#!/usr/bin/env python3
# file name: json_to_inv-pts.py
# version: 2025-11-18-v7
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
# * .bom.json pushed only if exists
# * pushes suppliers/manufacturers/price breaks if purchaseable
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
import time
from collections import defaultdict
from pathlib import Path
# ----------------------------------------------------------------------
# Sanitize company name for filename & JSON
# ----------------------------------------------------------------------
def sanitize_company_name(name):
    """Replace spaces with _, remove dots, and strip invalid filename chars."""
    print(f"DEBUG: Sanitizing company name: {name}")
    sanitized = name.replace(' ', '_').replace('.', '')
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', sanitized.strip())
    print(f"DEBUG: Sanitized -> {sanitized}")
    return sanitized
# ----------------------------------------------------------------------
# API endpoints
# ----------------------------------------------------------------------
BASE_URL = os.getenv("INVENTREE_URL")
if BASE_URL:
    BASE_URL = BASE_URL.rstrip("/")
    BASE_URL_PARTS = f"{BASE_URL}/api/part/"
    BASE_URL_CATEGORIES = f"{BASE_URL}/api/part/category/"
    BASE_URL_BOM = f"{BASE_URL}/api/bom/"
    BASE_URL_STOCK = f"{BASE_URL}/api/stock/"
    BASE_URL_TEST = f"{BASE_URL}/api/part/test-template/"
    BASE_URL_BUILD = f"{BASE_URL}/api/build/"
    BASE_URL_SALES = f"{BASE_URL}/api/sales/order/"
    BASE_URL_ATTACHMENTS = f"{BASE_URL}/api/part/attachment/"
    BASE_URL_PARAMETERS = f"{BASE_URL}/api/part/parameter/"
    BASE_URL_RELATED = f"{BASE_URL}/api/part/related/"
    BASE_URL_COMPANY = f"{BASE_URL}/api/company/"
    BASE_URL_SUPPLIER_PARTS = f"{BASE_URL}/api/company/part/"
    BASE_URL_MANUFACTURER_PART = f"{BASE_URL}/api/company/part/manufacturer/"
    BASE_URL_PRICE_BREAK = f"{BASE_URL}/api/company/price-break/"
    WEB_BASE = BASE_URL.rsplit('/api', 1)[0]
else:
    BASE_URL_PARTS = BASE_URL_CATEGORIES = BASE_URL_BOM = None
    BASE_URL_STOCK = BASE_URL_BUILD = BASE_URL_SALES = BASE_URL_ATTACHMENTS = None
    BASE_URL_PARAMETERS = BASE_URL_RELATED = None
    BASE_URL_COMPANY = BASE_URL_SUPPLIER_PARTS = BASE_URL_MANUFACTURER_PART = BASE_URL_PRICE_BREAK = None
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
# ----------------------------------------------------------------------
# Fetch data (handles pagination)
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
        elif isinstance(data, dict):
            items.append(data)
            url = None
        elif isinstance(data, list):
            items.extend(data)
            url = None
        else:
            raise Exception("Unexpected data type from API")
    return items
# ----------------------------------------------------------------------
# Category existence
# ----------------------------------------------------------------------
def check_category_exists(name, parent_pk=None):
    params = {"name": name}
    if parent_pk is not None:
        params["parent"] = parent_pk
    try:
        r = requests.get(BASE_URL_CATEGORIES, headers=HEADERS, params=params)
        if r.status_code != 200:
            return []
        data = r.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        return results
    except:
        return []
# ----------------------------------------------------------------------
# Part existence (using cache)
# ----------------------------------------------------------------------
def check_part_exists(cache, name, revision=None, ipn=None):
    print(f"DEBUG: Searching cache for part '{name}' rev '{revision}' (IPN={ipn})")
    candidates = cache.get(name, [])
    print(f"DEBUG: Found {len(candidates)} candidates with name '{name}'")
    results = []
    for res in candidates:
        if (revision is None or res.get('revision') == revision) and (ipn is None or res.get('IPN') == ipn):
            results.append(res)
            print(f"DEBUG: Match PK {res['pk']}: name='{res['name']}', revision='{res.get('revision', '')}', IPN='{res.get('IPN', '')}'")
    print(f"DEBUG: Found {len(results)} matches")
    return results
