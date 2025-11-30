#!/usr/bin/env python3
# file name: inv-parts_to_json.py
# version: 2025-11-22-v3
# --------------------------------------------------------------
# Pull from inventree **all parts** (templates, assemblies, real parts)
# -> data/parts/<level>/<category_path>/
#
# Organizes parts into dependency levels:
# - Level 1: Parts with no dependencies (no variant_of, no BOM sub-parts)
# - Higher levels: Based on max dependency level + 1
# Dependencies include variant_of and BOM sub-parts (if applicable)
#
# Features:
# * CLI glob patterns (e.g. "C_*_0402", "*_Table")
# * Saves: Part_Name[.revision].json
# * + Part_Name[.revision].bom.json for assemblies/templates with BOM
# * Skips parts with no category
# * Sanitized names/paths
# * Pulls suppliers/manufacturers/price breaks (aggregates duplicates)
# * category.json files saved in data/parts/0/<category_path>/
# * variant_of stored as "variant_of": "BaseName[.revision]"
#
# example usage:
# python3 ./api/inv-parts_to_json.py
# python3 ./api/inv-parts_to_json.py "**/*"        # <- pulls everything
# python3 ./api/inv-parts_to_json.py "Round_Table"
# python3 ./api/inv-parts_to_json.py "*_Table"
# --------------------------------------------------------------
# Changelog: revert to 7926e55008f6a7b7f95bab10e97b22c9e881bc01
# * Now pulls part.validated_bom -> saved in .json (controls big green "Validated" badge)
# * Now pulls BOM item "active" flag -> saved in .bom.json (required for BOM to be considered validated)
# * Now pulls BOM item "validated" flag -> saved in .bom.json


import requests
import json
import os
import re
import argparse
from collections import defaultdict

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
    BASE_URL_PARTS = BASE_URL_CATEGORIES = BASE_URL_BOM = None
    BASE_URL_SUPPLIER_PARTS = BASE_URL_MANUFACTURER_PART = BASE_URL_PRICE_BREAK = None

TOKEN = os.getenv("INVENTREE_TOKEN")
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

def sanitize_company_name(name):
    sanitized = name.replace(' ', '_').replace('.', '')
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', sanitized.strip())
    return sanitized

# ----------------------------------------------------------------------
# Fetch with pagination
# ----------------------------------------------------------------------
def fetch_data(url, params=None):
    items = []
    while url:
        r = requests.get(url, headers=HEADERS, params=params or {})
        if r.status_code != 200:
            raise Exception(f"API error {r.status_code}: {r.text}")
        data = r.json()
        if isinstance(data, dict) and "results" in data:
            items.extend(data["results"])
            url = data.get("next")
        elif isinstance(data, dict):
            items.append(data)
            url = None
        elif isinstance(data, list):
            items.extend(data)
            url = None
        else:
            raise Exception("Unexpected data type from API")
    return items

# ----------------------------------------------------------------------
# Save helper
# ----------------------------------------------------------------------
def save_to_file(data, filepath):
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

def write_category_files(root_dir, pk_to_path, parent_to_subs):
    cat_root = os.path.join(root_dir, "0")
    top = parent_to_subs.get("None", [])
    if top:
        save_to_file(top, os.path.join(cat_root, "category.json"))
    for parent_pk, subs in parent_to_subs.items():
        if parent_pk == "None" or not subs:
            continue
        parent_path = pk_to_path.get(int(parent_pk))
        if not parent_path:
            continue
        dir_parts = [sanitize_category_name(p) for p in parent_path.split("/")]
        dir_path = os.path.join(cat_root, *dir_parts)
        save_to_file(subs, os.path.join(dir_path, "category.json"))

# ----------------------------------------------------------------------
# BOM fetcher - includes active + validated
# ----------------------------------------------------------------------
def fetch_bom(part_pk):
    bom_items = fetch_data(f"{BASE_URL_BOM}?part={part_pk}")
    tree = []
    sub_pks = []
    for item in bom_items:
        sub_pk = item.get("sub_part")
        if not sub_pk:
            continue
        sub_pks.append(sub_pk)
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
    return tree, sub_pks

