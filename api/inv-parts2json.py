#!/usr/bin/env python3
# file name: inv-parts2json.py
# version: 2025-11-05-v2
# --------------------------------------------------------------
# Export **real parts only** (no assemblies, no templates)
# → data/parts/
#
# * CLI glob patterns (e.g. "C_*_0402", "C_*_0?0?")
# * Skips: assembly=True, is_template=True
# * Creates category folders + category.json
# * **Revision in filename** if present
# * No args → export all real parts
#
# example usage:
#   python3 ./api/inv-parts2json.py
#   python3 ./api/inv-parts2json.py "C_*_0402"
#   python3 ./api/inv-parts2json.py "C_*_0?0?"
# --------------------------------------------------------------
# File Structure of dev data after running with "*_Top":
# data/parts/
# ├── Furniture/
# │   ├── Tables/
# │   │   ├── Round_Top.[version.]json
# │   │   ├── Square_Top.[version.]json
# │   └── category.json
# └── category.json
# --------------------------------------------------------------

import requests
import json
import os
import re
import argparse

# ----------------------------------------------------------------------
# API endpoints & auth
# ----------------------------------------------------------------------
BASE_URL = os.getenv("INVENTREE_URL")
if BASE_URL:
    BASE_URL = BASE_URL.rstrip("/")
    BASE_URL_PARTS      = f"{BASE_URL}/api/part/"
    BASE_URL_CATEGORIES = f"{BASE_URL}/api/part/category/"
else:
    BASE_URL_PARTS = BASE_URL_CATEGORIES = None

TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json"
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
# Fetch data (handles pagination)
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
# Save JSON
# ----------------------------------------------------------------------
def save_to_file(data, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.write("\n")

# ----------------------------------------------------------------------
# Build category maps – sanitized pathstring
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
        # Sanitize each part of the path
        path_parts = raw_path.split("/")
        san_parts = [sanitize_category_name(p) for p in path_parts]
        san_path = "/".join(san_parts)
        san_name = sanitize_category_name(name)
        cat_mod = cat.copy()
        cat_mod["name"] = san_name
        cat_mod["pathstring"] = san_path  # sanitized pathstring
        cat_mod["image"] = ""
        pk_to_path[pk] = san_path
        parent_to_subs.setdefault(parent, []).append(cat_mod)
    return pk_to_path, parent_to_subs

# ----------------------------------------------------------------------
# Write category.json files
# ----------------------------------------------------------------------
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
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Export **real parts only** (no assemblies/templates) to data/parts/"
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns for **sanitized** part names (e.g. 'C_*_0402'). Default: all real parts."
    )
    args = parser.parse_args()

    if not TOKEN:
        raise Exception("INVENTREE_TOKEN not set")
    if not BASE_URL:
        raise Exception("INVENTREE_URL not set")

    root_dir = "data/parts"
    os.makedirs(root_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Fetch categories
    # ------------------------------------------------------------------
    print("DEBUG: Fetching categories...")
    categories = fetch_data(BASE_URL_CATEGORIES)
    pk_to_path, parent_to_subs = build_category_maps(categories)

    # ------------------------------------------------------------------
    # 2. Write category files
    # ------------------------------------------------------------------
    print("DEBUG: Writing category files...")
    write_category_files(root_dir, pk_to_path, parent_to_subs)

    # ------------------------------------------------------------------
    # 3. Compile glob patterns
    # ------------------------------------------------------------------
    patterns = []
    if args.patterns:
        for raw in args.patterns:
            pat = raw.removesuffix(".json").strip()
            if not pat:
                continue
            regex = "^" + re.escape(pat).replace("\\*", ".*").replace("\\?", ".") + "$"
            patterns.append(re.compile(regex, re.IGNORECASE))
        print(f"DEBUG: Filtering with {len(patterns)} patterns")

    # ------------------------------------------------------------------
    # 4. Fetch & export **real parts only**
    # ------------------------------------------------------------------
    print("DEBUG: Fetching parts...")
    parts = fetch_data(BASE_URL_PARTS)
    exported = 0

    for part in parts:
        cat_pk = part.get("category")
        name   = part.get("name")
        raw_rev = part.get("revision")  # can be null
        if not (cat_pk and name):
            continue

        # Skip assemblies and templates
        if part.get("assembly") or part.get("is_template"):
            print(f"DEBUG: Skipping assembly/template: {name}")
            continue

        san_name = sanitize_part_name(name)
        revision = sanitize_revision(raw_rev)
        rev_suffix = f".{revision}" if revision else ""
        base_name = f"{san_name}{rev_suffix}"

        # Apply pattern filter
        if patterns and not any(p.search(san_name) for p in patterns):
            continue

        # Build path
        pathstring = pk_to_path.get(cat_pk)
        if not pathstring:
            continue
        dir_parts = [sanitize_category_name(p) for p in pathstring.split("/")]
        dir_path = os.path.join(root_dir, *dir_parts)

        # Save
        part_mod = part.copy()
        part_mod["name"] = san_name
        part_mod["revision"] = revision  # keep in JSON
        part_mod["image"] = ""
        part_mod["thumbnail"] = ""
        part_file = os.path.join(dir_path, f"{base_name}.json")
        save_to_file(part_mod, part_file)
        exported += 1

    print(f"SUMMARY: Exported {exported} real parts")

if __name__ == "__main__":
    main()
