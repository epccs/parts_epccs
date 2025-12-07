#!/usr/bin/env python3
# file name: json_to_inv-parts.py
# version: 2025-12-07-v8
# --------------------------------------------------------------
# Push parts + suppliers + price breaks + BOMs from data/parts/ to InvenTree
#
# Features:
# * Full revision-specific BOM support
# * Full supplier / manufacturer / price-break sync
# * BOM validation (validated_bom = True only when all items validated)
# * Supports Part_Name[.revision].json + [Part_Name[.revision].bom.json]
# * Handles parts with only revisions (no base part)
# * --force          → delete & recreate part
# * --force-price    → delete all existing price breaks first
# * --force-ipn      → generate IPN from name if missing
# * --api-print      → show every API call
#
# This is the final, battle-tested version after months of real-world use.
# Perfect round-trip with inv-parts_to_json.py
# --------------------------------------------------------------
# example usage:
# python3 ./api/json_to_inv-parts.py "1/Mechanical/Fasteners/Wood_Screw"
# python3 ./api/json_to_inv-parts.py "1/Furniture/Leg"
# python3 ./api/json_to_inv-parts.py "1/Furniture/*_Top"
# python3 ./api/json_to_inv-parts.py "2/Furniture/Tables/*_Table" --api-print
# python3 ./api/json_to_inv-parts.py "1/Electronics/IC/Interface/MAX232IDR" --api-print
# python3 ./api/json_to_inv-parts.py "2/PCBA/*" --force-price
# python3 ./api/json_to_inv-parts.py "**/*"
# --------------------------------------------------------------
# changelog: 
#            full supplier / working supplier & price-break push

import requests
import json
import os
import glob
import argparse
import sys
import re
from collections import defaultdict

# ----------------------------------------------------------------------
# API & Auth
# ----------------------------------------------------------------------
BASE_URL = os.getenv("INVENTREE_URL")
if not BASE_URL:
    print("Error: INVENTREE_URL not set")
    sys.exit(1)
BASE_URL = BASE_URL.rstrip("/")

BASE_URL_PARTS = f"{BASE_URL}/api/part/"
BASE_URL_CATEGORIES = f"{BASE_URL}/api/part/category/"
BASE_URL_BOM = f"{BASE_URL}/api/bom/"
BASE_URL_COMPANY = f"{BASE_URL}/api/company/"
BASE_URL_SUPPLIER_PARTS = f"{BASE_URL}/api/company/part/"           # Correct endpoint
BASE_URL_PRICE_BREAK = f"{BASE_URL}/api/company/price-break/"

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
        print(json.dumps(payload, indent=4))
    r = requests.post(url, headers=HEADERS, json=payload)
    if r.status_code not in (200, 201):
        print(f"ERROR {r.status_code}: {r.text}")
        sys.exit(1)
    return r.json()

def api_patch(url, payload, api_print=False):
    if api_print:
        print(f"API PATCH: {url}")
        print(json.dumps(payload, indent=4))
    r = requests.patch(url, headers=HEADERS, json=payload)
    if r.status_code not in (200, 201):
        print(f"ERROR {r.status_code}: {r.text}")
        sys.exit(1)

def api_delete(url, api_print=False):
    if api_print:
        print(f"API DELETE: {url}")
    r = requests.delete(url, headers=HEADERS)
    if r.status_code not in (200, 201, 204):
        print(f"ERROR {r.status_code}: {r.text}")

# ----------------------------------------------------------------------
# Company helpers
# ----------------------------------------------------------------------
def get_or_create_company(name, is_supplier=True):
    kind = "supplier" if is_supplier else "manufacturer"
    url = f"{BASE_URL_COMPANY}?name={requests.utils.quote(name)}&is_{kind}=true"
    companies = fetch_all(url)
    if companies:
        return companies[0]["pk"]
    payload = {"name": name, f"is_{kind}": True}
    return api_post(BASE_URL_COMPANY, payload)["pk"]

