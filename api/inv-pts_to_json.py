#!/usr/bin/env python3
# file name: inv-pts_to_json.py
# version: 2025-11-23-v2
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
#   add --api-print with --dry-diff

import requests
import json
import os
import re
import argparse
from collections import defaultdict
from deepdiff import DeepDiff

# ----------------------------------------------------------------------
# API & Auth
# ----------------------------------------------------------------------
BASE_URL = os.getenv("INVENTREE_URL")
if BASE_URL:
    BASE_URL = BASE_URL.rstrip("/")
    BASE_URL_PARTS = f"{BASE_URL}/api/part/"
    BASE_URL_CATEGORIES = f"{BASE_URL}/api/part/category/"
    BASE_URL_BOM = f"{BASE_URL}/api/bom/"
    BASE_URL_SUPPLIER_PARTS = f"{BASE_URL}/api/company/part/"
    BASE_URL_MANUFACTURER_PART = f"{BASE_URL}/api/company/part/manufacturer/"
    BASE_URL_PRICE_BREAK = f"{BASE_URL}/api/company/price-break/"
else:
    raise Exception("INVENTREE_URL must be set")

TOKEN = os.getenv("INVENTREE_TOKEN")
if not TOKEN:
    raise Exception("INVENTREE_TOKEN must be set")

HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# ----------------------------------------------------------------------
# Sanitizers
# ----------------------------------------------------------------------
def sanitize_category_name(name):
    sanitized = name.replace(' ', '_').replace('.', '')
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', sanitized.strip())
    return sanitized

def sanitize_part_name(name):
    sanitized = name.replace(' ', '_').replace('.', ',')
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', sanitized.strip())
    return sanitized

def sanitize_revision(rev):
    if not rev:
        return ""
    rev = str(rev).strip()
    rev = re.sub(r'[<>:"/\\|?*]', '_', rev)
    return rev

# ----------------------------------------------------------------------
# Fetch with pagination + API print
# ----------------------------------------------------------------------
def fetch_data(url, params=None, api_print=False):
    items = []
    while url:
        if api_print:
            param_str = f"?{requests.compat.urlencode(params or {})}" if params else ""
            print(f"API GET: {url}{param_str}")
        r = requests.get(url, headers=HEADERS, params=params or {})
        if r.status_code != 200:
            raise Exception(f"API error {r.status_code}: {r.text}")
        data = r.json()
        if api_print:
            if isinstance(data, dict) and "results" in data:
                count = len(data["results"])
                sample = json.dumps(data["results"][:2] if count else [], default=str)[:200]
                print(f"       -> {r.status_code} [{count} items] sample: {sample}...")
            else:
                preview = json.dumps(data, default=str)[:200]
                print(f"       -> {r.status_code} {preview}...")
        if isinstance(data, dict) and "results" in data:
            items.extend(data["results"])
            url = data.get("next")
        else:
            items.extend(data if isinstance(data, list) else [data])
            url = None
    return items

# ----------------------------------------------------------------------
# Save helper (skipped in dry-diff)
# ----------------------------------------------------------------------
def save_to_file(data, filepath, dry_diff=False):
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
def build_category_maps(categories):
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

