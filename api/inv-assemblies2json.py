#!/usr/bin/env python3
# file name: inv-assemblies2json.py
# version: 2025-11-04-v4
# --------------------------------------------------------------
# Export **assemblies with BOMs** (single-level) → data/assemblies/
#
# * CLI glob patterns (e.g. "Widget_*", "*_Board")
# * Saves: Part_Name[.revision].json + Part_Name[.revision].bom.json
# * BOM: only direct sub-parts
# * Skips: non-assembly parts, templates
# * Handles missing/null revision safely
#
# example usage:
#   python3 ./api/inv-assemblies2json.py
#   python3 ./api/inv-assemblies2json.py "Widget_*"
# --------------------------------------------------------------
# see near bottom https://grok.com/share/c2hhcmQtMw%3D%3D_c721971e-5566-4a30-8129-040e6e84599f

import requests
import json
import os
import re
import argparse

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

def sanitize_revision(rev):
    """Sanitize revision string for filename."""
    if not rev:
        return ""
    rev = str(rev).strip()
    rev = re.sub(r'[<>:"/\\|?*]', '_', rev)
    return rev

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
# Single-level BOM fetcher
# ----------------------------------------------------------------------
def fetch_single_level_bom(part_pk):
    bom_items = fetch_data(f"{BASE_URL_BOM}?part={part_pk}")
    bom = []
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
        bom.append(node)
    return bom

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Export **assemblies with BOMs** (single-level) to data/assemblies/"
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns for sanitized assembly names (e.g. '*_Board'). Default: all."
    )
    args = parser.parse_args()

    if not TOKEN or not BASE_URL:
        raise Exception("INVENTREE_TOKEN and INVENTREE_URL must be set")

    root_dir = "data/assemblies"
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

    # 3. Fetch assemblies
    print("DEBUG: Fetching assemblies...")
    assemblies = fetch_data(BASE_URL_PARTS, params={"assembly": "true", "limit": 100})
    exported = 0

    for part in assemblies:
        pk = part.get("pk")
        name = part.get("name")
        raw_revision = part.get("revision")  # Can be null or missing
        cat_pk = part.get("category")
        if not (pk and name):
            continue

        # Skip templates
        if part.get("is_template"):
            print(f"DEBUG: Skipping template assembly: {name}")
            continue

        san_name = sanitize_part_name(name)

        # Pattern filter
        if patterns and not any(p.search(san_name) for p in patterns):
            continue

        pathstring = pk_to_path.get(cat_pk) if cat_pk else None
        if not pathstring:
            print(f"WARNING: Assembly '{name}' has no category, skipping.")
            continue

        dir_parts = [sanitize_category_name(p) for p in pathstring.split("/")]
        dir_path = os.path.join(root_dir, *dir_parts)

        # Handle revision safely
        revision = sanitize_revision(raw_revision)
        rev_suffix = f".{revision}" if revision else ""
        base_name = f"{san_name}{rev_suffix}"

        # Save clean part JSON
        part_clean = {
            "pk": pk,
            "name": san_name,
            "revision": revision,
            "IPN": part.get("IPN", ""),
            "description": part.get("description", ""),
            "assembly": True,
            "category": cat_pk,
            "image": "",
            "thumbnail": ""
        }
        save_to_file(part_clean, os.path.join(dir_path, f"{base_name}.json"))

        # Save single-level BOM
        print(f"DEBUG: Exporting BOM for: {base_name}")
        bom = fetch_single_level_bom(pk)
        bom_path = os.path.join(dir_path, f"{base_name}.bom.json")
        save_to_file(bom, bom_path)
        exported += 1

    print(f"SUMMARY: Exported {exported} assemblies + single-level BOMs to {root_dir}/")

if __name__ == "__main__":
    main()