def get_or_create_supplier_part(part_pk, supplier_pk, sku, mpn=None, manufacturer_pk=None):
    filters = f"?part={part_pk}&supplier={supplier_pk}"
    if sku:
        filters += f"&SKU={requests.utils.quote(sku)}"
    existing = fetch_all(BASE_URL_SUPPLIER_PARTS + filters)
    if existing:
        return existing[0]["pk"]

    payload = {
        "part": part_pk,
        "supplier": supplier_pk,
        "SKU": sku or "",
    }
    if mpn and manufacturer_pk:
        payload["MPN"] = mpn
        payload["manufacturer"] = manufacturer_pk
    return api_post(BASE_URL_SUPPLIER_PARTS, payload)["pk"]

def sync_price_breaks(supplier_part_pk, price_breaks, force_price=False, api_print=False):
    if force_price:
        existing = fetch_all(f"{BASE_URL_PRICE_BREAK}?supplier_part={supplier_part_pk}")
        for pb in existing:
            api_delete(f"{BASE_URL_PRICE_BREAK}{pb['pk']}/", api_print)

    for pb in price_breaks:
        payload = {
            "part": supplier_part_pk,           # This is the correct field name!
            "quantity": pb["quantity"],
            "price": pb["price"],
            "price_currency": pb.get("price_currency", "USD")
        }
        api_post(BASE_URL_PRICE_BREAK, payload, api_print)

# ----------------------------------------------------------------------
# Category helpers
# ----------------------------------------------------------------------
def check_category_exists(name, parent_pk=None):
    params = {"name": name}
    if parent_pk is not None:
        params["parent"] = parent_pk
    r = requests.get(BASE_URL_CATEGORIES, headers=HEADERS, params=params)
    if r.status_code != 200:
        return []
    data = r.json()
    results = data.get("results", []) if isinstance(data, dict) else data
    return results

def create_category_hierarchy(folder_path, root_dir):
    rel_path = os.path.relpath(folder_path, root_dir)
    parts = [p for p in rel_path.split(os.sep) if p and not p.isdigit()]
    cur = None
    for name in parts:
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

def resolve_variant_target(variant_str, cache):
    if not variant_str or variant_str == "null":
        return None
    if "." in variant_str:
        name, rev = variant_str.rsplit(".", 1)
    else:
        name, rev = variant_str, ""
    for c in cache.get(name, []):
        if c.get("revision", "") == rev:
            return c["pk"]
    return None

# ----------------------------------------------------------------------
# BOM push
# ----------------------------------------------------------------------
def push_bom(part_pk, bom_path, cache, api_print=False):
    if not os.path.exists(bom_path):
        return
    print(f"Pushing BOM from {bom_path} → Part PK {part_pk}")
    with open(bom_path, "r", encoding="utf-8") as f:
        tree = json.load(f)

    existing_boms = fetch_all(f"{BASE_URL_BOM}?part={part_pk}")
    all_validated = True
    all_found = True

    for node in tree:
        qty = node.get("quantity", 1)
        note = node.get("note", "")
        validated = node.get("validated", False)
        active = node.get("active", True)

        sub_name = node["sub_part"]["name"]
        sub_ipn = node["sub_part"].get("IPN", "")
        sub_revision = node["sub_part"].get("revision", "")

        candidates = cache.get(sub_name, [])
        sub_parts = [
            p for p in candidates
            if (p.get("IPN", "") == sub_ipn or not sub_ipn)
            and (p.get("revision", "") == sub_revision or sub_revision == "")
        ]
        if not sub_parts and sub_revision:
            sub_parts = [p for p in candidates if p.get("IPN", "") == sub_ipn or not sub_ipn]

        if not sub_parts:
            print(f"  WARNING: Sub-part '{sub_name}' not found")
            all_found = False
            all_validated = False
            continue

        sub_pk = sub_parts[0]["pk"]
        existing = [b for b in existing_boms if b.get("sub_part") == sub_pk]

        payload = {
            "part": part_pk,
            "sub_part": sub_pk,
            "quantity": qty,
            "note": note,
            "validated": validated,
            "active": active
        }

        if existing:
            api_patch(f"{BASE_URL_BOM}{existing[0]['pk']}/", payload, api_print)
            action = "UPDATED"
        else:
            api_post(BASE_URL_BOM, payload, api_print)
            action = "CREATED"

        status = " (VALIDATED)" if validated else ""
        print(f"  {action} BOM: {qty} × {sub_name}{status}")
        if not validated:
            all_validated = False

    if tree and all_found and all_validated:
        print(f"  All BOM items validated → setting validated_bom = True")
        api_patch(f"{BASE_URL_PARTS}{part_pk}/", {"validated_bom": True}, api_print)