# ----------------------------------------------------------------------
# Dependency handling
# ----------------------------------------------------------------------
def check_dependencies(part_pk):
    deps = {
        "stock": [], "bom": [], "test": [], "build": [], "sales": [],
        "attachments": [], "parameters": [], "related": []
    }
    for endpoint, key in [
        (BASE_URL_STOCK, "stock"), (BASE_URL_BOM, "bom"), (BASE_URL_TEST, "test"),
        (BASE_URL_BUILD, "build"), (BASE_URL_SALES, "sales"),
        (BASE_URL_ATTACHMENTS, "attachments"), (BASE_URL_PARAMETERS, "parameters"),
        (BASE_URL_RELATED, "related"),
    ]:
        try:
            r = requests.get(f"{endpoint}?part={part_pk}", headers=HEADERS)
            if r.status_code == 200:
                js = r.json()
                cnt = js.get("count", len(js)) if isinstance(js, dict) else len(js)
                if cnt:
                    deps[key] = js.get("results", js)
        except:
            pass
    return deps
def delete_dependencies(part_name, part_pk, clean):
    if not clean:
        return False
    deps = check_dependencies(part_pk)
    total = sum(len(v) for v in deps.values())
    if total == 0:
        return True
    print(f"WARNING: {total} dependencies for '{part_name}' (PK {part_pk})")
    if input(f"Type 'YES' to delete {total} deps: ") != "YES":
        return False
    if input(f"Type 'CONFIRM' to PERMANENTLY delete: ") != "CONFIRM":
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
                requests.delete(url, headers=HEADERS)
            except:
                pass
    return True
def delete_part(cache, part_name, part_pk, clean_deps):
    print(f"DEBUG: Deleting part '{part_name}' (PK {part_pk})")
    if not delete_dependencies(part_name, part_pk, clean_deps):
        raise Exception("Dependencies block deletion")
    try:
        requests.patch(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS, json={"active": False})
    except:
        pass
    try:
        r = requests.delete(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS)
        if r.status_code != 204:
            raise Exception(f"Delete failed: {r.text}")
    except:
        pass
    # Remove from cache
    if part_name in cache:
        cache[part_name] = [p for p in cache[part_name] if p['pk'] != part_pk]
# ----------------------------------------------------------------------
# Category hierarchy – folder-based
# ----------------------------------------------------------------------
def create_category_hierarchy(folder_path, start_dir, parent_pk=None):
    parts = os.path.relpath(folder_path, start_dir).split(os.sep)
    cur = parent_pk
    for name in parts:
        if name == "." or not name:
            continue
        existing = check_category_exists(name, cur)
        if existing:
            cur = existing[0]["pk"]
            continue
        payload = {"name": name, "parent": cur}
        try:
            r = requests.post(BASE_URL_CATEGORIES, headers=HEADERS, json=payload)
            if r.status_code != 201:
                raise Exception(f"Create category failed: {r.text}")
            cur = r.json()["pk"]
        except Exception as e:
            raise Exception(f"Network error creating category {name}: {e}")
    return cur
# ----------------------------------------------------------------------
# Parse filename -> name + revision (revision None if no .)
# ----------------------------------------------------------------------
def parse_filename(filepath):
    basename = os.path.basename(filepath)
    if not basename.endswith(".json"):
        return None, None
    name_part = basename[:-5] # remove .json
    if "." in name_part:
        name, rev = name_part.rsplit(".", 1)
        return name, rev
    else:
        return name_part, None
