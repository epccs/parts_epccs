#!/usr/bin/env python3
# file name: rm-inv-pts.py
# version: 2025-11-20-v4
# --------------------------------------------------------------
# Delete InvenTree parts based on JSON files in data/pts/<level>/...
#
# * Matches parts by sanitized name + revision (exact filename match)
# * Global search using name + revision + optional IPN fallback
# * --clean-dependencies -> two-step confirmation + deletes stock, BOMs, supplier parts, price breaks, etc.
# * --remove-json -> deletes the JSON + .bom.json after successful removal
# * --api-print -> verbose API logging (GET preview, POST/PATCH/DELETE URLs)
# * Respects variant dependencies (no special handling needed - just deletes the variant)
# * Works with the exact same folder/layout as inv-pts_to_json.py and json_to_inv-pts.py
#
# Example usage:
#   python3 ./api/rm-inv-pts.py "4/Mechanical/Widgets/Widget_Assembly_Variant*" --clean-dependencies --remove-json
#   python3 ./api/rm-inv-pts.py "2/Electronics/PCBA/Widget_Board*" --remove-json
# --------------------------------------------------------------
# Changelog:
# Fixed: Safe handling of price-break endpoint returning list OR dict
# Fixed: Robust JSON parsing for all paginated endpoints
# --------------------------------------------------------------
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
# Safe JSON list extractor
# ----------------------------------------------------------------------
def extract_results(data):
    """Handle both paginated {'results': [...]} and direct list responses."""
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

    data = r.json()
    results = extract_results(data)
    filtered = [
        p for p in results
        if p.get("name") == name_san and
           (p.get("revision") or "") == (revision_san or "")
    ]
    return filtered

# ----------------------------------------------------------------------
# Dependency handling - now fully safe
# ----------------------------------------------------------------------
def check_dependencies(part_pk, api_print=False):
    endpoints = [
        (f"{BASE_URL_STOCK}?part={part_pk}", "stock"),
        (f"{BASE_URL_BOM}?sub_part={part_pk}", "used_in_bom"),
        (f"{BASE_URL_SUPPLIER_PARTS}?part={part_pk}", "supplier_parts"),
    ]
    total = 0
    for url, name in endpoints:
        r = api_get(url, api_print=api_print)
        if r.status_code == 200:
            items = extract_results(r.json())
            if name == "supplier_parts":
                for sp in items:
                    sp_pk = sp["pk"]
                    pb_r = api_get(f"{BASE_URL_PRICE_BREAK}", params={"supplier_part": sp_pk}, api_print=False)
                    if pb_r.status_code == 200:
                        total += len(extract_results(pb_r.json()))
            total += len(items)
    return None, total  # we don't need the dict anymore, just count

def delete_all_dependencies(part_pk, api_print=False):
    # 1. SupplierParts + their price breaks
    sp_r = api_get(f"{BASE_URL_SUPPLIER_PARTS}?part={part_pk}", api_print=api_print)
    if sp_r.status_code == 200:
        supplier_parts = extract_results(sp_r.json())
        for sp in supplier_parts:
            sp_pk = sp["pk"]
            if api_print:
                print(f"  Deleting price breaks + SupplierPart {sp_pk}")

            # Price breaks
            pb_r = api_get(f"{BASE_URL_PRICE_BREAK}", params={"supplier_part": sp_pk}, api_print=api_print)
            if pb_r.status_code == 200:
                for pb in extract_results(pb_r.json()):
                    api_delete(f"{BASE_URL_PRICE_BREAK}{pb['pk']}/", api_print=api_print)

            # SupplierPart itself
            api_delete(f"{BASE_URL_SUPPLIER_PARTS}{sp_pk}/", api_print=api_print)

    # 2. Stock items
    stock_r = api_get(f"{BASE_URL_STOCK}?part={part_pk}", api_print=api_print)
    if stock_r.status_code == 200:
        for item in extract_results(stock_r.json()):
            api_delete(f"{BASE_URL_STOCK}{item['pk']}/", api_print=api_print)

    # 3. BOM usages
    bom_r = api_get(f"{BASE_URL_BOM}?sub_part={part_pk}", api_print=api_print)
    if bom_r.status_code == 200:
        for bom in extract_results(bom_r.json()):
            api_delete(f"{BASE_URL_BOM}{bom['pk']}/", api_print=api_print)

# ----------------------------------------------------------------------
# Main deletion
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

        if clean_deps:
            _, total = check_dependencies(pk, api_print=False)
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
    parser.add_argument("--clean-dependencies", action="store_true")
    parser.add_argument("--remove-json", action="store_true")
    parser.add_argument("--api-print", action="store_true")
    args = parser.parse_args()

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
        delete_part_from_file(f, args.clean_dependencies, args.remove_json, args.api_print)

    print("\nDone.")

if __name__ == "__main__":
    main()