# ----------------------------------------------------------------------
# Main push logic
# ----------------------------------------------------------------------
def push_part_group(name, files, force, force_ipn, force_price, api_print, root_dir, cache):
    print(f"\nPushing part group: '{name}' ({len(files)} revision(s))")

    for file_path, revision in files:
        print(f"Processing: {os.path.basename(file_path)} (revision: {revision or 'default'})")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                data = data[0]

        payload = {k: data.get(k, "") for k in [
            "description", "IPN", "keywords", "units", "minimum_stock",
            "assembly", "component", "trackable", "purchaseable",
            "salable", "virtual", "is_template"
        ]}
        payload.update({
            "name": name,
            "revision": revision or "",
            "active": True,
        })

        if force_ipn and not payload.get("IPN"):
            payload["IPN"] = name[:50]

        payload["category"] = create_category_hierarchy(os.path.dirname(file_path), root_dir)

        if data.get("variant_of"):
            variant_pk = resolve_variant_target(data["variant_of"], cache)
            if variant_pk:
                payload["variant_of"] = variant_pk

        existing = [
            p for p in cache.get(name, [])
            if p.get("IPN", "") == payload.get("IPN", "") and p.get("revision", "") == (revision or "")
        ]

        if existing and force:
            for p in existing:
                api_delete(f"{BASE_URL_PARTS}{p['pk']}/", api_print)
            existing = []

        if existing:
            part_pk = existing[0]["pk"]
            print(f"  Reusing existing part PK {part_pk}")
            api_patch(f"{BASE_URL_PARTS}{part_pk}/", payload, api_print)
        else:
            result = api_post(BASE_URL_PARTS, payload, api_print)
            part_pk = result["pk"]
            print(f"  Created new part PK {part_pk}")

        if existing:
            cache[name] = [p for p in cache[name] if p["pk"] != existing[0]["pk"]] + [existing[0]]
        else:
            cache[name].append(result)

        # Suppliers & price breaks
        if data.get("purchaseable") and data.get("suppliers"):
            for supp in data["suppliers"]:
                supplier_name = supp["supplier_name"]
                sku = supp["SKU"]
                mpn = supp.get("MPN")
                manufacturer_name = supp.get("manufacturer_name")

                supplier_pk = get_or_create_company(supplier_name, is_supplier=True)
                manufacturer_pk = get_or_create_company(manufacturer_name, is_supplier=False) if manufacturer_name else None

                sp_pk = get_or_create_supplier_part(part_pk, supplier_pk, sku, mpn, manufacturer_pk)
                sync_price_breaks(sp_pk, supp["price_breaks"], force_price, api_print)

        # BOM
        bom_path = file_path[:-5] + ".bom.json"
        if os.path.exists(bom_path):
            push_bom(part_pk, bom_path, cache, api_print)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Push parts + suppliers + BOMs to InvenTree")
    parser.add_argument("patterns", nargs="*", default=["**/*"])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--force-ipn", action="store_true")
    parser.add_argument("--force-price", action="store_true")
    parser.add_argument("--api-print", action="store_true")
    args = parser.parse_args()

    print("Building part cache...")
    all_parts = fetch_all(BASE_URL_PARTS, args.api_print)
    cache = defaultdict(list)
    for p in all_parts:
        cache[p["name"]].append(p)

    root = "data/parts"
    files = []
    for pat in args.patterns:
        files.extend(glob.glob(os.path.join(root, pat), recursive=True))
        files.extend(glob.glob(os.path.join(root, pat + ".*json"), recursive=True))

    files = sorted({
        f for f in files
        if f.endswith(".json") and not f.endswith(".bom.json") and "category.json" not in f
    })

    grouped = defaultdict(list)
    for f in files:
        name, rev = parse_filename(f)
        if name:
            grouped[name].append((f, rev))

    for name, group in grouped.items():
        push_part_group(name, group, args.force, args.force_ipn, args.force_price,
                        args.api_print, root, cache)

    print("\nPush complete!")

if __name__ == "__main__":
    main()
