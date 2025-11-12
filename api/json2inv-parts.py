#!/usr/bin/env python3
# file name: json2inv-parts.py
# version: 2025-11-12-v3
# --------------------------------------------------------------
# Import parts from data/parts -> InvenTree.
# * Folder structure -> category hierarchy
# * Supports revision in filename: Part_Name.revision.json
# * --force-ipn -> generate IPN from name when missing
# * --force -> delete existing part by **name + revision**
# * --clean-dependencies -> delete dependencies (BOM, stock, etc.)
# --------------------------------------------------------------
# Example usage:
# python3 ./api/json2inv-parts.py "Electronics/Passives/Capacitors/C_*" --force-ipn --force --clean-dependencies
# python3 ./api/json2inv-parts.py "Paint/Yellow_Paint" --force-ipn
# python3 ./api/json2inv-parts.py # Imports all parts
# python3 ./api/json2inv-parts.py "**/*" --force-ipn --force
# --------------------------------------------------------------
# File Structure of dev data after running with "*_Top":
# data/parts/
# +-- Furniture/
# ¦ +-- Tables/
# ¦ ¦ +-- Round_Top.[version.]json
# ¦ ¦ +-- Square_Top.[version.]json
# ¦ +-- category.json
# +-- category.json
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
# Part existence (by name + revision + optional IPN)
# ----------------------------------------------------------------------
def check_part_exists(name, revision, ipn=None):
    print(f"DEBUG: Global search for part '{name}' rev '{revision}' (IPN={ipn})")
    params = {"name": name}
    if revision:
        params["revision"] = revision
    if ipn:
        params["IPN"] = ipn
    try:
        r = requests.get(BASE_URL_PARTS, headers=HEADERS, params=params)
        if r.status_code != 200:
            return []
        data = r.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        if results:
            print(f"DEBUG: Found {len(results)} matches")
        return results
    except:
        return []
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
def delete_part(part_name, part_pk, clean_deps):
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
# ----------------------------------------------------------------------
# Category hierarchy – folder-based
# ----------------------------------------------------------------------
def create_category_hierarchy(folder_path, parent_pk=None):
    parts = os.path.relpath(folder_path, "data/parts").split(os.sep)
    cur = parent_pk
    for name in parts:
        if name == ".":
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
# Parse filename -> name + revision
# ----------------------------------------------------------------------
def parse_filename(filepath):
    basename = os.path.basename(filepath)
    if not basename.endswith(".json"):
        return None, None
    name_part = basename[:-5] # remove .json
    revision = ""
    if "." in name_part:
        name_part, revision = name_part.split(".", 1)
    return name_part, revision
# ----------------------------------------------------------------------
# Import one part
# ----------------------------------------------------------------------
def import_part(part_path, force_ipn=False, force=False, clean=False):
    print(f"DEBUG: Importing {part_path}")
    name, revision = parse_filename(part_path)
    if not name:
        print("DEBUG: Invalid filename – skipping")
        return
    try:
        with open(part_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"DEBUG: JSON error: {e}")
        return
    if isinstance(data, list):
        data = data[0]
    # Build payload
    allowed = [
        "name", "description", "IPN", "revision", "keywords",
        "barcode", "minimum_stock", "units", "assembly", "component",
        "trackable", "purchaseable", "salable", "virtual", "active"
    ]
    payload = {k: data.get(k) for k in allowed if k in data}
    if not payload.get("name"):
        print("DEBUG: No name – skipping")
        return
    # Override with filename-derived name/revision
    payload["name"] = name
    payload["revision"] = revision
    payload["active"] = True
    # Force IPN
    ipn = payload.get("IPN")
    if force_ipn and (not ipn or ipn.strip() == ""):
        ipn = name[:50]
        payload["IPN"] = ipn
        print(f"DEBUG: Generated IPN -> {ipn}")
    # Folder-based category
    folder = os.path.dirname(part_path)
    cat_pk = create_category_hierarchy(folder)
    payload["category"] = cat_pk
    print(f"DEBUG: Payload -> {payload}")
    # Check existence (name + revision + IPN)
    existing = check_part_exists(name, revision, ipn)
    if existing and force:
        for p in existing:
            print(f"DEBUG: --force: deleting existing part PK {p['pk']}")
            delete_part(p["name"], p["pk"], clean)
    elif existing:
        print(f"DEBUG: Part '{name}' rev '{revision}' exists – skipping")
        return
    # Create part
    try:
        r = requests.post(BASE_URL_PARTS, headers=HEADERS, json=payload)
        if r.status_code != 201:
            raise Exception(f"Create failed: {r.text}")
        new = r.json()
        new_pk = new['pk']
        print(f"DEBUG: Created '{new['name']}' rev '{new.get('revision', '')}' (PK {new_pk})")
    except Exception as e:
        print(f"ERROR: {e}")
        return
    # Import suppliers
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
        # Create price breaks
        for pb in supplier.get("price_breaks", []):
            pb_payload = {
                "part": new_pk,
                "supplier": supplier_pk,
                "quantity": pb.get("quantity", 0),
                "price": pb.get("price", 0.0),
                "price_currency": pb.get("price_currency", "")
            }
            pb_r = requests.post(BASE_URL_PRICE_BREAK, headers=HEADERS, json=pb_payload)
            if pb_r.status_code != 201:
                print(f"ERROR: Failed to create price break: {pb_r.text}")
                sys.exit(1)
# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Import parts from data/parts -> InvenTree (with revision support)"
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns (default: all under data/parts)"
    )
    parser.add_argument("--force-ipn", action="store_true",
                        help="Generate IPN from name when missing")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing part (name+revision) before import")
    parser.add_argument("--clean-dependencies", action="store_true",
                        help="Delete dependencies (requires two confirmations)")
    args = parser.parse_args()
    if not TOKEN:
        raise Exception("INVENTREE_TOKEN not set")
    if not BASE_URL:
        raise Exception("INVENTREE_URL not set")
    root = "data/parts"
    if not os.path.isdir(root):
        raise FileNotFoundError(f"{root} missing")
    # Collect files
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
    print(f"DEBUG: {len(files)} part files to process")
    for key, flist in key_to_files.items():
        for f, rev in flist:
            import_part(f, args.force_ipn, args.force, args.clean_dependencies)
if __name__ == "__main__":
    main()
