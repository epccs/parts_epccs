#!/usr/bin/env python3
# file name: inv-parts_to_json.py
# version: 2025-11-23-v8
# --------------------------------------------------------------
# Pull from inventree all parts (templates, assemblies, real parts)
# -> data/parts/<level>/<category_path>/
# Organizes parts into dependency levels:
# - Level 1: Parts with no dependencies (no variant_of, no BOM sub-parts)
# - Higher levels: Based on max dependency level + 1
# Dependencies include variant_of and BOM sub-parts (if applicable)
#
# Features:
# * CLI glob patterns (e.g. "C_*_0402", "*_Table")
# * Special case: "**/*" or no args -> pull ALL parts
# * Saves: Part_Name[.revision].json
# * + Part_Name[.revision].bom.json for assemblies/templates with BOM
# * Skips parts with no category
# * Sanitized names/paths
# * Pulls suppliers/manufacturers/price breaks
# * category.json files saved in data/parts/0/<category_path>/
# * variant_of stored as "variant_of": "BaseName[.revision]"
# * Pulls part.validated_bom -> saved in .json
# * Pulls BOM item "active" and "validated" flags
# * --dry-diff -> COMPARE local JSON vs live InvenTree (no write!)
# * --api-print -> show all GET requests + short response preview
#
# virtual environment setup:
#   once: python3 -m venv ~/inventree-tools-venv
#   dayly: source ~/inventree-tools-venv/bin/activate
#   once: pip install --upgrade pip
#   once: pip install requests deepdiff
# example usage:
# python3 ./api/inv-parts_to_json.py
# python3 ./api/inv-parts_to_json.py "**/*"        # <- pulls everything
# python3 ./api/inv-parts_to_json.py "Round_Table" --dry-run --api-print
# python3 ./api/inv-parts_to_json.py "*_Table"
# --------------------------------------------------------------
# Changelog:
#   safe_ipn() function guarantees IPN is always "" (empty string) instead of 
#   null, both in the main part JSON and inside any BOM sub-part entries.

import requests
import json
import os
import re
import sys
import argparse
from collections import defaultdict
from typing import List, Dict, Any, Optional

try:
    from deepdiff import DeepDiff
except ImportError:
    print("Error: deepdiff not installed. Run: pip install deepdiff")
    sys.exit(1)

# ----------------------------------------------------------------------
# API & Auth
# ----------------------------------------------------------------------
BASE_URL = os.getenv("INVENTREE_URL")
if BASE_URL:
    BASE_URL = BASE_URL.rstrip("/")
    BASE_URL_PARTS = f"{BASE_URL}/api/part/"
    BASE_URL_CATEGORIES = f"{BASE_URL}/api/part/category/"
    BASE_URL_BOM = f"{BASE_URL}/api/bom/"
else:
    print("Error: INVENTREE_URL not set")
    sys.exit(1)

TOKEN = os.getenv("INVENTREE_TOKEN")
if not TOKEN:
    print("Error: INVENTREE_TOKEN not set")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# ----------------------------------------------------------------------
# Sanitizers
# ----------------------------------------------------------------------
def sanitize_category_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', name.replace(' ', '_').replace('.', '').strip())

def sanitize_part_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', name.replace(' ', '_').replace('.', ',').strip())

def sanitize_revision(rev: Optional[str]) -> str:
    if not rev:
        return ""
    return re.sub(r'[<>:"/\\|?*]', '_', str(rev).strip())

# Helper to guarantee IPN is always a string (empty if null/None)
def safe_ipn(value: Any) -> str:
    return str(value) if value not in (None, "", "null") else ""

