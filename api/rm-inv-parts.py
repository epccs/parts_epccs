#!/usr/bin/env python3
# file name: rm-inv-parts.py
# version: 2025-11-07-v1
# --------------------------------------------------------------
# Delete parts (and optionally their dependencies) based on JSON files.
# * Uses GLOBAL search by name + IPN (ignores JSON category)
# * --clean-dependencies -> two confirmations
# * Sets part to inactive before deletion
# --------------------------------------------------------------
# Example usage:
# python3 ./api/rm-inv-parts.py "Paint/Yellow_Paint" --remove-json --clean-dependencies
# python3 ./api/rm-inv-parts.py "Electronics/Passives/Capacitors/C_*_0402" --clean-dependencies
import requests
import json
import os
import glob
import sys
import argparse
from collections import defaultdict
# ----------------------------------------------------------------------
# API endpoints
# ----------------------------------------------------------------------
if os.getenv("INVENTREE_URL"):
    BASE_URL = os.getenv("INVENTREE_URL").rstrip("/")
    BASE_URL_PARTS = f"{BASE_URL}/api/part/"
    BASE_URL_BOM = f"{BASE_URL}/api/bom/"
    BASE_URL_TEST = f"{BASE_URL}/api/part/test-template/"
    BASE_URL_STOCK = f"{BASE_URL}/api/stock/"
    BASE_URL_BUILD = f"{BASE_URL}/api/build/"
    BASE_URL_SALES = f"{BASE_URL}/api/sales/order/"
    BASE_URL_ATTACHMENTS = f"{BASE_URL}/api/part/attachment/"
    BASE_URL_PARAMETERS = f"{BASE_URL}/api/part/parameter/"
    BASE_URL_RELATED = f"{BASE_URL}/api/part/related/"
else:
    BASE_URL = None
    BASE_URL_PARTS = BASE_URL_BOM = BASE_URL_TEST = None
    BASE_URL_STOCK = BASE_URL_BUILD = BASE_URL_SALES = BASE_URL_ATTACHMENTS = None
    BASE_URL_PARAMETERS = BASE_URL_RELATED = None
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
# ----------------------------------------------------------------------
# GLOBAL search by name + IPN (ignores category)
# ----------------------------------------------------------------------
def find_parts_by_name_revision_ipn(name, revision, ipn):
    """Search globally for part by name + revision + IPN."""
    print(f"DEBUG: Global search for part '{name}' rev '{revision}' (IPN={ipn})")
    params = {"name": name}
    if revision:
        params["revision"] = revision
    if ipn:
        params["IPN"] = ipn
    try:
        r = requests.get(BASE_URL_PARTS, headers=HEADERS, params=params)
        print(f"DEBUG: Global search status {r.status_code}")
        if r.status_code != 200:
            raise Exception(f"Global search failed: {r.text}")
        data = r.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        if results:
            print(f"DEBUG: Found {len(results)} parts: {[p.get('pk') for p in results]}")
        return results
    except requests.RequestException as e:
        raise Exception(f"Network error in global search: {e}")
# ----------------------------------------------------------------------
# Dependency handling
# ----------------------------------------------------------------------
def check_dependencies(part_pk):
    deps = {
        "stock": [], "bom": [], "test": [], "build": [], "sales": [],
        "attachments": [], "parameters": [], "related": []
    }
    for endpoint, key in [
        (BASE_URL_STOCK, "stock"),
        (BASE_URL_BOM, "bom"),
        (BASE_URL_TEST, "test"),
        (BASE_URL_BUILD, "build"),
        (BASE_URL_SALES, "sales"),
        (BASE_URL_ATTACHMENTS, "attachments"),
        (BASE_URL_PARAMETERS, "parameters"),
        (BASE_URL_RELATED, "related"),
    ]:
        try:
            r = requests.get(f"{endpoint}?part={part_pk}", headers=HEADERS)
            print(f"DEBUG: Dep {key} -> {r.status_code}")
            if r.status_code == 200:
                js = r.json()
                cnt = js.get("count", len(js)) if isinstance(js, dict) else len(js)
                if cnt:
                    deps[key] = js.get("results", js)
        except requests.RequestException as e:
            print(f"DEBUG: Dep {key} network error: {e}")
    return deps
def delete_dependencies(part_name, part_pk, clean):
    if not clean:
        return False
    deps = check_dependencies(part_pk)
    total = sum(len(v) for v in deps.values())
    if total == 0:
        print(f"DEBUG: No deps for {part_name} (PK {part_pk})")
        return True
    print(f"WARNING: {total} dependencies for '{part_name}' (PK {part_pk})")
    for k, items in deps.items():
        if items:
            print(f" • {len(items)} {k}: {[i.get('pk') for i in items]}")
    if input(f"Type 'YES' to delete {total} deps: ") != "YES":
        print("DEBUG: Cancelled (first)")
        return False
    if input(f"Type 'CONFIRM' to PERMANENTLY delete: ") != "CONFIRM":
        print("DEBUG: Cancelled (second)")
        return False
    for key, items in deps.items():
        for it in items:
            pk = it.get("pk")
            url = {
                "stock": f"{BASE_URL_STOCK}{pk}/",
                "bom": f"{BASE_URL_BOM}{pk}/",
                "test": f"{BASE_URL_TEST}{pk}/",
                "build": f"{BASE_URL_BUILD}{pk}/",
                "sales": f"{BASE_URL_SALES}{pk}/",
                "attachments": f"{BASE_URL_ATTACHMENTS}{pk}/",
                "parameters": f"{BASE_URL_PARAMETERS}{pk}/",
                "related": f"{BASE_URL_RELATED}{pk}/",
            }[key]
            try:
                r = requests.delete(url, headers=HEADERS)
                print(f"DEBUG: Delete {key} {pk} -> {r.status_code}")
                if r.status_code != 204:
                    raise Exception(f"Delete failed: {r.text}")
            except requests.RequestException as e:
                raise Exception(f"Network error deleting {key} {pk}: {e}")
    return True
