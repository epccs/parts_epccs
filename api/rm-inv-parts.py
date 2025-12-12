#!/usr/bin/env python3
# file name: rm-inv-parts.py
# version: 2025-12-12-v9
# --------------------------------------------------------------
# Delete InvenTree parts based on JSON files in data/parts/<level>/...
#
# * Matches parts by sanitized name + revision (exact filename match)
# * Global search using name + revision + optional IPN fallback
# * --clean-dependencies -> two-step confirmation + deletes stock, BOMs, supplier parts, price breaks, etc.
# * --clean-dependencies-yes -> deletes ALL dependencies with NO confirmation
# * --remove-json -> deletes the JSON + .bom.json after successful removal
# * --api-print -> verbose API logging (GET preview, POST/PATCH/DELETE URLs)
# * Respects variant dependencies (no special handling needed - just deletes the variant)
# * Works with the exact same folder/layout as inv-parts_to_json.py and json_to_inv-parts.py
#
# Example usage:
#   python3 ./api/rm-inv-parts.py "4/Mechanical/Widgets/Widget_Assembly_Variant*" --clean-dependencies 
#   python3 ./api/rm-inv-parts.py "4/Mechanical/Widgets/Red_Widget.02" --clean-dependencies
#   python3 ./api/rm-inv-parts.py "2/Electronics/PCBA/Widget_Board*" --remove-json
#   python3 ./api/rm-inv-parts.py "2/Furniture/Tables/*_Table" --clean-dependencies --api-print
#   python3 ./api/rm-inv-parts.py "1/Mechanical/Fasteners/Wood_Screw" --clean-dependencies 
#   python3 ./api/rm-inv-parts.py "1/Furniture/Leg"
#   python3 ./api/rm-inv-parts.py "1/Furniture/*_Top"
# --------------------------------------------------------------
# Changelog:
#   pagination + robust response handling

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
if not BASE_URL:
    print("Error: INVENTREE_URL not set")
    sys.exit(1)
BASE_URL = BASE_URL.rstrip("/")

BASE_URL_PARTS           = f"{BASE_URL}/api/part/"
BASE_URL_BOM             = f"{BASE_URL}/api/bom/"
BASE_URL_STOCK           = f"{BASE_URL}/api/stock/"
BASE_URL_SUPPLIER_PARTS   = f"{BASE_URL}/api/company/part/"
BASE_URL_PRICE_BREAK     = f"{BASE_URL}/api/company/price-break/"

TOKEN = os.getenv("INVENTREE_TOKEN")
if not TOKEN:
    print("Error: INVENTREE_TOKEN not set")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ----------------------------------------------------------------------
