#!/usr/bin/env python3
# file name: inv-template2json.py
# version: 2025-11-03-v2
# --------------------------------------------------------------
# Export InvenTree template parts + **recursive BOM** to:
#   data/templates/<category>/Part_Name.json
#   data/templates/<category>/Part_Name.bom.json
#
# * Separate files for easy import
# * Full subassembly nesting in .bom.json
# * Glob filtering on sanitized names
# --------------------------------------------------------------
# example usage:
# # Export every template part BOM
# python3 ./api/inv-template2json.py
#
# # Export only Table (e.g. "Squar_Table", "Round_Table") templates
# python3 ./api/inv-template2json.py "*_Table"
# --------------------------------------------------------------
# File Structure of dev data after running with "*_Table":
# data/templates/
# ├── Furniture/
# │   ├── Tables/
# │   │   ├── Round_Table.json
# │   │   ├── Round_Table.bom.json
# │   │   ├── Square_Table.json
# │   │   ├── Square_Table.bom.json
# │   └── category.json
# └── category.json
# --------------------------------------------------------------

import requests
import json
import os
import re
import argparse
from urllib.parse import urlparse

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
    BASE_URL_PARTS = BASE_URL_CATEGORIES = BASE_URL_BOM = None

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
# Category maps
# ----------------------------------------------------------------------
def build_category_maps(categories):
    pk_to_path = {}
    parent_to_subs = {"None": []}
    for cat in categories:
        pk = cat.get("pk")
        name = cat.get("name")
        path = cat.get("pathstring")
        parent = str(cat.get("parent")) if cat.get("parent") is not None else "None"
        if not (pk and name and path):
            continue
        san_name = sanitize_category_name(name)
        cat_mod = cat.copy()
        cat_mod["name"] = san_name
        cat_mod["image"] = ""
        parts = path.split("/")
        parts[-1] = san_name
        san_path = "/".join(parts)
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
# Recursive BOM fetcher
# ----------------------------------------------------------------------
def fetch_recursive_bom(part_pk, visited=None, depth=0, max_depth=10):
    """Return full BOM tree with subassemblies expanded."""
    if visited is None:
        visited = set()
    if part_pk in visited or depth > max_depth:
        return []

    visited.add(part_pk)
    bom_items = fetch_data(f"{BASE_URL_BOM}?part={part_pk}")
    tree = []

    for item in bom_items:
        sub_pk = item.get("sub_part")
        if not sub_pk:
            continue

        # Get sub_part detail
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
            },
            "children": []
        }

        # Recurse into subassembly if it's a template or has BOM
        if sub_part.get("is_template") or any(b.get("part") == sub_pk for b in bom_items):
            node["children"] = fetch_recursive_bom(sub_pk, visited.copy(), depth + 1, max_depth)

        tree.append(node)

    return tree

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Export template parts + **recursive BOM** to separate .json and .bom.json files."
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
        print(f"DEBUG: Filtering with pattern(s): {args.patterns}")

    # 3. Fetch templates
    print("DEBUG: Fetching template parts...")
    templates = fetch_data(BASE_URL_PARTS, params={"is_template": "true", "limit": 100})

    exported = 0
    for part in templates:
        pk = part.get("pk")
        name = part.get("name")
        cat_pk = part.get("category")
        if not (pk and name):
            continue

        san_name = sanitize_part_name(name)
        if patterns and not any(p.search(san_name) for p in patterns):
            continue

        pathstring = pk_to_path.get(cat_pk) if cat_pk else None
        if not pathstring:
            print(f"WARNING: Template '{name}' has no category, skipping.")
            continue

        dir_parts = [sanitize_category_name(p) for p in pathstring.split("/")]
        dir_path = os.path.join(root_dir, *dir_parts)

        # --- Save clean part JSON ---
        part_clean = {
            "pk": part.get("pk"),
            "name": san_name,
            "IPN": part.get("IPN", ""),
            "description": part.get("description", ""),
            "revision": part.get("revision", ""),
            "is_template": True,
            "category": cat_pk,
            "image": "",
            "thumbnail": ""
        }
        save_to_file(part_clean, os.path.join(dir_path, f"{san_name}.json"))

        # --- Save recursive BOM ---
        print(f"DEBUG: Exporting BOM tree for: {san_name}")
        bom_tree = fetch_recursive_bom(pk)
        bom_path = os.path.join(dir_path, f"{san_name}.bom.json")
        save_to_file(bom_tree, bom_path)

        exported += 1

    print(f"SUMMARY: Exported {exported} templates + recursive BOMs to {root_dir}/")
    print("         Use *.json for part import, *.bom.json for BOM import.")

if __name__ == "__main__":
    main()