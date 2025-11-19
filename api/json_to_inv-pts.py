#!/usr/bin/env python3
# file name: json_to_inv-pts.py
# version: 2025-11-18-v16
# --------------------------------------------------------------
# Push all parts (templates, assemblies, real) from data/pts/<level>/ to InvenTree, level by level.
#
# * Folder structure under each level -> category hierarchy
# * Supports Part_Name[.revision].json + [Part_Name[.revision].bom.json]
# * Pushes categories on demand from folder paths
# * Pushes parts level by level to respect dependencies
# * --force-ipn -> generate IPN from name when missing
# * --force -> delete existing part (name + revision)
# * --clean-dependencies -> delete BOM/stock/etc. (with confirmation)
# * --force-price -> delete existing price breaks before pushing new ones
# * --api-print: prints every API call (URL + payload) without Authorization header
# * .bom.json pushed only if exists
# * pushes suppliers/manufacturers/price breaks if purchaseable, fetched globally + local filter (no ?supplier_part=)
# * Uses a cache for part lookups to improve performance
#
# example usage:
# python3 ./api/json_to_inv-pts.py "1/Mechanical/Fasteners/Wood_Screw" --force --force-ipn --clean-dependencies
# python3 ./api/json_to_inv-pts.py "1/Furniture/Leg" --force --force-ipn --clean-dependencies
# python3 ./api/json_to_inv-pts.py "1/Furniture/*_Top" --force --force-ipn --clean-dependencies
# python3 ./api/json_to_inv-pts.py "2/Furniture/Tables/*_Table" --force --force-ipn --clean-dependencies
# python3 ./api/json_to_inv-pts.py "**/*" --force --clean-dependencies
# --------------------------------------------------------------

import requests
import json
import os
import glob
import argparse
import sys
import re
from collections import defaultdict

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
BASE_URL = os.getenv("INVENTREE_URL").rstrip("/")
BASE_URL_PARTS = f"{BASE_URL}/api/part/"
BASE_URL_CATEGORIES = f"{BASE_URL}/api/part/category/"
BASE_URL_BOM = f"{BASE_URL}/api/bom/"
BASE_URL_COMPANY = f"{BASE_URL}/api/company/"
BASE_URL_SUPPLIER_PARTS = f"{BASE_URL}/api/company/part/"
BASE_URL_MANUFACTURER_PART = f"{BASE_URL}/api/company/part/manufacturer/"
BASE_URL_PRICE_BREAK = f"{BASE_URL}/api/company/price-break/"

TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ----------------------------------------------------------------------
# API helpers
# ----------------------------------------------------------------------
def fetch_all(url, api_print=False):
    items = []
    while url:
        if api_print:
            print(f"API GET: {url}")
        r = requests.get(url, headers=HEADERS)
        if r.status_code != 200:
            raise Exception(f"API error {r.status_code}: {r.text}")
        data = r.json()
        if api_print and "results" in data:
            preview = json.dumps(data["results"][:3], indent=2)
            print(f"Response (first 3): {preview} {'...' if len(data['results']) > 3 else ''}")
        if isinstance(data, dict) and "results" in data:
            items.extend(data["results"])
            url = data.get("next")
        else:
            items.extend(data if isinstance(data, list) else [data])
            url = None
    return items

def api_post(url, payload, api_print=False):
    if api_print:
        print(f"API POST: {url}")
        print(f"Payload: {json.dumps(payload, indent=4)}")
    r = requests.post(url, headers=HEADERS, json=payload)
    if r.status_code not in (200, 201):
        print(f"ERROR {r.status_code}: {r.text}")
        sys.exit(1)
    return r.json()

def api_patch(url, payload, api_print=False):
    if api_print:
        print(f"API PATCH: {url}")
        print(f"Payload: {json.dumps(payload, indent=4)}")
    r = requests.patch(url, headers=HEADERS, json=payload)
    if r.status_code not in (200, 201):
        print(f"ERROR {r.status_code}: {r.text}")
        sys.exit(1)
    return r.json()

def api_delete(url, api_print=False):
    if api_print:
        print(f"API DELETE: {url}")
    r = requests.delete(url, headers=HEADERS)
    if r.status_code not in (200, 201, 204):
        print(f"ERROR {r.status_code}: {r.text}")

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def sanitize_company_name(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name.replace(' ', '_').replace('.', '').strip())

def check_category_exists(name, parent_pk=None):
    params = {"name": name}
    if parent_pk is not None:
        params["parent"] = parent_pk
    data = requests.get(BASE_URL_CATEGORIES, headers=HEADERS, params=params).json()
    return data.get("results", data) if isinstance(data, dict) else data

def create_category_hierarchy(folder_path, start_dir, parent_pk=None):
    parts = os.path.relpath(folder_path, start_dir).split(os.sep)
    cur = parent_pk
    for name in parts:
        if not name or name == ".":
            continue
        existing = check_category_exists(name, cur)
        if existing:
            cur = existing[0]["pk"]
            continue
        payload = {"name": name, "parent": cur}
        cur = api_post(BASE_URL_CATEGORIES, payload)["pk"]
    return cur

