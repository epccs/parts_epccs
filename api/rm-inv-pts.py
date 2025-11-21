#!/usr/bin/env python3
# file name: rm-inv-pts.py
# version: 2025-11-20-v3
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
# Fixed: Price breaks are now correctly deleted via SupplierPart -> PriceBreak
# No more invalid ?part__part= filter
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
        if r.status_code == 200:
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
# Search part by name + revision
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
# Dependency handling - FIXED price break deletion
# ----------------------------------------------------------------------
def check_dependencies(part_pk, api_print=False):
    endpoints = [
        (f"{BASE_URL_STOCK}?part={part_pk}", "stock"),
        (f"{BASE_URL_BOM}?sub_part={part_pk}", "used_in_bom"),
        (f"{BASE_URL_SUPPLIER_PARTS}?part={part_pk}", "supplier_parts"),
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
            if name == "supplier_parts":
                # Also count price breaks per supplier part
                for sp in items:
                    sp_pk = sp["pk"]
                    pb_resp = api_get(f"{BASE_URL_PRICE_BREAK}", params={"supplier_part": sp_pk}, api_print=False)
                    if pb_resp.status_code == 200:
                        pbs = pb_resp.json().get("results", pb_resp.json() if isinstance(pb_resp.json(), list) else [])
                        total += len(pbs)
    return deps, total

def delete_all_dependencies(part_pk, api_print=False):
    # 1. Get SupplierParts for this part
    sp_resp = api_get(f"{BASE_URL_SUPPLIER_PARTS}?part={part_pk}", api_print=api_print)
    if sp_resp.status_code == 200:
        supplier_parts = sp_resp.json().get("results", [])
        for sp in supplier_parts:
            sp_pk = sp["pk"]
            if api_print:
                print(f"  Deleting price breaks for SupplierPart {sp_pk}")

            # Delete price breaks for this SupplierPart
            pb_resp = api_get(f"{BASE_URL_PRICE_BREAK}", params={"supplier_part": sp_pk}, api_print=api_print)
            if pb_resp.status_code == 200:
                pbs = pb_resp.json().get("results", pb_resp.json() if isinstance(pb_resp.json(), list) else [])
                for pb in pbs:
                    api_delete(f"{BASE_URL_PRICE_BREAK}{pb['pk']}/", api_print=api_print)

            # Delete the SupplierPart itself
            api_delete(f"{BASE_URL_SUPPLIER_PARTS}{sp_pk}/", api_print=api_print)

    # 2. Delete stock items
    stock_resp = api_get(f"{BASE_URL_STOCK}?part={part_pk}", api_print=api_print)
    if stock_resp.status_code == 200:
        stocks = stock_resp.json().get("results", [])
        for item in stocks:
            api_delete(f"{BASE_URL_STOCK}{item['pk']}/", api_print=api_print)

    # 3. Delete BOM usages (where this part is used)
    bom_resp = api_get(f"{BASE_URL_BOM}?sub_part={part_pk}", api_print=api_print)
    if bom_resp.status_code == 200:
        boms = bom_resp.json().get("results", [])
        for bom in boms:
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
        print("  Missing name in JSON - skipping")
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

        # Deactivate + delete part
        api_patch(f"{BASE_URL_PARTS}{pk}/", {"active": False}, api_print=api_print)
        r = api_delete(f"{BASE_URL_PARTS}{pk}/", api_print=api_print)
        if r.status_code == 204:
            print(f"  SUCCESS: Deleted part PK {pk}")
        else:
            print(f"  FAILED: {r.status_code} {r.text}")
            return

    # Remove JSON files on success
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
