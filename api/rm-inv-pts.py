#!/usr/bin/env python3
# file name: rm-inv-pts.py
# version: 2025-11-20-v1
# --------------------------------------------------------------
# Delete InvenTree parts based on JSON files in data/pts/<level>/...
#
# * Matches parts by sanitized name + revision (exact filename match)
# * Global search using name + revision + optional IPN fallback
# * --clean-dependencies -> two-step confirmation + deletes stock, BOMs, supplier parts, price breaks, etc.
# * --remove-json -> deletes the JSON + .bom.json after successful removal
# * Respects variant dependencies (no special handling needed – just deletes the variant)
# * Works with the exact same folder/layout as inv-pts_to_json.py and json_to_inv-pts.py
#
# Example usage:
#   python3 ./api/rm-inv-pts.py "4/Mechanical/Widgets/Widget_Assembly_Variant*" --clean-dependencies --remove-json
#   python3 ./api/rm-inv-pts.py "2/Electronics/PCBA/Widget_Board*" --remove-json
# --------------------------------------------------------------
import requests
import json
import os
import glob
import sys
import argparse
from collections import defaultdict

# ----------------------------------------------------------------------
# API & Auth
# ----------------------------------------------------------------------
BASE_URL = os.getenv("INVENTREE_URL")
if BASE_URL:
    BASE_URL = BASE_URL.rstrip("/")
    BASE_URL_PARTS = f"{BASE_URL}/api/part/"
    BASE_URL_BOM = f"{BASE_URL}/api/bom/"
    BASE_URL_STOCK = f"{BASE_URL}/api/stock/"
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
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ----------------------------------------------------------------------
# Same sanitizers as the pull/push scripts
# ----------------------------------------------------------------------
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
# Global search by name + revision (and IPN fallback)
# ----------------------------------------------------------------------
def find_part_exact(name_san, revision_san, ipn=""):
    params = {
        "name": name_san,
        "revision": revision_san or None,
        "search": name_san  # fallback broad search
    }
    if ipn:
        params["IPN"] = ipn

    r = requests.get(BASE_URL_PARTS, headers=HEADERS, params=params)
    if r.status_code != 200:
        print(f"DEBUG: Search failed {r.status_code}: {r.text}")
        return []

    data = r.json()
    results = data.get("results", data) if isinstance(data, dict) else data
    # Extra filter to be 100% sure (API sometimes ignores revision)
    filtered = [
        p for p in results
        if p.get("name") == name_san and
           (p.get("revision") or "") == (revision_san or "")
    ]
    return filtered

# ----------------------------------------------------------------------
# Dependency checking & cleaning
# ----------------------------------------------------------------------
def check_dependencies(part_pk):
    endpoints = [
        (BASE_URL_STOCK + f"?part={part_pk}", "stock"),
        (BASE_URL_BOM + f"?sub_part={part_pk}", "used_in_bom"),
        (BASE_URL_SUPPLIER_PARTS + f"?part={part_pk}", "supplier_parts"),
        (BASE_URL_PRICE_BREAK + f"?part__part={part_pk}", "price_breaks"),  # nested
    ]
    deps = {}
    total = 0
    for url, name in endpoints:
        r = requests.get(url, headers=HEADERS)
        if r.status_code == 200:
            js = r.json()
            items = js.get("results", js) if isinstance(js, dict) else js
            deps[name] = items
            total += len(items)
    return deps, total

def delete_all_dependencies(part_pk):
    # Order matters – delete leaf dependencies first
    to_delete = [
        (BASE_URL_PRICE_BREAK, "price_break"),
        (BASE_URL_SUPPLIER_PARTS, "supplier_part"),
        (BASE_URL_STOCK, "stock"),
        (BASE_URL_BOM, "bom_used"),
    ]
    for base, kind in to_delete:
        url = f"{base}?part={part_pk}" if "price_break" not in base else f"{base}?part__part={part_pk}"
        r = requests.get(url, headers=HEADERS)
        if r.status_code != 200:
            continue
        data = r.json()
        items = data.get("results", data) if isinstance(data, dict) else data
        for item in items:
            pk = item["pk"]
            del_url = f"{base}{pk}/" if "price_break" not in base else f"{BASE_URL_PRICE_BREAK}{pk}/"
            dr = requests.delete(del_url, headers=HEADERS)
            print(f"  Deleted {kind} {pk} -> {dr.status_code}")

