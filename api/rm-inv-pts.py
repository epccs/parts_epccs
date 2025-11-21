#!/usr/bin/env python3
# file name: rm-inv-pts.py
# version: 2025-11-20-v5
# --------------------------------------------------------------
# Delete InvenTree parts based on JSON files in data/pts/<level>/...
#
# * Matches parts by sanitized name + revision (exact filename match)
# * Global search using name + revision + optional IPN fallback
# * --clean-dependencies -> two-step confirmation + deletes stock, BOMs, supplier parts, price breaks, etc.
# * --clean-dependencies-yes -> deletes ALL dependencies with NO confirmation
# * --remove-json -> deletes the JSON + .bom.json after successful removal
# * --api-print -> verbose API logging (GET preview, POST/PATCH/DELETE URLs)
# * Respects variant dependencies (no special handling needed - just deletes the variant)
# * Works with the exact same folder/layout as inv-pts_to_json.py and json_to_inv-pts.py
#
# Example usage:
#   python3 ./api/rm-inv-pts.py "4/Mechanical/Widgets/Widget_Assembly_Variant*" --clean-dependencies --remove-json
#   python3 ./api/rm-inv-pts.py "2/Electronics/PCBA/Widget_Board*" --remove-json
#   python3 ./api/rm-inv-pts.py "2/Furniture/Tables/*_Table.json" --clean-dependencies
#   python3 ./api/rm-inv-pts.py "1/Mechanical/Fasteners/Wood_Screw.json"
#   python3 ./api/rm-inv-pts.py "1/Furniture/Leg.json"
#   python3 ./api/rm-inv-pts.py "1/Furniture/*_Top.json"
# --------------------------------------------------------------
# Changelog:
# New: --clean-dependencies-yes -> deletes ALL dependencies with NO confirmation
# Safe price-break deletion via SupplierPart
# Robust list/dict JSON handling
# --------------------------------------------------------------
# Todo: remove the .json match from CLI globbing