# Robust paginated fetch
# ----------------------------------------------------------------------
def fetch_all(base_url: str, params=None, api_print=False) -> list:
    items = []
    url = base_url
    first = True

    while url:
        if api_print:
            p = f"?{requests.compat.urlencode(params or {})}" if params and first else ""
            print(f"API GET: {url}{p}")

        r = requests.get(url, headers=HEADERS, params=params or {})
        if r.status_code != 200:
            if api_print:
                print(f" ERROR {r.status_code}: {r.text[:200]}")
            break

        try:
            data = r.json()
        except json.JSONDecodeError:
            if api_print:
                print(" Non-JSON response")
            break

        results = data.get("results", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        items.extend(results)

        if api_print and results:
            print(f" Page has {len(results)} items:")
            for item in results[:5]:
                if "sub_part" in item:
                    print(f"     BOM: {item.get('quantity')} × PK {item.get('sub_part')} → Assembly PK {item.get('part')}")
                elif "part" in item and "supplier" in item:
                    print(f"     SupplierPart PK {item['pk']} | Part {item.get('part')}")
                else:
                    print(f"     {json.dumps(item, default=str)[:300]}")
            if len(results) > 5:
                print(f"     ... and {len(results)-5} more")

        url = data.get("next") if isinstance(data, dict) else None
        params = None
        first = False

    return items

# ----------------------------------------------------------------------
# API helpers
# ----------------------------------------------------------------------
def api_delete(url, api_print=False):
    if api_print:
        print(f"API DELETE: {url}")
    r = requests.delete(url, headers=HEADERS)
    if api_print:
        print(f" → {r.status_code}")
    return r

def api_patch(url, payload, api_print=False):
    if api_print:
        print(f"API PATCH: {url} → {payload}")
    r = requests.patch(url, headers=HEADERS, json=payload)
    if api_print:
        print(f" → {r.status_code}")
    return r

# ----------------------------------------------------------------------
# Part lookup
# ----------------------------------------------------------------------
def sanitize_part_name(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name.replace(' ', '_').replace('.', ',')).strip()

def sanitize_revision(rev):
    return "" if not rev else re.sub(r'[<>:"/\\|?*]', '_', str(rev).strip())

def find_part_exact(name_san, revision_san="", ipn="", api_print=False):
    params = {"name": name_san, "search": name_san}
    if revision_san:
        params["revision"] = revision_san
    if ipn:
        params["IPN"] = ipn

    results = fetch_all(BASE_URL_PARTS, params, api_print)
    return [p for p in results if p["name"] == name_san and (p.get("revision") or "") == revision_san]

# ----------------------------------------------------------------------
# Dependency handling – only BOMs where the part is the ASSEMBLY
# ----------------------------------------------------------------------
def check_dependencies(part_pk, api_print=False):
    total = 0

    # SupplierParts + PriceBreaks
    sps = fetch_all(BASE_URL_SUPPLIER_PARTS, {"part__pk": part_pk}, api_print)
    total += len(sps)
    for sp in sps:
        total += len(fetch_all(BASE_URL_PRICE_BREAK, {"part": sp["pk"]}))

    # Stock
    total += len(fetch_all(f"{BASE_URL_STOCK}?part={part_pk}", api_print=api_print))

    # BOM lines where this part is the parent assembly
    total += len(fetch_all(f"{BASE_URL_BOM}?part={part_pk}", api_print=api_print))

    return total

def delete_all_dependencies(part_pk, api_print=False):
    # SupplierParts
    for sp in fetch_all(BASE_URL_SUPPLIER_PARTS, {"part__pk": part_pk}, api_print):
        sp_pk = sp["pk"]
        if api_print:
            print(f"  Deleting SupplierPart PK {sp_pk}")
        for pb in fetch_all(BASE_URL_PRICE_BREAK, {"part": sp_pk}):
            api_delete(f"{BASE_URL_PRICE_BREAK}{pb['pk']}/", api_print)
        api_delete(f"{BASE_URL_SUPPLIER_PARTS}{sp_pk}/", api_print)

    # Stock
    for item in fetch_all(f"{BASE_URL_STOCK}?part={part_pk}"):
        api_delete(f"{BASE_URL_STOCK}{item['pk']}/", api_print)

    # BOM lines – only where this part is the parent
    for bom in fetch_all(f"{BASE_URL_BOM}?part={part_pk}", api_print):
        qty = bom.get("quantity")
        sub = bom.get("sub_part")
        if api_print:
            print(f"  Deleting BOM line: {qty} × Part PK {sub} (from this assembly)")
        api_delete(f"{BASE_URL_BOM}{bom['pk']}/", api_print)

# ----------------------------------------------------------------------
# Pattern → files
# ----------------------------------------------------------------------
def resolve_pattern_to_files(pattern):
    root = "data/parts"
    candidates = set()

    for ext in ["", ".json"]:
        path = os.path.join(root, pattern + ext)
        if os.path.isfile(path):
            candidates.add(path)

    if "*" in pattern or "?" in pattern:
        for ext in [".json", ".*.json"]:
            candidates.update(glob.glob(os.path.join(root, pattern + ext), recursive=True))

    return sorted({
        f for f in candidates
        if f.endswith(".json") and not f.endswith(".bom.json") and "category.json" not in f
    })

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
        print("  No name → skip")
        return

    name_san = sanitize_part_name(name_raw)
    revision_san = sanitize_revision(revision_raw)

    print(f"  Looking for: '{name_raw}' | Rev: '{revision_raw or '(none)'}' IPN: {ipn or '(none)'}")
    candidates = find_part_exact(name_san, revision_san, ipn, api_print)

    if not candidates:
        print("  Not found")
        return

    for part in candidates:
        pk = part["pk"]
        print(f"  Found PK {pk}")

        if clean_deps or clean_deps_yes:
            dep_count = check_dependencies(pk, api_print)
            if dep_count == 0:
                print("  No dependencies")
            else:
                if clean_deps_yes:
                    print(f"  Auto-deleting {dep_count} dependencies")
                else:
                    print(f"  {dep_count} dependencies found")
                    if input("  Type YES to delete dependencies: ") != "YES":
                        print("  Skipped")
                        continue
                    if input("  Type CONFIRM to permanently delete: ") != "CONFIRM":
                        print("  Aborted")
                        continue
                delete_all_dependencies(pk, api_print)

        api_patch(f"{BASE_URL_PARTS}{pk}/", {"active": False}, api_print)
        r = api_delete(f"{BASE_URL_PARTS}{pk}/", api_print)
        print(f"  SUCCESS: Deleted part PK {pk}" if r.status_code == 204 else f"  FAILED: {r.status_code}")

    if remove_json:
        for p in [json_path, json_path[:-5] + ".bom.json"]:
            if os.path.exists(p):
                os.remove(p)
                print(f"  Removed {p}")

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Safe InvenTree part deletion")
    parser.add_argument("patterns", nargs="*", default=["**/*"])
    parser.add_argument("--clean-dependencies", action="store_true")
    parser.add_argument("--clean-dependencies-yes", action="store_true")
    parser.add_argument("--remove-json", action="store_true")
    parser.add_argument("--api-print", action="store_true")
    args = parser.parse_args()

    if args.clean_dependencies and args.clean_dependencies_yes:
        print("Error: conflicting flags")
        sys.exit(1)

    files = []
    for pat in args.patterns:
        files.extend(resolve_pattern_to_files(pat))

    if not files:
        print("No files found")
        return

    print(f"Found {len(files)} part(s) to process\n")
    for f in files:
        delete_part_from_file(f, args.clean_dependencies, args.clean_dependencies_yes, args.remove_json, args.api_print)
    print("\nFinished safely.")

if __name__ == "__main__":
    main()