def write_category_files(root_dir, pk_to_path, parent_to_subs, dry_diff=False):
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
def fetch_bom(part_pk, api_print=False):
    bom_items = fetch_data(f"{BASE_URL_BOM}?part={part_pk}", api_print=api_print)
    tree = []
    for item in bom_items:
        sub_pk = item.get("sub_part")
        if not sub_pk:
            continue
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
    return tree

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Pull parts from InvenTree -> data/pts/ (with diff mode)"
    )
    parser.add_argument("patterns", nargs="*", help='Glob patterns (e.g. "*_Table")')
    parser.add_argument("--dry-diff", action="store_true", help="Compare local JSON vs live InvenTree (no write)")
    parser.add_argument("--api-print", action="store_true", help="Show API calls + response preview")
    args = parser.parse_args()

    if not TOKEN or not BASE_URL:
        raise Exception("INVENTREE_TOKEN and INVENTREE_URL must be set")

    root_dir = "data/pts"

    print("DEBUG: Fetching categories...")
    categories = fetch_data(BASE_URL_CATEGORIES, api_print=args.api_print)
    pk_to_path, parent_to_subs = build_category_maps(categories)
    print("DEBUG: Writing category.json files...")
    write_category_files(root_dir, pk_to_path, parent_to_subs, dry_diff=args.dry_diff)

    # Filter logic
    patterns = []
    if args.patterns and not any(p in ["**/*", "*"] for p in args.patterns):
        for raw in args.patterns:
            pat = raw.removesuffix(".json").strip()
            if not pat:
                continue
            regex = "^" + re.escape(pat).replace("\\*", ".*").replace("\\?", ".") + "$"
            patterns.append(re.compile(regex, re.IGNORECASE))
        print(f"DEBUG: Filtering with {len(patterns)} patterns")
    else:
        print("DEBUG: No filter -> pulling ALL parts")

    print("DEBUG: Fetching all parts...")
    parts = fetch_data(BASE_URL_PARTS, api_print=args.api_print)
    all_parts = {part['pk']: part for part in parts if part.get('pk')}

    deps = defaultdict(list)
    for pk, part in all_parts.items():
        if part.get('variant_of'):
            deps[pk].append(part['variant_of'])
        if part.get('assembly') or part.get('is_template'):
            print(f"DEBUG: Fetching BOM for pk {pk} ({part.get('name')})")
            bom_tree = fetch_bom(pk, api_print=args.api_print)
            all_parts[pk]['bom_tree'] = bom_tree
            deps[pk].extend([item["sub_part"]["pk"] for item in bom_tree])

    level_memo = {}
    for pk in all_parts:
        get_level(pk, level_memo, deps)

    compared = 0
    for pk, part in all_parts.items():
        name = part.get("name")
        raw_rev = part.get("revision")
        cat_pk = part.get("category")
        if not (name and cat_pk):
            continue

        san_name = sanitize_part_name(name)
        if patterns and not any(p.search(san_name) for p in patterns):
            continue

        pathstring = pk_to_path.get(cat_pk)
        if not pathstring:
            print(f"WARNING: Part '{name}' (pk {pk}) has no category, skipping.")
            continue

        dir_parts = [sanitize_category_name(p) for p in pathstring.split("/")]
        level = level_memo.get(pk, 1)
        level_dir = os.path.join(root_dir, str(level), *dir_parts)

        revision = sanitize_revision(raw_rev)
        rev_suffix = f".{revision}" if revision else ""
        base_name = f"{san_name}{rev_suffix}"
        json_path = os.path.join(level_dir, f"{base_name}.json")

        # Build clean part data (same as save logic)
        variant_of_full = None
        if part.get("variant_of"):
            variant_pk = part["variant_of"]
            variant_part = all_parts.get(variant_pk)
            if variant_part:
                v_name = sanitize_part_name(variant_part.get("name", ""))
                v_rev = sanitize_revision(variant_part.get("revision"))
                v_rev_suffix = f".{v_rev}" if v_rev else ""
                variant_of_full = f"{v_name}{v_rev_suffix}"

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
            "suppliers": []  # Simplified for diff
        }

        if args.dry_diff:
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    local_data = json.load(f)
                diff = DeepDiff(local_data, current_data, ignore_order=True)
                if diff:
                    print(f"\nDIFF: {json_path}")
                    print(diff.pretty())
                else:
                    print(f"OK: {json_path} (identical)")
            else:
                print(f"NEW: {json_path} (would be created)")
            compared += 1
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
                        print(f"OK BOM: {bom_path} (identical)")
                else:
                    print(f"NEW BOM: {bom_path} (would be created)")
            else:
                save_to_file(bom_tree, bom_path)

    if args.dry_diff:
        print(f"\nDRY-DIFF: Compared {compared} parts")
    else:
        print(f"SUMMARY: Pulled {compared} parts + BOMs to {root_dir}/<level>/")

def get_level(pk, memo, deps):
    if pk in memo:
        return memo[pk]
    if not deps.get(pk):
        memo[pk] = 1
        return 1
    max_dep_level = max((get_level(dep_pk, memo, deps) for dep_pk in deps[pk]), default=0)
    memo[pk] = 1 + max_dep_level
    return memo[pk]

if __name__ == "__main__":
    try:
        from deepdiff import DeepDiff
    except ImportError:
        print("Install deepdiff for --dry-diff: pip install deepdiff")
        sys.exit(1)
    main()
