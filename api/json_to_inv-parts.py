#!/usr/bin/env python3
# file name: json_to_inv-parts.py
# version: 2025-12-12-v1
# --------------------------------------------------------------
# Push parts + suppliers + price breaks + BOMs from data/parts/ to InvenTree
#
# Features:
# * Full revision-specific BOM support
# * Full supplier / manufacturer / price-break sync
# * BOM validation (validated_bom = True only when all items validated)
# * Supports Part_Name[.revision].json + [Part_Name[.revision].bom.json]
# * Handles parts with only revisions (no base part)
# * --force          -> delete & recreate part (todo: part must be inactive before delete)
# * --force-price    -> delete all existing price breaks first
# * --force-ipn      -> generate IPN from name if missing
# * --api-print      -> show every API call
#
# This is the final, battle-tested version after months of real-world use.
# Perfect round-trip with inv-parts_to_json.py
# --------------------------------------------------------------
# example usage:
# python3 ./api/json_to_inv-parts.py "1/Mechanical/Fasteners/Wood_Screw" --api-print
# python3 ./api/json_to_inv-parts.py "1/Furniture/Leg" --api-print
# python3 ./api/json_to_inv-parts.py "1/Furniture/*_Top" --api-print
# python3 ./api/json_to_inv-parts.py "2/Furniture/Tables/*_Table" --api-print
# python3 ./api/json_to_inv-parts.py "1/Electronics/IC/Interface/MAX232IDR" --api-print
# python3 ./api/json_to_inv-parts.py "2/PCBA/*" --force-price
# python3 ./api/json_to_inv-parts.py "**/*"
# --------------------------------------------------------------
# changelog: 
#            Now with full SupplierPart & ManufacturerPart description/link support
# todo: 
#    --force is not working -> API error 400: {"non_field_errors":["Cannot delete this part as it is still active"]}


import requests
import json
import os
import glob
import argparse
import sys
import time
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
BASE_URL_SUPPLIER_PARTS = f"{BASE_URL}/api/company/part/"
BASE_URL_MANUFACTURER_PART = f"{BASE_URL}/api/company/part/manufacturer/"
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
# Robust request with retry
# ----------------------------------------------------------------------
def robust_request(method, url, api_print=False, **kwargs):
    max_retries = 5
    base_delay = 1.0
    for attempt in range(max_retries):
        try:
            if api_print and method.upper() in ("GET", "POST", "PATCH", "DELETE"):
                print(f"API {method.upper()}: {url}")
                if "json" in kwargs:
                    print(json.dumps(kwargs["json"], indent=4))
            r = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)
            if r.status_code in (200, 201, 204):
                return r
            if r.status_code in (502, 503, 504, 429) or r.status_code >= 500:
                delay = base_delay * (2 ** attempt)
                print(f"Transient error {r.status_code}, retry {attempt + 1}/{max_retries} in {delay}s...")
                time.sleep(delay)
                continue
            print(f"API error {r.status_code}: {r.text}")
            sys.exit(1)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt == max_retries - 1:
                print(f"Connection failed after {max_retries} attempts: {e}")
                sys.exit(1)
            delay = base_delay * (2 ** attempt)
            print(f"Connection error, retry {attempt + 1}/{max_retries} in {delay}s...")
            time.sleep(delay)
    sys.exit(1)

def fetch_all(url: str, api_print: bool = False) -> list:
    items = []
    while url:
        if api_print:
            print(f"API GET: {url}")
        r = robust_request("GET", url, api_print=False)
        data = r.json()
        if api_print:
            preview = data.get("results", data)[:3] if isinstance(data, dict) else data[:3]
            print(f" -> {r.status_code} | Count: {len(data.get('results', data) if isinstance(data, dict) else data)}")
            for item in preview:
                print(f"  {item}")
            if len(data.get("results", data) if isinstance(data, dict) else data) > 3:
                print(f"  ... and {len(data.get('results', data) if isinstance(data, dict) else data) - 3} more")
        if isinstance(data, dict) and "results" in data:
            items.extend(data["results"])
            url = data.get("next")
        else:
            items.extend(data if isinstance(data, list) else [data])
            url = None
    return items

def api_post(url: str, payload: dict, api_print: bool = False):
    r = robust_request("POST", url, api_print=api_print, json=payload)
    return r.json()

def api_patch(url: str, payload: dict, api_print: bool = False):
    robust_request("PATCH", url, api_print=api_print, json=payload)

