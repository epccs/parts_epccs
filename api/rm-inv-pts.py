#!/usr/bin/env python3
# file name: rm-inv-pts.py
# version: 2025-11-20-v2
# --------------------------------------------------------------
# Delete InvenTree parts based on JSON files in data/pts/<level>/...
#
# * Matches parts by sanitized name + revision (exact filename match)
# * Global search using name + revision + optional IPN fallback
# * --clean-dependencies -> two-step confirmation + deletes stock, BOMs, supplier parts, price breaks, etc.
# * --remove-json -> deletes the JSON + .bom.json after successful removal
# * --api-print -> verbose API logging (GET preview, POST/PATCH/DELETE URLs)
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
import re
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
# Same sanitizers as pull/push scripts
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
# Verbose API helpers
# ----------------------------------------------------------------------
def api_get(url, params=None, api_print=False):
    if api_print:
        param_str = f"?{requests.compat.urlencode(params)}" if params else ""
        print(f"API GET: {url}{param_str}")
    r = requests.get(url, headers=HEADERS, params=params)
    if api_print and r.status_code == 200:
        preview = json.dumps(r.json())[:200].replace("\n", " ")
        print(f"       -> {r.status_code} {preview}...")
    elif api_print:
        print(f"       -> {r.status_code}")
    return r

def api_patch(url, payload, api_print=False):
    if api_print:
        print(f"API PATCH: {url}")
        print(f"Payload: {json.dumps(payload, indent=4)}")
    r = requests.patch(url, headers=HEADERS, json=payload)
    if api_print:
        print(f"       -> {r.status_code}")
    return r

def api_delete(url, api_print=False):
    if api_print:
        print(f"API DELETE: {url}")
    r = requests.delete(url, headers=HEADERS)
    if api_print:
        print(f"       -> {r.status_code}")
    return r

# ----------------------------------------------------------------------
# Global search by name + revision
# ----------------------------------------------------------------------
def find_part_exact(name_san, revision_san, ipn="", api_print=False):
    params = {"name": name_san, "search": name_san}
    if revision_san:
        params["revision"] = revision_san
    if ipn:
        params["IPN"] = ipn

    r = api_get(BASE_URL_PARTS, params=params, api_print=api_print)
    if r.status_code != 200:
        return []

    data = r.json()
    results = data.get("results", data) if isinstance(data, dict) else data
    filtered = [
        p for p in results
        if p.get("name") == name_san and
           (p.get("revision") or "") == (revision_san or "")
    ]
    return filtered

# ----------------------------------------------------------------------
# Dependency handling
# ----------------------------------------------------------------------
def check_dependencies(part_pk, api_print=False):
    endpoints = [
        (BASE_URL_STOCK + f"?part={part_pk}", "stock"),
        (BASE_URL_BOM + f"?sub_part={part_pk}", "used_in_bom"),
        (BASE_URL_SUPPLIER_PARTS + f"?part={part_pk}", "supplier_parts"),
        (BASE_URL_PRICE_BREAK + f"?part__part={part_pk}", "price_breaks"),
    ]
    deps = {}
    total = 0
    for url, name in endpoints:
        r = api_get(url, api_print=api_print)
        if r.status_code == 200:
            js = r.json()
            items = js.get("results", js) if isinstance(js, dict) else js
            deps[name] = items
            total += len(items)
    return deps, total

def delete_all_dependencies(part_pk, api_print=False):
    to_delete = [
        (BASE_URL_PRICE_BREAK, "?part__part="),
        (BASE_URL_SUPPLIER_PARTS, "?part="),
        (BASE_URL_STOCK, "?part="),
        (BASE_URL_BOM, "?sub_part="),
    ]
    for base_url, query in to_delete:
        url = f"{base_url}{query}{part_pk}"
        r = api_get(url, api_print=api_print)
        if r.status_code != 200:
            continue
        data = r.json()
        items = data.get("results", data) if isinstance(data, dict) else data
        for item in items:
            pk = item["pk"]
            del_url = f"{base_url}{pk}/"
            api_delete(del_url, api_print=api_print)

# ----------------------------------------------------------------------
# Main deletion routine
# ----------------------------------------------------------------------
def delete_part_from_file(json_path, clean_deps=False, remove_json=False, api_print=False):
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

    candidates = find_part_exact(name_san, revision_san, ipn if ipn else None, api_print=api_print)
    if not candidates:
        print("  Not found in InvenTree – nothing to delete")
        return

    for part in candidates:
        pk = part["pk"]
        print(f"  Found match → PK {pk}")

        if clean_deps:
            deps, total = check_dependencies(pk, api_print=api_print)
            if total > 0:
                print(f"  {total} dependencies detected")
                if input("  Type YES to delete dependencies: ") != "YES":
                    print("  Skipped")
                    continue
                if input("  Type CONFIRM to permanently delete: ") != "CONFIRM":
                    print("  Aborted")
                    continue
                delete_all_dependencies(pk, api_print=api_print)
            else:
                print("  No dependencies")

        # Deactivate first
        api_patch(f"{BASE_URL_PARTS}{pk}/", {"active": False}, api_print=api_print)

        # Final delete
        r = api_delete(f"{BASE_URL_PARTS}{pk}/", api_print=api_print)
        if r.status_code == 204:
            print(f"  SUCCESS: Deleted part PK {pk}")
        else:
            print(f"  Delete failed {r.status_code}: {r.text}")
            return  # don't remove files on failure

    # Remove files only on success
    if remove_json:
        for path in [json_path, json_path[:-5] + ".bom.json"]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"  Removed {path}")
                except Exception as e:
                    print(f"  File remove error: {e}")

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
        help="Glob patterns relative to data/pts (e.g. '1/Electronics/Connectors/*')"
    )
    parser.add_argument(
        "--clean-dependencies", action="store_true",
        help="Delete stock, BOM usage, supplier parts, price breaks, etc. (double confirmation)"
    )
    parser.add_argument(
        "--remove-json", action="store_true",
        help="Delete the .json and .bom.json files after successful deletion"
    )
    parser.add_argument(
        "--api-print", action="store_true",
        help="Print every API call and short preview of GET responses"
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
        delete_part_from_file(
            f,
            clean_deps=args.clean_dependencies,
            remove_json=args.remove_json,
            api_print=args.api_print
        )

    print("\nDone.")

if __name__ == "__main__":
    main()