import requests
import json
import os
import glob
import sys
import argparse
import re

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
# Safe JSON extractor
# ----------------------------------------------------------------------
def extract_results(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("results", data if "pk" in data else [])
    return []

# ----------------------------------------------------------------------
# Sanitizers
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
        param_str = f"?{requests.compat.urlencode(params or {})}" if params else ""
        print(f"API GET: {url}{param_str}")
    r = requests.get(url, headers=HEADERS, params=params)
    if api_print:
        if r.status_code == 200 and r.content:
            preview = json.dumps(r.json() if r.content else "", default=str)[:200].replace("\n", " ")
            print(f"       -> {r.status_code} {preview}...")
        else:
            print(f"       -> {r.status_code} {r.text[:200]}")
    return r

def api_delete(url, api_print=False):
    if api_print:
        print(f"API DELETE: {url}")
    r = requests.delete(url, headers=HEADERS)
    if api_print:
        print(f"       -> {r.status_code}")
    return r

def api_patch(url, payload, api_print=False):
    if api_print:
        print(f"API PATCH: {url}  payload: {payload}")
    r = requests.patch(url, headers=HEADERS, json=payload)
    if api_print:
        print(f"       -> {r.status_code}")
    return r

# ----------------------------------------------------------------------
# Search part
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

    results = extract_results(r.json())
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
    total = 0
    # Supplier parts + price breaks
    sp_r = api_get(f"{BASE_URL_SUPPLIER_PARTS}?part={part_pk}", api_print=False)
    if sp_r.status_code == 200:
        for sp in extract_results(sp_r.json()):
            total += 1
            pb_r = api_get(f"{BASE_URL_PRICE_BREAK}", params={"supplier_part": sp["pk"]}, api_print=False)
            if pb_r.status_code == 200:
                total += len(extract_results(pb_r.json()))
    # Stock + BOM usage
    for endpoint in [f"{BASE_URL_STOCK}?part={part_pk}", f"{BASE_URL_BOM}?sub_part={part_pk}"]:
        r = api_get(endpoint, api_print=False)
        if r.status_code == 200:
            total += len(extract_results(r.json()))
    return total

def delete_all_dependencies(part_pk, api_print=False):
    # SupplierParts + PriceBreaks
    sp_r = api_get(f"{BASE_URL_SUPPLIER_PARTS}?part={part_pk}", api_print=api_print)
    if sp_r.status_code == 200:
        for sp in extract_results(sp_r.json()):
            sp_pk = sp["pk"]
            if api_print:
                print(f"  Deleting SupplierPart {sp_pk} + price breaks")
            pb_r = api_get(f"{BASE_URL_PRICE_BREAK}", params={"supplier_part": sp_pk}, api_print=api_print)
            if pb_r.status_code == 200:
                for pb in extract_results(pb_r.json()):
                    api_delete(f"{BASE_URL_PRICE_BREAK}{pb['pk']}/", api_print=api_print)
            api_delete(f"{BASE_URL_SUPPLIER_PARTS}{sp_pk}/", api_print=api_print)

    # Stock
    stock_r = api_get(f"{BASE_URL_STOCK}?part={part_pk}", api_print=api_print)
    if stock_r.status_code == 200:
        for item in extract_results(stock_r.json()):
            api_delete(f"{BASE_URL_STOCK}{item['pk']}/", api_print=api_print)

    # BOM usages
    bom_r = api_get(f"{BASE_URL_BOM}?sub_part={part_pk}", api_print=api_print)
    if bom_r.status_code == 200:
        for bom in extract_results(bom_r.json()):
            api_delete(f"{BASE_URL_BOM}{bom['pk']}/", api_print=api_print)

# ----------------------------------------------------------------------
# Main deletion
# ----------------------------------------------------------------------
def delete_part_from_file(json_path, clean_deps=False, clean_deps_yes=False, remove_json=False, api_print=False):
    print(f"\nProcessing: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, list):
            data = data[0]

    name_raw = data.get("name")
    revision_raw = data.get("revision", "")
    ipn = data.get("IPN", "")

    if not name_raw:
        print("  Missing name - skipping")
        return

    name_san = sanitize_part_name(name_raw)
    revision_san = sanitize_revision(revision_raw)

    print(f"  Looking for: '{name_raw}' | Rev: '{revision_raw or '(none)'}' | IPN: {ipn or '(none)'}")

    candidates = find_part_exact(name_san, revision_san, ipn if ipn else None, api_print=api_print)
    if not candidates:
        print("  Not found in InvenTree - nothing to delete")
        return

    for part in candidates:
        pk = part["pk"]
        print(f"  Found match -> PK {pk}")

        do_clean = clean_deps or clean_deps_yes
        if do_clean:
            total = check_dependencies(pk)
            if total > 0:
                if clean_deps_yes:
                    print(f"  --clean-dependencies-yes: Auto-deleting {total} dependencies (no confirm)")
                else:
                    print(f"  {total} dependencies detected")
                    if input("  Type YES to delete dependencies: ") != "YES":
                        print("  Skipped")
                        continue
                    if input("  Type CONFIRM to permanently delete: ") != "CONFIRM":
                        print("  Aborted")
                        continue
            else:
                print("  No dependencies")

            delete_all_dependencies(pk, api_print=api_print)
        elif total := check_dependencies(pk):
            print(f"  Warning: {total} dependencies exist but --clean-dependencies not used - skipping part")
            continue

        api_patch(f"{BASE_URL_PARTS}{pk}/", {"active": False}, api_print=api_print)
        r = api_delete(f"{BASE_URL_PARTS}{pk}/", api_print=api_print)
        if r.status_code == 204:
            print(f"  SUCCESS: Deleted part PK {pk}")
        else:
            print(f"  FAILED: {r.status_code} {r.text}")
            return

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
        description="Safely delete InvenTree parts from data/pts/ JSON files"
    )
    parser.add_argument("patterns", nargs="*", default=["**/*"],
                        help="Glob patterns relative to data/pts")
    parser.add_argument("--clean-dependencies", action="store_true",
                        help="Delete dependencies with double confirmation")
    parser.add_argument("--clean-dependencies-yes", action="store_true",
                        help="Delete dependencies with NO confirmation (dangerous!)")
    parser.add_argument("--remove-json", action="store_true",
                        help="Delete JSON + .bom.json files after success")
    parser.add_argument("--api-print", action="store_true",
                        help="Verbose API logging")
    args = parser.parse_args()

    if args.clean_dependencies and args.clean_dependencies_yes:
        print("Error: --clean-dependencies and --clean-dependencies-yes are mutually exclusive")
        sys.exit(1)

    root = "data/pts"
    if not os.path.isdir(root):
        print(f"Error: {root} not found")
        sys.exit(1)

    files = []
    for pat in args.patterns:
        full = os.path.join(root, pat)
        files.extend(glob.glob(full, recursive=True))
        files.extend(glob.glob(full + ".*.json", recursive=True))

    json_files = sorted({
        f for f in files
        if f.endswith(".json") and not f.endswith(".bom.json") and "category.json" not in f
    })

    if not json_files:
        print("No matching files")
        return

    print(f"Found {len(json_files)} part(s) to delete\n")
    for f in json_files:
        delete_part_from_file(
            f,
            clean_deps=args.clean_dependencies,
            clean_deps_yes=args.clean_dependencies_yes,
            remove_json=args.remove_json,
            api_print=args.api_print
        )

    print("\nDone.")

if __name__ == "__main__":
    main()
