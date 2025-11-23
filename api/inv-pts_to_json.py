#!/usr/bin/env python3
# file name: inv-pts_to_json.py
# version: 2025-11-23-v6
# --------------------------------------------------------------
# Pull from inventree all parts (templates, assemblies, real parts)
# -> data/pts/<level>/<category_path>/
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
# * category.json files saved in data/pts/0/<category_path>/
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
# python3 ./api/inv-pts_to_json.py
# python3 ./api/inv-pts_to_json.py "**/*"        # <- pulls everything
# python3 ./api/inv-pts_to_json.py "Round_Table" --dry-run --api-print
# python3 ./api/inv-pts_to_json.py "*_Table"
# --------------------------------------------------------------
# Changelog:
#   fix --dry-diff exact name matching (no regex) when no wildcards used

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
                print(f"       → {r.status_code} [{c} items] sample: {s}...")
            else:
                preview = json.dumps(data, default=str)[:200]
                print(f"       → {r.status_code} {preview}...")
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
# Category handling
# ----------------------------------------------------------------------
def build_category_maps(categories: List[Dict]) -> tuple[Dict[int, str], Dict[str, List[Dict]]]:
    pk_to_path = {}
    parent_to_subs = {"None": []}
    for cat in categories:
        pk = cat.get("pk")
        name = cat.get("name")
        raw_path = cat.get("pathstring")
        parent = str(cat.get("parent")) if cat.get("parent") is not None else "None"
        if not (pk and name and raw_path):
            continue
        path_parts = raw_path.split("/")
        san_parts = [sanitize_category_name(p) for p in path_parts]
        san_path = "/".join(san_parts)
        san_name = sanitize_category_name(name)
        cat_mod = cat.copy()
        cat_mod["name"] = san_name
        cat_mod["pathstring"] = san_path
        cat_mod["image"] = ""
        pk_to_path[pk] = san_path
        parent_to_subs.setdefault(parent, []).append(cat_mod)
    return pk_to_path, parent_to_subs

def write_category_files(root_dir: str, pk_to_path: Dict[int, str], parent_to_subs: Dict[str, List[Dict]], dry_diff: bool = False) -> None:
    cat_root = os.path.join(root_dir, "0")
    top = parent_to_subs.get("None", [])
    if top:
        save_to_file(top, os.path.join(cat_root, "category.json"), dry_diff)
    for parent_pk, subs in parent_to_subs.items():
        if parent_pk == "None" or not subs:
            continue
        parent_path = pk_to_path.get(int(parent_pk))
        if not parent_path:
            continue
        dir_parts = [sanitize_category_name(p) for p in parent_path.split("/")]
        dir_path = os.path.join(cat_root, *dir_parts)
        save_to_file(subs, os.path.join(dir_path, "category.json"), dry_diff)

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
        sub_ipn = sub_part.get("IPN", "")
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
        description="Pull parts from InvenTree → data/pts/ (with diff mode)"
    )
    parser.add_argument("patterns", nargs="*", help='Part name or glob (e.g. Round_Table, "*_Table", "**/*")')
    parser.add_argument("--dry-diff", action="store_true", help="Compare local vs live (no write)")
    parser.add_argument("--api-print", action="store_true", help="Show API calls")
    args = parser.parse_args()

    root_dir = "data/pts"

    print("DEBUG: Fetching categories...")
    categories = fetch_data(BASE_URL_CATEGORIES, api_print=args.api_print)
    pk_to_path, parent_to_subs = build_category_maps(categories)
    print("DEBUG: Writing category.json files...")
    write_category_files(root_dir, pk_to_path, parent_to_subs, dry_diff=args.dry_diff)

    # Smart pattern handling
    exact_names = []
    glob_patterns = []
    for pat in args.patterns or []:
        pat = pat.strip()
        if not pat:
            continue
        if "*" in pat or "?" in pat:
            glob_patterns.append(pat)
        else:
            exact_names.append(pat)

    if glob_patterns:
        print(f"DEBUG: Using glob patterns: {glob_patterns}")
    if exact_names:
        print(f"DEBUG: Using exact names: {exact_names}")
    if not args.patterns:
        print("DEBUG: No patterns → pulling ALL parts")

    print("DEBUG: Fetching all parts...")
    parts = fetch_data(BASE_URL_PARTS, api_print=args.api_print)
    all_parts = {p['pk']: p for p in parts if p.get('pk')}

    deps = defaultdict(list)
    for pk, part in all_parts.items():
        if part.get('variant_of'):
            deps[pk].append(part['variant_of'])
        if part.get('assembly') or part.get('is_template'):
            print(f"DEBUG: Fetching BOM for pk {pk} ({part.get('name')})")
            bom_tree, sub_pks = fetch_bom(pk, api_print=args.api_print)
            all_parts[pk]['bom_tree'] = bom_tree
            deps[pk].extend(sub_pks)

    level_memo = {}
    for pk in all_parts:
        get_level(pk, level_memo, deps)

    compared = 0
    for pk, part in all_parts.items():
        name = part.get("name")
        if not name:
            continue

        # Match logic
        if exact_names and name not in exact_names:
            continue
        if glob_patterns:
            if not any(fnmatch.fnmatch(name, pat) for pat in glob_patterns):
                continue

        san_name = sanitize_part_name(name)
        cat_pk = part.get("category")
        if not cat_pk:
            continue

        pathstring = pk_to_path.get(cat_pk)
        if not pathstring:
            print(f"WARNING: Part '{name}' has no category path")
            continue

        dir_parts = [sanitize_category_name(p) for p in pathstring.split("/")]
        level = level_memo.get(pk, 1)
        level_dir = os.path.join(root_dir, str(level), *dir_parts)

        revision = sanitize_revision(part.get("revision"))
        rev_suffix = f".{revision}" if revision else ""
        base_name = f"{san_name}{rev_suffix}"
        json_path = os.path.join(level_dir, f"{base_name}.json")

        # Build current data
        variant_of_full = None
        if part.get("variant_of"):
            vp = all_parts.get(part["variant_of"])
            if vp:
                v_name = sanitize_part_name(vp.get("name", ""))
                v_rev = sanitize_revision(vp.get("revision"))
                variant_of_full = f"{v_name}.{v_rev}" if v_rev else v_name

        current_data = {
            "name": san_name,
            "revision": revision,
            "IPN": part.get("IPN", ""),
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
            "suppliers": []
        }

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
            compared += 1
        else:
            save_to_file(current_data, json_path)

        # BOM
        bom_tree = part.get('bom_tree', [])
        if bom_tree:
            bom_path = os.path.join(level_dir, f"{base_name}.bom.json")
            if args.dry_diff:
                if os.path.exists(bom_path):
                    with open(bom_path, "r") as f:
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

    if args.dry_diff:
        print(f"\nDRY-DIFF: Compared {compared} parts")
    else:
        print(f"SUMMARY: Pulled {compared} parts")

def get_level(pk: int, memo: Dict[int, int], deps: Dict[int, List[int]]) -> int:
    if pk in memo:
        return memo[pk]
    if not deps.get(pk):
        memo[pk] = 1
        return 1
    max_dep = max((get_level(d, memo, deps) for d in deps[pk]), default=0)
    memo[pk] = 1 + max_dep
    return memo[pk]

if __name__ == "__main__":
    import fnmatch  # ← Added for glob matching
    main()