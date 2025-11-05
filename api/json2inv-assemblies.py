#!/usr/bin/env python3
# file name: json2inv-assemblies.py
# version: 2025-11-05-v1
# --------------------------------------------------------------
# Import assemblies + BOMs from data/assemblies/ → InvenTree
#
# * Supports: Part_Name[.revision].json + Part_Name[.revision].bom.json
# * CLI options: --force-ipn, --force, --clean-dependencies
# * Skips duplicates by (name + revision)
# * Compatible with inv-assemblies2json.py
#
# example usage:
#   python3 ./api/json2inv-assemblies.py
#   python3 ./api/json2inv-assemblies.py "Widget_*"
#   python3 ./api/json2inv-assemblies.py --force --clean-dependencies
# --------------------------------------------------------------
# see https://grok.com/share/c2hhcmQtMw%3D%3D_c721971e-5566-4a30-8129-040e6e84599f

import requests
import json
import os
import glob
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
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# ----------------------------------------------------------------------
# Sanitizers (for matching)
# ----------------------------------------------------------------------
def sanitize_part_name(name):
    return name.replace(' ', '_').replace('.', ',')

# ----------------------------------------------------------------------
# Fetch helpers
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
# Check if part exists by name + revision
# ----------------------------------------------------------------------
def find_part_by_name_revision(name, revision):
    """Return list of matching parts (name + revision)."""
    print(f"DEBUG: Searching for part '{name}' revision '{revision}'")
    params = {"name": name}
    if revision:
        params["revision"] = revision
    try:
        r = requests.get(BASE_URL_PARTS, headers=HEADERS, params=params)
        if r.status_code != 200:
            return []
        data = r.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        print(f"DEBUG: Found {len(results)} matches")
        return results
    except:
        return []

# ----------------------------------------------------------------------
# Delete BOM items (clean-dependencies)
# ----------------------------------------------------------------------
def delete_bom_items(part_pk, clean_deps):
    if not clean_deps:
        return
    print(f"DEBUG: Fetching BOM for part PK {part_pk}")
    bom_items = fetch_data(f"{BASE_URL_BOM}?part={part_pk}")
    if not bom_items:
        print("DEBUG: No BOM items to delete")
        return

    print(f"WARNING: Found {len(bom_items)} BOM items to delete")
    confirm1 = input("Type 'YES' to delete BOM: ")
    if confirm1 != "YES":
        print("DEBUG: Cancelled (first)")
        return
    confirm2 = input("Type 'CONFIRM' to PERMANENTLY delete: ")
    if confirm2 != "CONFIRM":
        print("DEBUG: Cancelled (second)")
        return

    for item in bom_items:
        pk = item.get("pk")
        if not pk:
            continue
        try:
            r = requests.delete(f"{BASE_URL_BOM}{pk}/", headers=HEADERS)
            print(f"DEBUG: DELETE BOM {pk} → {r.status_code}")
            if r.status_code != 204:
                print(f"DEBUG: Failed: {r.text}")
        except:
            pass

# ----------------------------------------------------------------------
# Delete part (force)
# ----------------------------------------------------------------------
def delete_part(part_pk, clean_deps):
    print(f"DEBUG: Deleting part PK {part_pk}")
    delete_bom_items(part_pk, clean_deps)
    # Set inactive first
    try:
        r = requests.patch(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS, json={"active": False})
        print(f"DEBUG: Patch active=False → {r.status_code}")
    except:
        pass
    try:
        r = requests.delete(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS)
        print(f"DEBUG: DELETE part → {r.status_code}")
    except:
        pass

