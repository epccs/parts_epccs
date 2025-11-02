#!/usr/bin/env python3
# file name: inv-parts2json.py
# version: 2025-11-01-v1
# --------------------------------------------------------------
# Export InvenTree parts + categories → data/parts/ hierarchy
#
# * CLI glob patterns (e.g. "C_*_0402", "C_*_0?0?") are matched
#   **after** sanitizing the part name.
# * Creates category folders + category.json files as needed.
# * No arguments → export **all** parts/categories.
#
# example usage:
#   # Export everything
#   python3 ./api/inv-parts2json.py
#
#   # Export only 0402 capacitors
#   python3 ./api/inv-parts2json.py "C_*_0402"
#
#   # Export capacitors with 0x0x size (e.g. 0402, 0603)
#   python3 ./api/inv-parts2json.py "C_*_0?0?"
#
#   # Export Widget_Board which is in parts/Electronics/PCB/
#   python3 ./api/inv-parts2json.py "Widget_Board"
# --------------------------------------------------------------

import requests
import json
import os
import re
import argparse

# ----------------------------------------------------------------------
# API endpoints & auth
# ----------------------------------------------------------------------
if os.getenv("INVENTREE_URL"):
    BASE_URL = os.getenv("INVENTREE_URL")
    BASE_URL_PARTS      = BASE_URL + "api/part/"
    BASE_URL_CATEGORIES = BASE_URL + "api/part/category/"
else:
    BASE_URL = None
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
    """Spaces to _, remove dots, strip invalid filename chars."""
    sanitized = name.replace(' ', '_').replace('.', '')
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', sanitized.strip())
    return sanitized


def sanitize_part_name(name):
    """Spaces to _, dots to ,, strip invalid filename chars."""
    sanitized = name.replace(' ', '_').replace('.', ',')
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', sanitized.strip())
    return sanitized


# ----------------------------------------------------------------------
# Generic fetch (handles pagination)
# ----------------------------------------------------------------------
def fetch_data(url):
    """Return flat list of items."""
    items = []
    while url:
        r = requests.get(url, headers=HEADERS)
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
# Save JSON helper
# ----------------------------------------------------------------------
def save_to_file(data, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.write("\n")


# ----------------------------------------------------------------------
# Build category hierarchy (PK to pathstring + parent to subcats)
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

        # Update pathstring with sanitized name
        parts = path.split("/")
        parts[-1] = san_name
        san_path = "/".join(parts)

        pk_to_path[pk] = san_path

        parent_to_subs.setdefault(parent, []).append(cat_mod)

    return pk_to_path, parent_to_subs


# ----------------------------------------------------------------------
# Write category.json files (top-level + sub-folders)
# ----------------------------------------------------------------------
def write_category_files(root_dir, pk_to_path, parent_to_subs):
    # Top-level
    top = parent_to_subs.get("None", [])
    if top:
        save_to_file(top, os.path.join(root_dir, "category.json"))

    # Sub-categories
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
        description="Export InvenTree parts + categories to data/parts/ (with glob support)."
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns for **sanitized** part names (e.g. 'C_*_0402', 'C_*_0?0?'). "
             "Default: export ALL."
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
    # 2. Write category.json files (creates folders)
    # ------------------------------------------------------------------
    print("DEBUG: Writing category.json files...")
    write_category_files(root_dir, pk_to_path, parent_to_subs)

    # ------------------------------------------------------------------
    # 3. Compile glob patterns to regex (after sanitizing)
    # ------------------------------------------------------------------
    patterns = []
    if args.patterns:
        for raw in args.patterns:
            # Remove .json if present
            pat = raw.removesuffix(".json").strip()
            if not pat:
                continue
            # glob to regex
            regex = "^" + re.escape(pat).replace("\\*", ".*").replace("\\?", ".") + "$"
            patterns.append(re.compile(regex, re.IGNORECASE))
        print(f"DEBUG: Filtering with {len(patterns)} patterns")

    # ------------------------------------------------------------------
    # 4. Fetch & export parts
    # ------------------------------------------------------------------
    print("DEBUG: Fetching parts...")
    parts = fetch_data(BASE_URL_PARTS)
    exported = 0

    for part in parts:
        cat_pk = part.get("category")
        name   = part.get("name")
        if not (cat_pk and name):
            continue

        san_name = sanitize_part_name(name)

        # Apply pattern filter (if any)
        if patterns and not any(p.search(san_name) for p in patterns):
            continue

        # Build directory from category path
        pathstring = pk_to_path.get(cat_pk)
        if not pathstring:
            continue
        dir_parts = [sanitize_category_name(p) for p in pathstring.split("/")]
        dir_path = os.path.join(root_dir, *dir_parts)

        # Save part JSON
        part_mod = part.copy()
        part_mod["name"] = san_name
        part_mod["image"] = ""
        part_mod["thumbnail"] = ""
        part_file = os.path.join(dir_path, f"{san_name}.json")
        save_to_file(part_mod, part_file)
        exported += 1

    print(f"SUMMARY: Exported {exported} parts (categories created as needed)")

if __name__ == "__main__":
    main()