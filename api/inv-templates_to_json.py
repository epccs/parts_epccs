#!/usr/bin/env python3
# file name: inv-templates_to_json.py
# version: 2025-11-14-v2
# --------------------------------------------------------------
# Pull from inventree **template parts** + **single-level BOM** to:
# data/templates/<category>/Part_Name[.revision].json
# data/templates/<category>/Part_Name[.revision].bom.json (only if BOM exists)
#
# * CLI glob patterns (e.g. "*_Table")
# * Revision in filename if present
# * Sanitized pathstring in category.json
# * No .bom.json if no BOM items
# * Compatible with json_to_inv-templates.py
# * pulls suppliers/manufacturers/price breaks like parts
# * aggregate duplicate price breaks during pull since the InvTree API does not allow duplicate price breaks to be pushed.
#
# example usage:
# python3 ./api/inv-templates_to_json.py
# python3 ./api/inv-templates_to_json.py "*_Table"
# python3 ./api/inv-templates_to_json.py "Round_Table"
# --------------------------------------------------------------
# File Structure of dev data after running with "Round_Table":
# data/templates/
# +-- Furniture/
# ¦ +-- Tables/
# ¦ ¦ +-- Round_Table.[version.]json
# ¦ ¦ +-- [Round_Table.[version.]bom.json] (if BOM exists)
# ¦ +-- category.json
# +-- category.json
# --------------------------------------------------------------

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
    """Sanitize revision string for filename."""
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
        else:
            items.extend(data)
            url = None
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
# Category maps – sanitized pathstring
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
    top = parent_to_subs.get("None", [])
    if top:
        save_to_file(top, os.path.join(root_dir, "category.json"))
    for parent_pk, subs in parent_to_subs.items():
        if parent_pk == "None" or not subs:
            continue
        parent_path = pk_to_path.get(int(parent_pk))
        if not parent_path:
            continue
        dir_parts = [sanitize_category_name(p) for p in parent_path.split("/")]
        dir_path = os.path.join(root_dir, *dir_parts)
        save_to_file(subs, os.path.join(dir_path, "category.json"))
# ----------------------------------------------------------------------
# Single-level BOM fetcher
# ----------------------------------------------------------------------
def fetch_bom(part_pk):
    bom_items = fetch_data(f"{BASE_URL_BOM}?part={part_pk}")
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
            "sub_part": {
                "pk": sub_pk,
                "name": sub_name,
                "IPN": sub_ipn,
                "description": sub_part.get("description", "")
            }
        }
        tree.append(node)
    return tree
# ----------------------------------------------------------------------
# Fetch and add supplier details
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
            if len(pbs) > 1:
                print(f"Found {len(pbs) - 1} duplicates for quantity {q} in SupplierPart for part '{part_name}' supplier '{sp_details['supplier_name']}'")
            selected = max(pbs, key=lambda x: x.get('updated', ''))
            sp_details['price_breaks'].append({
                "quantity": q,
                "price": selected.get('price', 0.0),
                "price_currency": selected.get('price_currency', '')
            })
        sp_details['price_breaks'].sort(key=lambda x: x['quantity'])
        if sp.get('manufacturer_part'):
            mp_url = f"{BASE_URL_MANUFACTURER_PART}{sp['manufacturer_part']}/"
            mp = fetch_data(mp_url)
            if mp:
                mp = mp[0]
                sp_details['manufacturer_name'] = sanitize_company_name(mp.get('manufacturer_detail', {}).get('name', ''))
                sp_details['MPN'] = mp.get('MPN', ''),
                sp_details['mp_description'] = mp.get('description', '')
                sp_details['mp_link'] = mp.get('link', '')
        suppliers_list.append(sp_details)
    return suppliers_list
# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Pull template parts + **single-level BOM** to separate .json and .bom.json files."
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns for sanitized template names (e.g. '*_Table'). Default: all."
    )
    args = parser.parse_args()
    if not TOKEN or not BASE_URL:
        raise Exception("INVENTREE_TOKEN and INVENTREE_URL must be set")
    root_dir = "data/templates"
    os.makedirs(root_dir, exist_ok=True)
    # 1. Categories
    print("DEBUG: Fetching categories...")
    categories = fetch_data(BASE_URL_CATEGORIES)
    pk_to_path, parent_to_subs = build_category_maps(categories)
    print("DEBUG: Writing category.json files...")
    write_category_files(root_dir, pk_to_path, parent_to_subs)
    # 2. Compile patterns
    patterns = []
    if args.patterns:
        for raw in args.patterns:
            pat = raw.removesuffix(".json").strip()
            if not pat:
                continue
            regex = "^" + re.escape(pat).replace("\\*", ".*").replace("\\?", ".") + "$"
            patterns.append(re.compile(regex, re.IGNORECASE))
        print(f"DEBUG: Filtering with {len(patterns)} patterns")
    # 3. Fetch templates
    print("DEBUG: Fetching template parts...")
    templates = fetch_data(BASE_URL_PARTS, params={"is_template": "true", "limit": 100})
    exported = 0
    for part in templates:
        pk = part.get("pk")
        name = part.get("name")
        raw_rev = part.get("revision")
        cat_pk = part.get("category")
        if not (pk and name):
            continue
        san_name = sanitize_part_name(name)
        revision = sanitize_revision(raw_rev)
        rev_suffix = f".{revision}" if revision else ""
        base_name = f"{san_name}{rev_suffix}"
        # Pattern filter
        if patterns and not any(p.search(san_name) for p in patterns):
            continue
        pathstring = pk_to_path.get(cat_pk) if cat_pk else None
        if not pathstring:
            print(f"WARNING: Template '{name}' has no category, skipping.")
            continue
        dir_parts = [sanitize_category_name(p) for p in pathstring.split("/")]
        dir_path = os.path.join(root_dir, *dir_parts)
        # Fetch suppliers only if purchaseable
        suppliers = fetch_suppliers(pk, name) if part.get("purchaseable", False) else []
        # Save clean part JSON with suppliers
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
            "is_template": True,
            "category": cat_pk,
            "image": "",
            "thumbnail": "",
            "suppliers": suppliers
        }
        save_to_file(part_clean, os.path.join(dir_path, f"{base_name}.json"))
        # Save single-level BOM **only if not empty**
        print(f"DEBUG: Fetching BOM for: {base_name}")
        bom_tree = fetch_bom(pk)
        if bom_tree: # Only write if BOM has items
            bom_path = os.path.join(dir_path, f"{base_name}.bom.json")
            save_to_file(bom_tree, bom_path)
            print(f"DEBUG: Saved BOM ? {bom_path}")
        else:
            print(f"DEBUG: No BOM items for {base_name} – skipping .bom.json")
        exported += 1
    print(f"SUMMARY: Pulled {exported} templates + BOMs (only when present) to {root_dir}/")
    print(" Use *.json for part push to inventree, *.bom.json for BOM push (if exists).")
if __name__ == "__main__":
    main()