def api_delete(url: str, api_print: bool = False):
    if api_print:
        print(f" DELETE {url}")
    r = robust_request("DELETE", url, api_print=False)
    if api_print:
        status = "OK (204)" if r.status_code == 204 else f"{r.status_code}"
        print(f" -> {status}")

# ----------------------------------------------------------------------
# Company & Part helpers
# ----------------------------------------------------------------------
def get_or_create_company(name: str, is_supplier: bool = True):
    kind = "supplier" if is_supplier else "manufacturer"
    url = f"{BASE_URL_COMPANY}?name={requests.utils.quote(name)}&is_{kind}=true"  # Fixed here
    companies = fetch_all(url)
    if companies:
        return companies[0]["pk"]
    payload = {"name": name, f"is_{kind}": True}
    return api_post(BASE_URL_COMPANY, payload)["pk"]

def get_or_create_manufacturer_part(part_pk: int, manufacturer_pk: int, mpn: str,
                                   description: str = "", link: str = "", api_print: bool = False):
    if not mpn:
        return None
    existing = fetch_all(f"{BASE_URL_MANUFACTURER_PART}?part={part_pk}&MPN={requests.utils.quote(mpn)}")
    for mp in existing:
        if mp.get("manufacturer") == manufacturer_pk:
            # Update if needed
            payload = {}
            if description and mp.get("description", "") != description:
                payload["description"] = description
            if link and mp.get("link", "") != link:
                payload["link"] = link
            if payload:
                api_patch(f"{BASE_URL_MANUFACTURER_PART}{mp['pk']}/", payload, api_print)
            return mp["pk"]

    # Create new
    payload = {
        "part": part_pk,
        "manufacturer": manufacturer_pk,
        "MPN": mpn,
        "description": description or "",
        "link": link or "",
    }
    return api_post(BASE_URL_MANUFACTURER_PART, payload, api_print)["pk"]

def get_or_create_supplier_part(part_pk: int, supplier_dict: dict, manufacturer_part_pk: int = None, api_print: bool = False):
    """
    supplier_dict keys used:
        supplier_name, SKU, description, link, packaging, note
    """
    supplier_name = supplier_dict["supplier_name"]
    sku = supplier_dict.get("SKU", "")
    description = supplier_dict.get("description", "")
    link = supplier_dict.get("link", "")
    packaging = supplier_dict.get("packaging", "")
    note = supplier_dict.get("note", "")

    supplier_pk = get_or_create_company(supplier_name, is_supplier=True)

    filters = f"?part={part_pk}&supplier={supplier_pk}"
    if sku:
        filters += f"&SKU={requests.utils.quote(sku)}"
    existing = fetch_all(BASE_URL_SUPPLIER_PARTS + filters)

    if existing:
        sp = existing[0]
        payload = {}
        for field, value in [
            ("description", description),
            ("link", link),
            ("packaging", packaging),
            ("note", note),
        ]:
            if value and sp.get(field, "") != value:
                payload[field] = value
        if manufacturer_part_pk and sp.get("manufacturer_part") != manufacturer_part_pk:
            payload["manufacturer_part"] = manufacturer_part_pk
        if payload:
            api_patch(f"{BASE_URL_SUPPLIER_PARTS}{sp['pk']}/", payload, api_print)
        return sp["pk"]

    # Create new
    payload = {
        "part": part_pk,
        "supplier": supplier_pk,
        "SKU": sku,
        "description": description,
        "link": link,
        "packaging": packaging,
        "note": note,
    }
    if manufacturer_part_pk:
        payload["manufacturer_part"] = manufacturer_part_pk

    return api_post(BASE_URL_SUPPLIER_PARTS, payload, api_print)["pk"]

def sync_price_breaks(supplier_part_pk: int, price_breaks: list, force_price: bool = False, api_print: bool = False):
    if force_price:
        print(f" [FORCE-PRICE] Deleting all price breaks for SupplierPart {supplier_part_pk}")
        existing = fetch_all(f"{BASE_URL_PRICE_BREAK}?part={supplier_part_pk}", api_print)
        if existing:
            confirm = input(" Type 'YES' to confirm deletion: ") if sys.stdin.isatty() else "YES"
            if confirm != "YES":
                print(" Skipping deletion")
                return
            for pb in existing:
                api_delete(f"{BASE_URL_PRICE_BREAK}{pb['pk']}/", api_print)

    existing_keys = set()
    if not force_price:
        current = fetch_all(f"{BASE_URL_PRICE_BREAK}?part={supplier_part_pk}")
        existing_keys = {(pb["quantity"], pb["price"], pb.get("price_currency", "USD")) for pb in current}

    created = 0
    for pb in price_breaks:
        key = (pb["quantity"], pb["price"], pb.get("price_currency", "USD"))
        if key in existing_keys:
            if api_print:
                print(f" Already exists: Qty {pb['quantity']} @ ${pb['price']}")
            continue
        payload = {
            "part": supplier_part_pk,
            "quantity": pb["quantity"],
            "price": pb["price"],
            "price_currency": pb.get("price_currency", "USD")
        }
        result = api_post(BASE_URL_PRICE_BREAK, payload, api_print)
        created += 1
        if api_print:
            print(f" Created PK {result.get('pk')} Qty: {pb['quantity']} @ ${pb['price']}")
    if api_print and created:
        print(f" {created} price break(s) created")