# ----------------------------------------------------------------------
# Push one part
# ----------------------------------------------------------------------
def push_part(part_path, force_ipn=False, force=False, clean=False, force_price=False, level_dir=None, cache=None):
    print(f"DEBUG: Pushing {part_path}")
    name, rev_from_file = parse_filename(part_path)
    if not name:
        print("DEBUG: Invalid filename - skipping")
        return
    try:
        with open(part_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"DEBUG: JSON error: {e}")
        return
    if isinstance(data, list):
        data = data[0]
    revision = rev_from_file if rev_from_file is not None else data.get("revision", "")
    # Build payload
    allowed = [
        "name", "description", "IPN", "keywords", "units",
        "minimum_stock", "assembly", "component", "trackable",
        "purchaseable", "salable", "virtual", "is_template"
    ]
    payload = {k: data.get(k) for k in allowed if k in data}
    if not payload.get("name"):
        print("DEBUG: No name – skipping")
        return
    # Override name
    payload["name"] = name
    payload["active"] = True
    if revision:
        payload["revision"] = revision
    # Force IPN
    ipn = payload.get("IPN")
    if force_ipn and (not ipn or ipn.strip() == ""):
        ipn = name[:50]
        payload["IPN"] = ipn
        print(f"DEBUG: Generated IPN -> {ipn}")
    # Folder-based category
    folder = os.path.dirname(part_path)
    cat_pk = create_category_hierarchy(folder, level_dir)
    payload["category"] = cat_pk
    # Handle variant_of_name
    variant_of_name = data.get("variant_of_name")
    if variant_of_name:
        variant_existing = check_part_exists(cache, variant_of_name)
        if variant_existing:
            payload["variant_of"] = variant_existing[0]["pk"]
        else:
            print(f"WARNING: Variant parent '{variant_of_name}' not found - skipping variant_of")
    print(f"DEBUG: Payload -> {payload}")
    # Check existence
    existing = check_part_exists(cache, name, revision if revision else None, ipn)
    if existing and force:
        for p in existing:
            print(f"DEBUG: --force: deleting existing part PK {p['pk']}")
            delete_part(cache, p["name"], p["pk"], clean)
        new_pk = None
    elif existing:
        print(f"DEBUG: Part '{name}' rev '{revision}' exists - using PK {existing[0]['pk']}")
        new_pk = existing[0]['pk']
        # Optionally update part details if needed
        # For now, skip updating part, but proceed to suppliers/price
    else:
        # Create part
        try:
            r = requests.post(BASE_URL_PARTS, headers=HEADERS, json=payload)
            if r.status_code != 201:
                raise Exception(f"Create failed: {r.text}")
            new = r.json()
            new_pk = new['pk']
            print(f"DEBUG: Created '{new['name']}' rev '{new.get('revision', '')}' (PK {new_pk})")
            # Add to cache
            cache[new['name']].append(new)
        except Exception as e:
            print(f"ERROR: {e}")
            return
        # Verify the part exists with retry
        verified = False
        for attempt in range(3):
            verify_r = requests.get(f"{BASE_URL_PARTS}{new_pk}/", headers=HEADERS)
            if verify_r.status_code == 200:
                verified = True
                break
            print(f"DEBUG: Verify attempt {attempt+1} failed for Part {new_pk}: {verify_r.status_code}")
            time.sleep(1)
        if not verified:
            print(f"ERROR: Part {new_pk} not found after creation and retries.")
            sys.exit(1)
        print(f"DEBUG: Part {new_pk} verified.")
    if new_pk is None:
        return  # If deleted and not recreated yet, but since we deleted and then create in the else, it should be fine
    # Push suppliers if purchaseable
    if data.get("purchaseable", False):
        suppliers = data.get("suppliers", [])
        for supplier in suppliers:
            raw_supplier_name = supplier.get("supplier_name")
            if not raw_supplier_name:
                print(f"ERROR: Missing supplier name for part {name}")
                sys.exit(1)
            supplier_name = sanitize_company_name(raw_supplier_name)
            # Check supplier exists
            sup_params = {"name": supplier_name, "is_supplier": True}
            sup_r = requests.get(BASE_URL_COMPANY, headers=HEADERS, params=sup_params)
            if sup_r.status_code != 200:
                print(f"ERROR: Failed to search for supplier {supplier_name}")
                sys.exit(1)
            sup_data = sup_r.json()
            sup_results = sup_data.get("results", []) if isinstance(sup_data, dict) else sup_data
            sup_results = [s for s in sup_results if s['name'] == supplier_name]
            if not sup_results:
                print(f"ERROR: Supplier '{supplier_name}' not found in the system")
                sys.exit(1)
            supplier_pk = sup_results[0]["pk"]
            # Check manufacturer if present
            mp_pk = None
            if "manufacturer_name" in supplier:
                raw_man_name = supplier["manufacturer_name"]
                if not raw_man_name:
                    print(f"ERROR: Missing manufacturer name for supplier {supplier_name} in part {name}")
                    sys.exit(1)
                man_name = sanitize_company_name(raw_man_name)
                man_params = {"name": man_name, "is_manufacturer": True}
                man_r = requests.get(BASE_URL_COMPANY, headers=HEADERS, params=man_params)
                if man_r.status_code != 200:
                    print(f"ERROR: Failed to search for manufacturer {man_name}")
                    sys.exit(1)
                man_data = man_r.json()
                man_results = man_data.get("results", []) if isinstance(man_data, dict) else man_data
                man_results = [m for m in man_results if m['name'] == man_name]
                if not man_results:
                    print(f"ERROR: Manufacturer '{man_name}' not found in the system")
                    sys.exit(1)
                man_pk = man_results[0]["pk"]
                # Create ManufacturerPart
                mp_payload = {
                    "part": new_pk,
                    "manufacturer": man_pk,
                    "MPN": supplier.get("MPN", ""),
                    "description": supplier.get("mp_description", ""),
                    "link": supplier.get("mp_link", "")
                }
                mp_r = requests.post(BASE_URL_MANUFACTURER_PART, headers=HEADERS, json=mp_payload)
                if mp_r.status_code != 201:
                    print(f"ERROR: Failed to create ManufacturerPart for {man_name}: {mp_r.text}")
                    sys.exit(1)
                mp_pk = mp_r.json()["pk"]
            # Create SupplierPart
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
            sp_r = requests.post(BASE_URL_SUPPLIER_PARTS, headers=HEADERS, json=sp_payload)
            if sp_r.status_code != 201:
                print(f"ERROR: Failed to create SupplierPart for {supplier_name}: {sp_r.text}")
                sys.exit(1)
            sp_pk = sp_r.json()["pk"]
            # Verify the supplier part exists with retry
            sp_verified = False
            for attempt in range(3):
                verify_sp = requests.get(f"{BASE_URL_SUPPLIER_PARTS}{sp_pk}/", headers=HEADERS)
                if verify_sp.status_code == 200:
                    sp_verified = True
                    break
                print(f"DEBUG: Verify attempt {attempt+1} failed for SupplierPart {sp_pk}: {verify_sp.status_code}")
                time.sleep(1)
            if not sp_verified:
                print(f"ERROR: SupplierPart {sp_pk} not found after creation and retries.")
                sys.exit(1)
            print(f"DEBUG: SupplierPart {sp_pk} verified.")
            # Fetch existing price breaks
            existing_pbs = fetch_data(BASE_URL_PRICE_BREAK, params={"supplier_part": sp_pk})
            if force_price:
                for pb in existing_pbs:
                    requests.delete(f"{BASE_URL_PRICE_BREAK}{pb['pk']}/", headers=HEADERS)
                print(f"DEBUG: Deleted all existing price breaks for SupplierPart {sp_pk}")
                existing_by_quantity = {}
            else:
                existing_by_quantity = {pb['quantity']: pb for pb in existing_pbs}
            # De-duplicate input price breaks
            unique_pbs = {}
            for pb in supplier.get("price_breaks", []):
                q = pb.get("quantity", 0)
                if q not in unique_pbs:
                    unique_pbs[q] = pb
                else:
                    print(f"DEBUG: Duplicate quantity {q} in input data for SupplierPart {sp_pk}, keeping first.")
            # Create or update price breaks
            for q, pb in unique_pbs.items():
                json_price = pb.get("price", 0.0)
                json_currency = pb.get("price_currency", "")
                if q in existing_by_quantity:
                    existing_pb = existing_by_quantity[q]
                    print(f"DEBUG: Existing quantity {q} for SupplierPart {sp_pk}, existing price: {existing_pb['price']} {existing_pb['price_currency']}")
                    if existing_pb['price'] != json_price or existing_pb['price_currency'] != json_currency:
                        pb_update_payload = {
                            "price": json_price,
                            "price_currency": json_currency
                        }
                        pb_update_r = requests.patch(f"{BASE_URL_PRICE_BREAK}{existing_pb['pk']}/", headers=HEADERS, json=pb_update_payload)
                        if pb_update_r.status_code != 200:
                            print(f"ERROR: Failed to update price break: {pb_update_r.text}")
                            sys.exit(1)
                        print(f"DEBUG: Updated quantity {q} for SupplierPart {sp_pk}, new price: {json_price} {json_currency}")
                    else:
                        print(f"DEBUG: Skipping matching quantity {q} for SupplierPart {sp_pk}")
                    continue
                pb_payload = {
                    "supplier_part": sp_pk,
                    "quantity": q,
                    "price": json_price,
                    "price_currency": json_currency
                }
                pb_r = requests.post(BASE_URL_PRICE_BREAK, headers=HEADERS, json=pb_payload)
                if pb_r.status_code != 201:
                    print(f"ERROR: Failed to create price break: {pb_r.text}")
                    sys.exit(1)
                print(f"DEBUG: Created quantity {q} for SupplierPart {sp_pk}, price: {json_price} {json_currency}")
    # Push BOM if exists
    base = part_path[:-5]
    bom_path = base + ".bom.json"
    if os.path.exists(bom_path):
        print(f"DEBUG: Pushing BOM from {bom_path}")
        push_bom(new_pk, bom_path, cache=cache)
    else:
        print(f"DEBUG: No .bom.json for {name} - skipping BOM")