def delete_part(part_name, part_pk, clean_deps):
    print(f"DEBUG: Deleting part '{part_name}' (PK {part_pk})")
    if not delete_dependencies(part_name, part_pk, clean_deps):
        raise Exception("Dependencies block deletion")
    try:
        r = requests.patch(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS,
                           json={"active": False})
        print(f"DEBUG: Patch active=False -> {r.status_code}")
        if r.status_code not in (200, 201):
            raise Exception(f"Patch failed: {r.text}")
    except requests.RequestException as e:
        raise Exception(f"Network error patching active: {e}")
    try:
        r = requests.delete(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS)
        print(f"DEBUG: DELETE part -> {r.status_code}")
        if r.status_code != 204:
            raise Exception(f"Delete failed: {r.text}")
        print(f"DEBUG: Part {part_name} (PK {part_pk}) removed")
    except requests.RequestException as e:
        raise Exception(f"Network error deleting part: {e}")
# ----------------------------------------------------------------------
# Process a single JSON file
# ----------------------------------------------------------------------
def process_part_file(part_file, remove_json=False, clean_deps=False):
    print(f"DEBUG: Processing {part_file}")
    try:
        with open(part_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"DEBUG: JSON error: {e}")
        return
    if isinstance(data, list):
        data = data[0]
    name = data.get("name")
    revision = data.get("revision", "")
    ipn = data.get("IPN") or data.get("name")[:50] # fallback
    if not name:
        print("DEBUG: Missing name – skip")
        return
    # GLOBAL search by name + revision + IPN
    existing = find_parts_by_name_revision_ipn(name, revision, ipn)
    if not existing:
        print(f"DEBUG: Part '{name}' rev '{revision}' (IPN={ipn}) not found – skip")
        return
    for p in existing:
        delete_part(name, p["pk"], clean_deps)
    if remove_json:
        try:
            os.remove(part_file)
            print(f"DEBUG: Removed {part_file}")
        except Exception as e:
            print(f"DEBUG: Remove file error: {e}")
# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Delete InvenTree parts based on data/parts JSON files (global name+revision+IPN search)."
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns (relative to data/parts)"
    )
    parser.add_argument("--remove-json", action="store_true",
                        help="Delete the JSON file after successful removal")
    parser.add_argument("--clean-dependencies", action="store_true",
                        help="Delete all dependencies (two confirmations)")
    args = parser.parse_args()
    if not TOKEN:
        raise Exception("INVENTREE_TOKEN not set")
    if not BASE_URL:
        raise Exception("INVENTREE_URL not set")
    root = "data/parts"
    if not os.path.isdir(root):
        raise FileNotFoundError(f"{root} missing")
    matched_files = []
    if args.patterns:
        for pat in args.patterns:
            recursive = "**" in pat
            # No revision
            no_rev_pat = os.path.join(root, pat + ".json")
            matched_files.extend(glob.glob(no_rev_pat, recursive=recursive))
            # With revision
            rev_pat = os.path.join(root, pat + ".*.json")
            matched_files.extend(glob.glob(rev_pat, recursive=recursive))
    else:
        matched_files = glob.glob(os.path.join(root, "**/*.json"), recursive=True)
    files = sorted(set(f for f in matched_files if os.path.basename(f) != "category.json"))
    # Build key_to_files for conflict check
    key_to_files = defaultdict(list)
    for f in files:
        basename = os.path.basename(f)[:-5]
        parts = basename.split(".", 1)
        if len(parts) == 0:
            continue
        name = parts[0]
        rev = parts[1] if len(parts) > 1 else ""
        rel_dir = os.path.relpath(os.path.dirname(f), root)
        key = os.path.join(rel_dir, name).replace("\\", "/")
        key_to_files[key].append((f, rev))
    # Check for conflicts
    for key, flist in key_to_files.items():
        revs = [r for _, r in flist]
        if len(revs) > 1 and "" in revs:
            files_str = ", ".join([os.path.basename(f) for f, _ in flist])
            raise Exception(f"Error for {key}: both no-revision and revisioned files exist: {files_str}")
    print(f"DEBUG: {len(files)} files to process")
    for key, flist in key_to_files.items():
        for f, rev in flist:
            process_part_file(f, args.remove_json, args.clean_dependencies)
if __name__ == "__main__":
    main()