# ----------------------------------------------------------------------
# Supplier fetcher - quiet about duplicates
# ----------------------------------------------------------------------
def fetch_suppliers(part_pk, part_name):
    supplier_parts = fetch_data(BASE_URL_SUPPLIER_PARTS, params={"part": part_pk})
    suppliers_list = []
    for sp in supplier_parts:
        sp_details = {
            "supplier_name": sanitize_company_name(sp.get('supplier_detail', {}).get('name', '')),
            "SKU": sp.get('SKU', ''),
            "description": sp.get('description', ''),
            "link": sp.get('link', ''),
            "note": sp.get('note', ''),
            "packaging": sp.get('packaging', ''),
            "price_breaks": []
        }
        price_breaks = fetch_data(BASE_URL_PRICE_BREAK, params={"supplier_part": sp['pk']})
        pb_by_quantity = defaultdict(list)
        for pb in price_breaks:
            q = pb.get('quantity', 0)
            pb_by_quantity[q].append(pb)
        for q, pbs in pb_by_quantity.items():
            selected = max(pbs, key=lambda x: x.get('updated', ''))
            sp_details['price_breaks'].append({
                "quantity": q,
                "price": selected.get('price', 0.0),
                "price_currency": selected.get('price_currency', '')
            })
        sp_details['price_breaks'].sort(key=lambda x: x['quantity'])
        if sp.get('manufacturer_part'):
            mp_resp = fetch_data(f"{BASE_URL_MANUFACTURER_PART}{sp['manufacturer_part']}/")
            if mp_resp:
                mp = mp_resp[0] if isinstance(mp_resp, list) else mp_resp
                sp_details['manufacturer_name'] = sanitize_company_name(mp.get('manufacturer_detail', {}).get('name', ''))
                sp_details['MPN'] = mp.get('MPN', '')
                sp_details['mp_description'] = mp.get('description', '')
                sp_details['mp_link'] = mp.get('link', '')
        suppliers_list.append(sp_details)
    return suppliers_list

# ----------------------------------------------------------------------
# Level computation
# ----------------------------------------------------------------------
def get_level(pk, memo, deps):
    if pk in memo:
        return memo[pk]
    if not deps.get(pk):
        memo[pk] = 1
        return 1
    max_dep_level = max((get_level(dep_pk, memo, deps) for dep_pk in deps[pk]), default=0)
    memo[pk] = 1 + max_dep_level
    return memo[pk]

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Pull all parts (templates, assemblies, real) to data/parts/<level>/, organized by dependency levels."
    )
    parser.add_argument(
        "patterns", nargs="*",
        help='Glob patterns for sanitized part names (e.g. "*_Table"). Use "**/*" or nothing to pull everything.'
    )
    args = parser.parse_args()

    if not TOKEN or not BASE_URL:
        raise Exception("INVENTREE_TOKEN and INVENTREE_URL must be set")

    root_dir = "data/parts"
    os.makedirs(root_dir, exist_ok=True)

    print("DEBUG: Fetching categories...")
    categories = fetch_data(BASE_URL_CATEGORIES)
    pk_to_path, parent_to_subs = build_category_maps(categories)
    print("DEBUG: Writing category.json files...")
    write_category_files(root_dir, pk_to_path, parent_to_subs)

    # Special case: "**/*" or no patterns → pull everything
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
    parts = fetch_data(BASE_URL_PARTS)
    all_parts = {part['pk']: part for part in parts if part.get('pk')}

    deps = defaultdict(list)
    for pk, part in all_parts.items():
        if part.get('variant_of'):
            deps[pk].append(part['variant_of'])
        if part.get('assembly') or part.get('is_template'):
            print(f"DEBUG: Fetching BOM for pk {pk} ({part.get('name')})")
            bom_tree, bom_pks = fetch_bom(pk)
            all_parts[pk]['bom_tree'] = bom_tree
            deps[pk].extend(bom_pks)

    level_memo = {}
    for pk in all_parts:
        get_level(pk, level_memo, deps)

    exported = 0
    for pk, part in all_parts.items():
        name = part.get("name")
        raw_rev = part.get("revision")
        cat_pk = part.get("category")
        if not (name and cat_pk):
            continue

        san_name = sanitize_part_name(name)

        # Apply filter only if patterns exist and it's not the "pull all" case
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

        suppliers = fetch_suppliers(pk, name) if part.get("purchaseable", False) else []

        # Resolve variant_of with revision
        variant_of_full = None
        if part.get("variant_of"):
            variant_pk = part["variant_of"]
            variant_part = all_parts.get(variant_pk)
            if not variant_part:
                variant_r = requests.get(f"{BASE_URL_PARTS}{variant_pk}/", headers=HEADERS)
                if variant_r.status_code == 200:
                    variant_part = variant_r.json()
            if variant_part:
                v_name = sanitize_part_name(variant_part.get("name", ""))
                v_rev_raw = variant_part.get("revision")
                v_rev = sanitize_revision(v_rev_raw)
                v_rev_suffix = f".{v_rev}" if v_rev else ""
                variant_of_full = f"{v_name}{v_rev_suffix}"

        part_clean = {
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
            "suppliers": suppliers
        }

        save_to_file(part_clean, os.path.join(level_dir, f"{base_name}.json"))

        bom_tree = part.get('bom_tree', [])
        save_bom = (part.get('assembly') or (part.get('is_template') and bom_tree))
        if save_bom:
            bom_path = os.path.join(level_dir, f"{base_name}.bom.json")
            save_to_file(bom_tree, bom_path)
            print(f"DEBUG: Saved BOM to {bom_path}")
        else:
            print(f"DEBUG: No BOM saved for {base_name}")

        exported += 1

    print(f"SUMMARY: Pulled {exported} parts + BOMs (when applicable) to {root_dir}/<level>/")

if __name__ == "__main__":
    main()