# ----------------------------------------------------------------------
# Main deletion routine
# ----------------------------------------------------------------------
def delete_part_from_file(json_path, clean_deps=False, remove_json=False):
    print(f"\nProcessing: {json_path}")

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            data = data[0]
    except Exception as e:
        print(f"  JSON load error: {e}")
        return

    name_raw = data.get("name")
    revision_raw = data.get("revision", "")
    ipn = data.get("IPN", "")

    if not name_raw:
        print("  Missing name in JSON – skipping")
        return

    name_san = sanitize_part_name(name_raw)
    revision_san = sanitize_revision(revision_raw)

    print(f"  Looking for part: '{name_raw}' | Rev: '{revision_raw or '(none)'}' | IPN: {ipn or '(none)'}")

    candidates = find_part_exact(name_san, revision_san, ipn if ipn else None)
    if not candidates:
        print("  Not found in InvenTree – nothing to delete")
        return

    for part in candidates:
        pk = part["pk"]
        print(f"  Found match -> PK {pk}")

        if clean_deps:
            deps, total = check_dependencies(pk)
            if total > 0:
                print(f"  {total} dependencies detected")
                if input("  Type YES to delete dependencies: ") != "YES":
                    print("  Skipped")
                    continue
                if input("  Type CONFIRM to permanently delete: ") != "CONFIRM":
                    print("  Aborted")
                    continue
                delete_all_dependencies(pk)
            else:
                print("  No dependencies")

        # Deactivate first (some instances require this)
        requests.patch(f"{BASE_URL_PARTS}{pk}/", headers=HEADERS, json={"active": False})

        # Final delete
        r = requests.delete(f"{BASE_URL_PARTS}{pk}/", headers=HEADERS)
        if r.status_code == 204:
            print(f"  SUCCESS: Deleted part PK {pk}")
        else:
            print(f"  Delete failed {r.status_code}: {r.text}")
            return  # don't remove files on failure

    # Only remove files if deletion succeeded
    if remove_json:
        try:
            os.remove(json_path)
            print(f"  Removed {json_path}")
        except Exception as e:
            print(f"  File remove error: {e}")

        bom_path = json_path[:-5] + ".bom.json"
        if os.path.exists(bom_path):
            try:
                os.remove(bom_path)
                print(f"  Removed {bom_path}")
            except Exception as e:
                print(f"  BOM file remove error: {e}")

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Delete InvenTree parts based on data/pts/<level>/ JSON files"
    )
    parser.add_argument(
        "patterns", nargs="*",
        default=["**/*"],
        help="Glob patterns relative to data/pts (e.g. '3/Mechanical/Widgets/*Variant*')"
    )
    parser.add_argument(
        "--clean-dependencies", action="store_true",
        help="Delete stock, BOM usage, supplier parts, price breaks, etc. (double confirmation)"
    )
    parser.add_argument(
        "--remove-json", action="store_true",
        help="Delete the .json and .bom.json files after successful deletion"
    )
    args = parser.parse_args()

    root = "data/pts"
    if not os.path.isdir(root):
        print(f"Error: {root} directory not found")
        sys.exit(1)

    files = []
    for pat in args.patterns:
        full_pat = os.path.join(root, pat)
        files.extend(glob.glob(full_pat, recursive=True))
        files.extend(glob.glob(full_pat + ".*.json", recursive=True))

    json_files = sorted({
        f for f in files
        if f.endswith(".json") and not f.endswith(".bom.json") and "category.json" not in f
    })

    if not json_files:
        print("No matching part JSON files found")
        return

    print(f"Found {len(json_files)} part file(s) to process\n")
    for f in json_files:
        delete_part_from_file(f, args.clean_dependencies, args.remove_json)

    print("\nDone.")

if __name__ == "__main__":
    import re  # used in sanitizers
    main()