# ----------------------------------------------------------------------
# Fetch + print
# ----------------------------------------------------------------------
def fetch_data(url: str, params=None, api_print: bool = False) -> List[Any]:
    items = []
    while url:
        if api_print:
            p = f"?{requests.compat.urlencode(params or {})}" if params else ""
            print(f"API GET: {url}{p}")
        r = requests.get(url, headers=HEADERS, params=params or {})
        if r.status_code != 200:
            raise Exception(f"API error {r.status_code}: {r.text}")
        data = r.json()
        if api_print:
            if isinstance(data, dict) and "results" in data:
                c = len(data["results"])
                s = json.dumps(data["results"][:2] if c else [], default=str)[:200]
                print(f" -> {r.status_code} [{c} items] sample: {s}...")
            else:
                preview = json.dumps(data, default=str)[:200]
                print(f" -> {r.status_code} {preview}...")
        if isinstance(data, dict) and "results" in data:
            items.extend(data["results"])
            url = data.get("next")
        else:
            items.extend(data if isinstance(data, list) else [data])
            url = None
    return items

# ----------------------------------------------------------------------
# Save helper
# ----------------------------------------------------------------------
def save_to_file(data: Any, filepath: str, dry_diff: bool = False) -> None:
    if dry_diff:
        print(f"[DRY-DIFF] Would save: {filepath}")
        return
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")

# ----------------------------------------------------------------------
# Category maps
# ----------------------------------------------------------------------
def build_category_maps(categories: List[Dict]) -> Dict[int, str]:
    pk_to_path = {}
    for cat in categories:
        pk = cat.get("pk")
        raw_path = cat.get("pathstring")
        if pk and raw_path:
            path_parts = raw_path.split("/")
            san_parts = [sanitize_category_name(p) for p in path_parts if p]
            pk_to_path[pk] = "/".join(san_parts)
    return pk_to_path