# ----------------------------------------------------------------------
# Single-level BOM push with retry
# ----------------------------------------------------------------------
def push_bom(parent_pk: int, bom_path: str, level: int = 0, cache=None):
    indent = " " * level
    try:
        with open(bom_path, "r", encoding="utf-8") as f:
            tree = json.load(f)
    except Exception as e:
        print(f"{indent}ERROR: Failed to read BOM: {e}")
        return
    # Fetch all existing BOM lines for the parent once
    existing_boms = fetch_data(f"{BASE_URL_BOM}?part={parent_pk}")
    for node in tree:
        qty = node.get("quantity", 1)
        note = node.get("note", "")
        sub = node["sub_part"]
        sub_name = sub["name"]
        sub_ipn = sub.get("IPN", "")
        sub_parts = check_part_exists(cache, sub_name, None, sub_ipn if sub_ipn else None)
        if not sub_parts:
            print(f"{indent}WARNING: Sub-part '{sub_name}' not found – skipping")
            continue
        if len(sub_parts) > 1:
            print(f"{indent}WARNING: Multiple ({len(sub_parts)}) exact matches for sub-part '{sub_name}' – picking first PK {sub_parts[0]['pk']}")
        sub_pk = sub_parts[0]["pk"]
        # Check for existing BOM line locally
        existing = [b for b in existing_boms if b['sub_part'] == sub_pk]
        payload = {
            "part": parent_pk,
            "sub_part": sub_pk,
            "quantity": qty,
            "note": note,
        }
        def try_post_bom(attempt=1):
            if existing:
                bom_pk = existing[0]["pk"]
                r = requests.patch(f"{BASE_URL_BOM}{bom_pk}/", headers=HEADERS, json=payload)
                action = "UPDATED"
            else:
                r = requests.post(BASE_URL_BOM, headers=HEADERS, json=payload)
                action = "CREATED"
            if r.status_code in (200, 201):
                print(f"{indent}{action} BOM: {qty} × {sub_name} (sub_pk {sub_pk})")
                # Update existing_boms if created new
                if action == "CREATED":
                    existing_boms.append(r.json())
                return True
            else:
                err = r.json()
                if "part" in err and "object does not exist" in str(err["part"]):
                    if attempt < 3:
                        print(f"{indent}Retrying BOM line (attempt {attempt + 1})...")
                        input("Press enter to retry...")
                        return try_post_bom(attempt + 1)
                print(f"{indent}ERROR: BOM line failed: {r.text}")
                return False
        try_post_bom()
# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Push all parts from data/pts/<level>/ to InvenTree, level by level"
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns (default: all under data/pts)"
    )
    parser.add_argument("--force-ipn", action="store_true",
                        help="Generate IPN from name when missing")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing part (name+revision) before push")
    parser.add_argument("--clean-dependencies", action="store_true",
                        help="Delete dependencies (requires two confirmations)")
    parser.add_argument("--force-price", action="store_true",
                        help="Delete existing price breaks before pushing new ones")
    args = parser.parse_args()
    if not TOKEN:
        raise Exception("INVENTREE_TOKEN not set")
    if not BASE_URL:
        raise Exception("INVENTREE_URL not set")
    root = "data/pts"
    if not os.path.isdir(root):
        raise FileNotFoundError(f"{root} missing")
    # Fetch all existing parts for cache
    print("DEBUG: Fetching all existing parts for cache...")
    all_parts = fetch_data(BASE_URL_PARTS)
    cache = defaultdict(list)
    for part in all_parts:
        cache[part['name']].append(part)
    print(f"DEBUG: Cached {len(all_parts)} parts")
    # Collect files
    matched_files = []
    if args.patterns:
        for pat in args.patterns:
            no_rev_pat = os.path.join(root, "**/" + pat + ".json")
            matched_files.extend(glob.glob(no_rev_pat, recursive=True))
            rev_pat = os.path.join(root, "**/" + pat + ".*.json")
            matched_files.extend(glob.glob(rev_pat, recursive=True))
    else:
        matched_files = glob.glob(os.path.join(root, "**/*.json"), recursive=True)
    files = sorted(set(f for f in matched_files if os.path.basename(f) != "category.json" and not f.endswith(".bom.json")))
    print(f"DEBUG: {len(files)} part files to process")
    # Get levels
    all_levels = set()
    for f in files:
        rel = os.path.relpath(f, root)
        level_str = rel.split(os.sep)[0]
        if level_str.isdigit() and int(level_str) > 0:
            all_levels.add(int(level_str))
    levels = sorted(all_levels)
    for level in levels:
        print(f"Processing level {level}")
        level_dir = os.path.join(root, str(level))
        level_files = [f for f in files if os.path.relpath(f, root).startswith(str(level) + os.sep)]
        # Build key_to_files for conflict check
        key_to_files = defaultdict(list)
        for f in level_files:
            name, rev_from_file = parse_filename(f)
            if not name: continue
            rel_dir = os.path.relpath(os.path.dirname(f), level_dir)
            key = os.path.join(rel_dir, name).replace("\\", "/")
            key_to_files[key].append((f, rev_from_file))
        # Check for conflicts
        for key, flist in key_to_files.items():
            if len(flist) > 1:
                files_str = ", ".join(os.path.basename(ff) for ff, _ in flist)
                print(f"WARNING for level {level} {key}: multiple files: {files_str}. Processing anyway.")
        for key, flist in key_to_files.items():
            for f, rev_from_file in flist:
                push_part(f, args.force_ipn, args.force, args.clean_dependencies, args.force_price, level_dir, cache)
if __name__ == "__main__":
    main()
