#!/usr/bin/env python3
# file name: rm-inv-categories.py
# version: 2025-10-27-v1
# --------------------------------------------------------------
# Delete EMPTY part categories based on folder structure in data/parts.
# * Only deletes if category has ZERO parts.
# * Supports --remove-json to delete category.json files.
# * Safe: skips non-empty categories.
# --------------------------------------------------------------
# example usage:
#      # Delete empty Paint category (after removing Yellow_Paint, see rm-inv-parts.py examples)
#      python3 ./api/rm-inv-categories.py "Paint"
#
#      # Delete Capacitors category (after removing all C_*.json)
#      python3 ./api/rm-inv-parts.py "Electronics/Passives/Capacitors/C_*.json" --clean-dependencies --remove-json
#      python3 ./api/rm-inv-categories.py "Electronics/Passives/Capacitors" --remove-json
#      # note: the last example does not alter category.json or remove it, at this time handling is manual.

import requests
import json
import os
import glob
import sys
import argparse

# ----------------------------------------------------------------------
# API endpoints
# ----------------------------------------------------------------------
if os.getenv("INVENTREE_URL"):
    BASE_URL = os.getenv("INVENTREE_URL")
    BASE_URL_CATEGORIES = BASE_URL + "api/part/category/"
    BASE_URL_PARTS = BASE_URL + "api/part/"
else:
    BASE_URL = None
    BASE_URL_CATEGORIES = BASE_URL_PARTS = None

TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ----------------------------------------------------------------------
# Get category by path (folder structure)
# ----------------------------------------------------------------------
def get_category_pk_from_path(folder_path):
    """Return PK of the leaf category from folder path, or None if not found."""
    print(f"DEBUG: Resolving category from path: {folder_path}")
    parts = os.path.relpath(folder_path, "data/parts").split(os.sep)
    cur_pk = None
    for name in parts:
        if name == ".":
            continue
        params = {"name": name}
        if cur_pk:
            params["parent"] = cur_pk
        try:
            r = requests.get(BASE_URL_CATEGORIES, headers=HEADERS, params=params)
            print(f"DEBUG: Category lookup {name} (parent={cur_pk}) → {r.status_code}")
            if r.status_code != 200:
                print(f"DEBUG: Failed to lookup {name}: {r.text}")
                return None
            data = r.json()
            results = data.get("results", data) if isinstance(data, dict) else data
            if not results:
                print(f"DEBUG: Category '{name}' not found")
                return None
            cur_pk = results[0]["pk"]
            print(f"DEBUG: → {name} (PK {cur_pk})")
        except requests.RequestException as e:
            print(f"DEBUG: Network error: {e}")
            return None
    return cur_pk

# ----------------------------------------------------------------------
# Check if category has parts
# ----------------------------------------------------------------------
def category_has_parts(cat_pk):
    """Return True if category has any parts."""
    try:
        r = requests.get(BASE_URL_PARTS, headers=HEADERS, params={"category": cat_pk})
        print(f"DEBUG: Parts in cat {cat_pk} → {r.status_code}")
        if r.status_code != 200:
            return True  # assume has parts on error
        data = r.json()
        count = data.get("count", len(data.get("results", data))) if isinstance(data, dict) else len(data)
        has_parts = count > 0
        print(f"DEBUG: Category {cat_pk} has {count} parts → {'YES' if has_parts else 'NO'}")
        return has_parts
    except requests.RequestException as e:
        print(f"DEBUG: Network error checking parts: {e}")
        return True  # safe default

# ----------------------------------------------------------------------
# Delete category
# ----------------------------------------------------------------------
def delete_category(cat_pk, cat_path):
    """Delete category if empty."""
    if category_has_parts(cat_pk):
        print(f"WARNING: Category '{cat_path}' (PK {cat_pk}) has parts — SKIPPED")
        return False

    try:
        r = requests.delete(f"{BASE_URL_CATEGORIES}{cat_pk}/", headers=HEADERS)
        print(f"DEBUG: DELETE category {cat_pk} → {r.status_code}")
        if r.status_code == 204:
            print(f"DEBUG: Category '{cat_path}' (PK {cat_pk}) deleted")
            return True
        else:
            print(f"DEBUG: Delete failed: {r.text}")
            return False
    except requests.RequestException as e:
        print(f"DEBUG: Network error deleting category: {e}")
        return False

# ----------------------------------------------------------------------
# Process a folder (category path)
# ----------------------------------------------------------------------
def process_category_folder(folder_path, remove_json=False):
    print(f"DEBUG: Processing category folder: {folder_path}")
    cat_pk = get_category_pk_from_path(folder_path)
    if not cat_pk:
        print(f"DEBUG: Category path not found in InvenTree — skipping")
        return

    cat_path = os.path.relpath(folder_path, "data/parts")
    if delete_category(cat_pk, cat_path):
        # Optionally remove category.json
        json_file = os.path.join(folder_path, "category.json")
        if remove_json and os.path.isfile(json_file):
            try:
                os.remove(json_file)
                print(f"DEBUG: Removed {json_file}")
            except Exception as e:
                print(f"DEBUG: Failed to remove {json_file}: {e}")

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Delete EMPTY InvenTree part categories based on data/parts folder structure."
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns for category folders (e.g. 'Electronics/Passives/Capacitors', 'Paint')"
    )
    parser.add_argument("--remove-json", action="store_true",
                        help="Delete category.json files after successful deletion")
    args = parser.parse_args()

    if not TOKEN:
        raise Exception("INVENTREE_TOKEN not set")
    if not BASE_URL:
        raise Exception("INVENTREE_URL not set")

    root = "data/parts"
    if not os.path.isdir(root):
        raise FileNotFoundError(f"{root} missing")

    # ---- collect folders ----
    folders = []
    for pat in args.patterns or ["*"]:
        full = os.path.join(root, pat)
        matches = glob.glob(full, recursive=True)
        folders.extend([m for m in matches if os.path.isdir(m)])

    folders = sorted(set(folders))
    print(f"DEBUG: {len(folders)} category folders to check")

    deleted = 0
    for f in folders:
        if process_category_folder(f, args.remove_json):
            deleted += 1

    print(f"SUMMARY: {deleted} empty categories deleted")

if __name__ == "__main__":
    main()