def parse_filename(filepath):
    basename = os.path.basename(filepath)
    if not basename.endswith(".json"):
        return None, None
    name_part = basename[:-5]
    if "." in name_part:
        name, rev = name_part.rsplit(".", 1)
        return name, rev
    return name_part, None

def check_part_exists(cache, name, revision=None, ipn=None):
    candidates = cache.get(name, [])
    results = []
    for res in candidates:
        if (revision is None or res.get('revision') == revision) and (ipn is None or res.get('IPN') == ipn):
            results.append(res)
    return results

# ----------------------------------------------------------------------
# Push one part
# ----------------------------------------------------------------------
def push_part(part_path, force_ipn=False, force=False, clean=False, force_price=False, api_print=False, level_dir=None, cache=None, all_price_breaks=None):
    print(f"DEBUG: Pushing {part_path}")
    name, rev_from_file = parse_filename(part_path)
    if not name:
        return

    with open(part_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        data = data[0]

    revision = rev_from_file or data.get("revision", "")

    payload = {k: data.get(k) for k in [
        "name", "description", "IPN", "keywords", "units",
        "minimum_stock", "assembly", "component", "trackable",
        "purchaseable", "salable", "virtual", "is_template"
    ] if k in data}
    payload["name"] = name
    payload["active"] = True
    if revision:
        payload["revision"] = revision

    if force_ipn and (not payload.get("IPN") or payload["IPN"].strip() == ""):
        payload["IPN"] = name[:50]
        print(f"DEBUG: Generated IPN -> {payload['IPN']}")

    payload["category"] = create_category_hierarchy(os.path.dirname(part_path), level_dir)

    variant_of_name = data.get("variant_of_name")
    if variant_of_name:
        variants = check_part_exists(cache, variant_of_name)
        if variants:
            payload["variant_of"] = variants[0]["pk"]

    existing = check_part_exists(cache, name, revision if revision else None, payload.get("IPN"))

    new_pk = None
    if existing and force:
        for p in existing:
            print(f"DEBUG: --force: deleting part PK {p['pk']}")
            api_delete(f"{BASE_URL_PARTS}{p['pk']}/", api_print)
            cache[name] = [c for c in cache[name] if c["pk"] != p["pk"]]
    if existing and not force:
        print(f"DEBUG: Part exists – using PK {existing[0]['pk']}")
        new_pk = existing[0]["pk"]
        fresh = requests.get(f"{BASE_URL_PARTS}{new_pk}/", headers=HEADERS).json()
        cache[name] = [fresh]
    else:
        new = api_post(BASE_URL_PARTS, payload, api_print)
        new_pk = new["pk"]
        print(f"DEBUG: Created '{new['name']}' (PK {new_pk})")
        cache[new["name"]].append(new)

    if new_pk is None:
        return

    # Suppliers & pricing
    if data.get("purchaseable", False):
        for supplier in data.get("suppliers", []):
            supplier_name = sanitize_company_name(supplier["supplier_name"])
            suppliers = [s for s in fetch_all(BASE_URL_COMPANY, {"name": supplier_name, "is_supplier": True}, api_print) if s["name"] == supplier_name]
            if not suppliers:
                print(f"ERROR: Supplier '{supplier_name}' not found")
                sys.exit(1)
            supplier_pk = suppliers[0]["pk"]

            # ManufacturerPart (optional)
            mp_pk = None
            if "manufacturer_name" in supplier:
                man_name = sanitize_company_name(supplier["manufacturer_name"])
                mans = [m for m in fetch_all(BASE_URL_COMPANY, {"name": man_name, "is_manufacturer": True}, api_print) if m["name"] == man_name]
                if mans:
                    man_pk = mans[0]["pk"]
                    mp_existing = fetch_all(BASE_URL_MANUFACTURER_PART, {"part": new_pk, "manufacturer": man_pk}, api_print)
                    if mp_existing:
                        mp_pk = mp_existing[0]["pk"]
                    else:
                        mp_payload = {
                            "part": new_pk,
                            "manufacturer": man_pk,
                            "MPN": supplier.get("MPN", ""),
                            "description": supplier.get("mp_description", ""),
                            "link": supplier.get("mp_link", "")
                        }
                        mp_pk = api_post(BASE_URL_MANUFACTURER_PART, mp_payload, api_print)["pk"]

            # SupplierPart
            sp_existing = fetch_all(BASE_URL_SUPPLIER_PARTS, {"part": new_pk, "supplier": supplier_pk, "SKU": supplier.get("SKU", "")}, api_print)
            if sp_existing:
                sp_pk = sp_existing[0]["pk"]
            else:
                sp_payload = {
                    "part": new_pk,
                    "supplier": supplier_pk,
                    "manufacturer_part": mp_pk,
                    "SKU": supplier.get("SKU", ""),
                    "description": supplier.get("description", ""),
                    "link": supplier.get("link", ""),
                    "note": supplier.get("note", ""),
                    "packaging": supplier.get("packaging", "")
                }
                sp_pk = api_post(BASE_URL_SUPPLIER_PARTS, sp_payload, api_print)["pk"]

            # Price breaks – FIXED: no ?supplier_part= filter, use global list + local filter
            sp_price_breaks = [pb for pb in all_price_breaks if pb["part"] == sp_pk]
            existing_by_quantity = {pb["quantity"]: pb for pb in sp_price_breaks}

            for pb in supplier.get("price_breaks", []):
                q = pb.get("quantity", 0)
                price = pb.get("price", 0.0)
                currency = pb.get("price_currency", "")

                if q in existing_by_quantity:
                    existing_pb = existing_by_quantity[q]
                    if existing_pb["price"] == price and existing_pb["price_currency"] == currency:
                        print(f"DEBUG: Skipping unchanged quantity {q}")
                        continue
                    pb_payload = {
                        "part": sp_pk,  # current InvenTree quirk – keep until fixed
                        "price": price,
                        "price_currency": currency
                    }
                    api_patch(f"{BASE_URL_PRICE_BREAK}{existing_pb['pk']}/", pb_payload, api_print)
                    print(f"DEBUG: Updated quantity {q} → {price} {currency}")
                else:
                    pb_payload = {
                        "part": sp_pk,  # current InvenTree quirk
                        "quantity": q,
                        "price": price,
                        "price_currency": currency
                    }
                    api_post(BASE_URL_PRICE_BREAK, pb_payload, api_print)
                    print(f"DEBUG: Created quantity {q} → {price} {currency}")

    # BOM
    bom_path = part_path[:-5] + ".bom.json"
    if os.path.exists(bom_path):
        print(f"DEBUG: Pushing BOM from {bom_path}")
        push_bom(new_pk, bom_path, cache=cache, api_print=api_print)

# ----------------------------------------------------------------------
# BOM push
# ----------------------------------------------------------------------
def push_bom(parent_pk, bom_path, level=0, cache=None, api_print=False):
    indent = " " * level
    with open(bom_path, "r", encoding="utf-8") as f:
        tree = json.load(f)

    existing_boms = fetch_all(f"{BASE_URL_BOM}?part={parent_pk}", api_print=api_print)

    for node in tree:
        qty = node.get("quantity", 1)
        note = node.get("note", "")
        sub_name = node["sub_part"]["name"]
        sub_ipn = node["sub_part"].get("IPN", "")

        sub_parts = check_part_exists(cache, sub_name, None, sub_ipn if sub_ipn else None)
        if not sub_parts:
            print(f"{indent}WARNING: Sub-part '{sub_name}' not found – skipping")
            continue
        sub_pk = sub_parts[0]["pk"]

        existing = [b for b in existing_boms if b["sub_part"] == sub_pk]
        payload = {"part": parent_pk, "sub_part": sub_pk, "quantity": qty, "note": note}

        if existing:
            api_patch(f"{BASE_URL_BOM}{existing[0]['pk']}/", payload, api_print)
            action = "UPDATED"
        else:
            api_post(BASE_URL_BOM, payload, api_print)
            action = "CREATED"

        print(f"{indent}{action} BOM: {qty} × {sub_name} (sub_pk {sub_pk})")

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("patterns", nargs="*", default=["**/*"])
    parser.add_argument("--force-ipn", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--clean-dependencies", action="store_true")
    parser.add_argument("--force-price", action="store_true")
    parser.add_argument("--api-print", action="store_true")
    args = parser.parse_args()

    print("DEBUG: Building part cache...")
    all_parts = fetch_all(BASE_URL_PARTS, api_print=args.api_print)
    cache = defaultdict(list)
    for p in all_parts:
        cache[p["name"]].append(p)
    print(f"DEBUG: Cached {len(all_parts)} parts")

    # Pre-fetch all price breaks once – avoids broken ?supplier_part= filter
    print("DEBUG: Fetching all price breaks...")
    all_price_breaks = fetch_all(BASE_URL_PRICE_BREAK, api_print=args.api_print)
    print(f"DEBUG: Fetched {len(all_price_breaks)} price breaks")

    root = "data/pts"
    files = []
    for pat in args.patterns:
        files.extend(glob.glob(os.path.join(root, pat), recursive=True))
        files.extend(glob.glob(os.path.join(root, pat + ".*json"), recursive=True))
    files = sorted({f for f in files if f.endswith(".json") and not f.endswith(".bom.json") and "category.json" not in f})

    for f in files:
        push_part(f, args.force_ipn, args.force, args.clean_dependencies, args.force_price, args.api_print, root, cache, all_price_breaks)

if __name__ == "__main__":
    main()