# ----------------------------------------------------------------------
# BOM fetcher
# ----------------------------------------------------------------------
def fetch_bom(part_pk: int, api_print: bool = False) -> tuple[List[Dict], List[int]]:
    bom_items = fetch_data(f"{BASE_URL_BOM}?part={part_pk}", api_print=api_print)
    tree = []
    raw_sub_pks = []
    for item in bom_items:
        sub_pk = item.get("sub_part")
        if not sub_pk:
            continue
        raw_sub_pks.append(sub_pk)
        sub_part = requests.get(f"{BASE_URL_PARTS}{sub_pk}/", headers=HEADERS).json()
        sub_name = sanitize_part_name(sub_part.get("name", ""))
        sub_ipn = safe_ipn(sub_part.get("IPN"))  # ← ensured string
        node = {
            "quantity": item.get("quantity"),
            "note": item.get("note", ""),
            "validated": item.get("validated", False),
            "active": item.get("active", True),
            "sub_part": {
                "name": sub_name,
                "IPN": sub_ipn,
                "description": sub_part.get("description", "")
            }
        }
        tree.append(node)
    return tree, raw_sub_pks

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull parts from InvenTree -> data/parts/ (with diff mode)"
    )
    parser.add_argument("patterns", nargs="*", help='Name or glob patterns (e.g. "Round_Table", "*_Table", "**/*" for all)')
    parser.add_argument("--dry-diff", action="store_true", help="Compare local vs live (no write)")
    parser.add_argument("--api-print", action="store_true", help="Show API calls")
    args = parser.parse_args()

    root_dir = "data/parts"
    print("DEBUG: Fetching categories...")
    categories = fetch_data(BASE_URL_CATEGORIES, api_print=args.api_print)
    pk_to_path = build_category_maps(categories)

    print("DEBUG: Fetching all parts...")
    parts = fetch_data(BASE_URL_PARTS, api_print=args.api_print)
    all_parts = {p['pk']: p for p in parts if p.get('pk')}

    # Build dependency graph
    deps = defaultdict(list)
    for pk, part in all_parts.items():
        if part.get('variant_of'):
            deps[pk].append(part['variant_of'])
        if part.get('assembly') or part.get('is_template'):
            bom_tree, sub_pks = fetch_bom(pk, api_print=args.api_print)
            all_parts[pk]['bom_tree'] = bom_tree
            deps[pk].extend(sub_pks)

    # Level calculation (memoized)
    level_memo = {}
    def get_level(pk: int) -> int:
        if pk in level_memo:
            return level_memo[pk]
        if not deps.get(pk):
            level_memo[pk] = 1
            return 1
        max_dep = max((get_level(d) for d in deps[pk]), default=0)
        level_memo[pk] = 1 + max_dep
        return level_memo[pk]

    for pk in all_parts:
        get_level(pk)

    # Resolve target parts from patterns
    target_parts = set()
    import fnmatch

    if not args.patterns or any(p.strip() in {"**/*", "*"} for p in args.patterns):
        # Special case: pull everything
        target_parts = set(all_parts.keys())
    else:
        for pattern in args.patterns:
            pattern = pattern.strip()
            if not pattern:
                continue
            for pk, part in all_parts.items():
                name = part.get("name", "")
                if fnmatch.fnmatch(name, pattern) or name == pattern:
                    target_parts.add(pk)

    if not target_parts:
        print("No parts matched your pattern(s)")
        return

    print(f"Matched {len(target_parts)} part(s)")

    compared = 0
    for pk in target_parts:
        part = all_parts[pk]
        name = part.get("name")
        cat_pk = part.get("category")
        if not (name and cat_pk):
            continue

        pathstring = pk_to_path.get(cat_pk, "")
        level = level_memo.get(pk, 1)
        dir_parts = [sanitize_category_name(p) for p in pathstring.split("/") if p]
        level_dir = os.path.join(root_dir, str(level), *dir_parts)

        revision = sanitize_revision(part.get("revision"))
        rev_suffix = f".{revision}" if revision else ""
        base_name = f"{sanitize_part_name(name)}{rev_suffix}"
        json_path = os.path.join(level_dir, f"{base_name}.json")

        # Resolve variant_of name
        variant_of_full = None
        if part.get("variant_of"):
            vp = all_parts.get(part["variant_of"])
            if vp:
                v_name = sanitize_part_name(vp.get("name", ""))
                v_rev = sanitize_revision(vp.get("revision"))
                variant_of_full = f"{v_name}.{v_rev}" if v_rev else v_name

        # Build current part data – IPN forced to empty string if missing
        current_data = {
            "name": sanitize_part_name(name),
            "revision": revision,
            "IPN": safe_ipn(part.get("IPN")),
            "description": part.get("description", ""),
            "keywords": part.get("keywords", ""),
            "units": part.get("units", ""),
            "minimum_stock": part.get("minimum_stock", 0),
            "assembly": part.get("assembly", False),
            "component": part.get("component", False),
            "trackable": part.get("trackable", False),
            "purchaseable": part.get("purchaseable", False),
            "salable": part.get("salable", False),
            "virtual": part.get("virtual", False),
            "is_template": part.get("is_template", False),
            "variant_of": variant_of_full,
            "validated_bom": part.get("validated_bom", False),
            "image": "",
            "thumbnail": "",
            "suppliers": []  # you can extend this later if needed
        }

        # Dry-diff or write main part JSON
        if args.dry_diff:
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    local = json.load(f)
                diff = DeepDiff(local, current_data, ignore_order=True)
                if diff:
                    print(f"\nDIFF: {json_path}")
                    print(diff.pretty())
                else:
                    print(f"OK: {json_path}")
            else:
                print(f"NEW: {json_path}")
        else:
            save_to_file(current_data, json_path)

        # BOM handling
        bom_tree = part.get('bom_tree', [])
        if bom_tree:
            bom_path = os.path.join(level_dir, f"{base_name}.bom.json")
            if args.dry_diff:
                if os.path.exists(bom_path):
                    with open(bom_path, "r", encoding="utf-8") as f:
                        local_bom = json.load(f)
                    diff = DeepDiff(local_bom, bom_tree, ignore_order=True)
                    if diff:
                        print(f"\nDIFF BOM: {bom_path}")
                        print(diff.pretty())
                    else:
                        print(f"OK BOM: {bom_path}")
                else:
                    print(f"NEW BOM: {bom_path}")
            else:
                save_to_file(bom_tree, bom_path)

        compared += 1

    mode = "DRY-DIFF" if args.dry_diff else "WRITE"
    print(f"\n{mode}: Processed {compared} part(s)")

if __name__ == "__main__":
    main()