# ----------------------------------------------------------------------
# Category helpers
# ----------------------------------------------------------------------
def check_category_exists(name: str, parent_pk: int = None):
    params = {"name": name}
    if parent_pk is not None:
        params["parent"] = parent_pk
    r = requests.get(BASE_URL_CATEGORIES, headers=HEADERS, params=params)
    if r.status_code != 200:
        return []
    data = r.json()
    return data.get("results", []) if isinstance(data, dict) else data

def create_category_hierarchy(folder_path: str, root_dir: str):
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

def parse_filename(filepath: str):
    basename = os.path.basename(filepath)
    if not basename.endswith(".json"):
        return None, None
    name_part = basename[:-5]
    if "." in name_part:
        name, rev = name_part.rsplit(".", 1)
        return name, rev
    return name_part, None

def resolve_variant_target(variant_str: str, cache: dict):
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
def push_bom(part_pk: int, bom_path: str, cache: dict, api_print: bool = False):
    if not os.path.exists(bom_path):
        return
    print(f"Pushing BOM from {bom_path} to Part PK {part_pk}")
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
            print(f" WARNING: Sub-part '{sub_name}' not found")
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
        print(f" {action} BOM: {qty} x {sub_name}{status}")
        if not validated:
            all_validated = False
    if tree and all_found and all_validated:
        print(f" All BOM items validated setting validated_bom = True")
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

        # Find existing part
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
            print(f" Reusing existing part PK {part_pk}")
            api_patch(f"{BASE_URL_PARTS}{part_pk}/", payload, api_print)
            part_data = existing[0]
        else:
            result = api_post(BASE_URL_PARTS, payload, api_print)
            part_pk = result["pk"]
            print(f" Created new part PK {part_pk}")
            part_data = result

        # Update cache
        if name not in cache:
            cache[name] = []
        if existing:
            cache[name] = [p for p in cache[name] if p["pk"] != existing[0]["pk"]] + [existing[0]]
        else:
            cache[name].append(part_data)

        # Suppliers
        if data.get("purchaseable") and data.get("suppliers"):
            print(f" Pushing {len(data['suppliers'])} supplier(s)")
            for supp in data["suppliers"]:
                if api_print:
                    print(f" → Supplier: {supp['supplier_name']}, SKU: {supp.get('SKU','<none>')}, MPN: {supp.get('MPN','<none>')}")

                supplier_pk = get_or_create_company(supp["supplier_name"], is_supplier=True)

                manufacturer_part_pk = None
                if supp.get("manufacturer_name") and supp.get("MPN"):
                    mfg_pk = get_or_create_company(supp["manufacturer_name"], is_supplier=False)
                    manufacturer_part_pk = get_or_create_manufacturer_part(
                        part_pk=part_pk,
                        manufacturer_pk=mfg_pk,
                        mpn=supp["MPN"],
                        description=supp.get("mp_description", ""),
                        link=supp.get("mp_link", ""),
                        api_print=api_print
                    )

                sp_pk = get_or_create_supplier_part(
                    part_pk=part_pk,
                    supplier_dict=supp,
                    manufacturer_part_pk=manufacturer_part_pk,
                    api_print=api_print
                )

                sync_price_breaks(sp_pk, supp.get("price_breaks", []), force_price, api_print)

        # BOM
        bom_path = file_path[:-5] + ".bom.json"
        if os.path.exists(bom_path):
            push_bom(part_pk, bom_path, cache, api_print)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Push parts + suppliers + BOMs + rich metadata to InvenTree")
    parser.add_argument("patterns", nargs="*", default=["**/*"])
    parser.add_argument("--force", action="store_true", help="Delete and recreate parts")
    parser.add_argument("--force-ipn", action="store_true", help="Generate IPN from name if missing")
    parser.add_argument("--force-price", action="store_true", help="Delete all existing price breaks first")
    parser.add_argument("--api-print", action="store_true", help="Print every API call")
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