# ----------------------------------------------------------------------
# Import one assembly
# ----------------------------------------------------------------------
def import_assembly(part_file, bom_file, force_ipn, force, clean_deps):
    print(f"DEBUG: Importing assembly: {part_file}")

    # Load part JSON
    try:
        with open(part_file, "r", encoding="utf-8") as f:
            part_data = json.load(f)
    except Exception as e:
        raise Exception(f"Failed to read {part_file}: {e}")

    # Extract name and revision
    name = part_data.get("name")
    revision = part_data.get("revision", "")
    if not name:
        print("DEBUG: Skipping – no name")
        return

    # Force IPN
    ipn = part_data.get("IPN")
    if force_ipn and (not ipn or ipn.strip() == ""):
        ipn = name[:50]
        part_data["IPN"] = ipn
        print(f"DEBUG: Generated IPN → {ipn}")

    # Check for existing
    existing = find_part_by_name_revision(name, revision)
    if existing:
        if force:
            for p in existing:
                delete_part(p["pk"], clean_deps)
        else:
            print(f"DEBUG: Assembly '{name}' rev '{revision}' exists – skipping")
            return

    # Prepare payload
    payload = {
        "name": name,
        "description": part_data.get("description", ""),
        "IPN": ipn or "",
        "revision": revision,
        "assembly": True,
        "category": part_data.get("category"),
        "is_template": False
    }

    # Create part
    try:
        r = requests.post(BASE_URL_PARTS, headers=HEADERS, json=payload)
        if r.status_code != 201:
            raise Exception(f"Create failed: {r.text}")
        new_part = r.json()
        part_pk = new_part["pk"]
        print(f"DEBUG: Created assembly '{name}' rev '{revision}' (PK {part_pk})")
    except Exception as e:
        raise Exception(f"Failed to create assembly: {e}")

    # Import BOM
    if not bom_file or not os.path.exists(bom_file):
        print("DEBUG: No .bom.json file – skipping BOM")
        return

    try:
        with open(bom_file, "r", encoding="utf-8") as f:
            bom_data = json.load(f)
    except Exception as e:
        print(f"DEBUG: Failed to read BOM: {e}")
        return

    print(f"DEBUG: Importing {len(bom_data)} BOM items")
    for item in bom_data:
        sub_part = item.get("sub_part", {})
        if not sub_part.get("pk"):
            continue
        bom_payload = {
            "part": part_pk,
            "sub_part": sub_part["pk"],
            "quantity": item.get("quantity", 1),
            "note": item.get("note", "")
        }
        try:
            r = requests.post(BASE_URL_BOM, headers=HEADERS, json=bom_payload)
            if r.status_code not in (201, 200):
                print(f"DEBUG: BOM item failed: {r.text}")
        except:
            pass

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Import assemblies + BOMs from data/assemblies/"
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns (e.g. 'Widget_*'). Default: all."
    )
    parser.add_argument("--force-ipn", action="store_true",
                        help="Generate IPN from name if missing")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing assembly (name+revision) before import")
    parser.add_argument("--clean-dependencies", action="store_true",
                        help="Delete existing BOM items (requires YES+CONFIRM)")
    args = parser.parse_args()

    if not TOKEN or not BASE_URL:
        raise Exception("INVENTREE_TOKEN and INVENTREE_URL must be set")

    root_dir = "data/assemblies"
    if not os.path.isdir(root_dir):
        raise FileNotFoundError(f"{root_dir} not found")

    # ------------------------------------------------------------------
    # Resolve .json files
    # ------------------------------------------------------------------
    files = []
    for pat in args.patterns or ["*"]:
        full = os.path.join(root_dir, pat)
        matches = glob.glob(full, recursive=True)
        files.extend([m for m in matches if m.endswith(".json") and not m.endswith(".bom.json")])

    if not files:
        for pat in args.patterns:
            fp = os.path.join(root_dir, pat)
            if os.path.isfile(fp) and fp.endswith(".json") and not fp.endswith(".bom.json"):
                files.append(fp)

    files = sorted(set(files))
    print(f"DEBUG: {len(files)} assembly files to import")

    # ------------------------------------------------------------------
    # Import loop
    # ------------------------------------------------------------------
    imported = 0
    for part_file in files:
        bom_file = part_file.replace(".json", ".bom.json")
        try:
            import_assembly(part_file, bom_file, args.force_ipn, args.force, args.clean_dependencies)
            imported += 1
        except Exception as e:
            print(f"ERROR: {e}")

    print(f"SUMMARY: Imported {imported} assemblies")

if __name__ == "__main__":
    main()