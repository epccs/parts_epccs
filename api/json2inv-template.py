#!/usr/bin/env python3
# file name: json2inv-template.py
# version: 2025-11-13-v1
# --------------------------------------------------------------
# Import **template** parts + single-level BOM from data/templates/ -> InvenTree
#
# * Folder structure -> category hierarchy
# * Supports: Part_Name[.revision].json + Part_Name[.revision].bom.json
# * Creates part **first**, then imports BOM with **retry + manual input**
# * --force-ipn -> generate IPN from name when missing
# * --force -> delete existing template (name + revision)
# * --clean-dependencies -> delete BOM/stock/etc. (with confirmation)
# * .bom.json imported **only if exists**
# * imports suppliers/manufacturers/price breaks like parts
#
# example usage:
# python3 ./api/json2inv-template.py "Furniture/Tables/*_Table.json"
# python3 ./api/json2inv-template.py "**/*.json" --force --clean-dependencies
# --------------------------------------------------------------
# File Structure of dev data after running with "Round_Table":
# data/templates/
# +-- Furniture/
# ¦ +-- Tables/
# ¦ ¦ +-- Round_Table.[version.]json
# ¦ ¦ +-- [Round_Table.[version.]bom.json] (if BOM exists)
# ¦ +-- category.json
# +-- category.json
# --------------------------------------------------------------
import requests
import json
import os
import glob
import re
import argparse
from pathlib import Path
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
    raise RuntimeError("INVENTREE_URL not set")
TOKEN = os.getenv("INVENTREE_TOKEN")
if not TOKEN:
    raise RuntimeError("INVENTREE_TOKEN not set")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
# ----------------------------------------------------------------------
# Sanitize company name
# ----------------------------------------------------------------------
def sanitize_company_name(name):
    sanitized = name.replace(' ', '_').replace('.', '')
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', sanitized.strip())
    return sanitized
# ----------------------------------------------------------------------
# Category helpers
# ----------------------------------------------------------------------
def category_exists(name: str, parent_pk: int | None = None):
    params = {"name": name}
    if parent_pk is not None:
        params["parent"] = parent_pk
    r = requests.get(BASE_URL_CATEGORIES, headers=HEADERS, params=params)
    if r.status_code != 200:
        return None
    data = r.json()
    results = data.get("results", data) if isinstance(data, dict) else data
    return results[0] if results else None
def create_category(name: str, parent_pk: int | None = None):
    payload = {"name": name}
    if parent_pk is not None:
        payload["parent"] = parent_pk
    r = requests.post(BASE_URL_CATEGORIES, headers=HEADERS, json=payload)
    if r.status_code != 201:
        raise RuntimeError(f"Create category failed: {r.text}")
    return r.json()["pk"]
def build_category_from_path(folder_path: str) -> int:
    rel = os.path.relpath(folder_path, "data/templates")
    parts = [p for p in rel.split(os.sep) if p and p != "."]
    cur_pk = None
    for name in parts:
        existing = category_exists(name, cur_pk)
        cur_pk = existing["pk"] if existing else create_category(name, cur_pk)
    return cur_pk
# ----------------------------------------------------------------------
# Part existence (by name + revision + IPN)
# ----------------------------------------------------------------------
def part_exists(name: str, revision: str, ipn: str | None = None):
    params = {"name": name}
    if revision:
        params["revision"] = revision
    if ipn:
        params["IPN"] = ipn
    r = requests.get(BASE_URL_PARTS, headers=HEADERS, params=params)
    if r.status_code != 200:
        return []
    data = r.json()
    results = data.get("results", data) if isinstance(data, dict) else data
    return results
# ----------------------------------------------------------------------
# Dependency handling
# ----------------------------------------------------------------------
def check_dependencies(part_pk: int):
    deps = {}
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
def delete_dependencies(part_name: str, part_pk: int, clean: bool):
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
def delete_part(part_name: str, part_pk: int, clean_deps: bool):
    if not delete_dependencies(part_name, part_pk, clean_deps):
        raise RuntimeError("Dependencies block deletion")
    try:
        requests.patch(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS, json={"active": False})
    except:
        pass
    r = requests.delete(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS)
    if r.status_code != 204:
        raise RuntimeError(f"DELETE part failed: {r.text}")
# ----------------------------------------------------------------------
# Parse filename -> name + revision
# ----------------------------------------------------------------------
def parse_filename(filepath):
    basename = os.path.basename(filepath)
    if not basename.endswith(".json"):
        return None, None
    name_part = basename[:-5]
    revision = ""
    if "." in name_part:
        name_part, revision = name_part.rsplit(".", 1)
    return name_part, revision
# ----------------------------------------------------------------------
# Import one template part + BOM + suppliers
# ----------------------------------------------------------------------
def import_template_part(part_path: str, force_ipn: bool, force: bool, clean: bool):
    print(f"DEBUG: Importing template: {part_path}")
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
    payload = {k: data.get(k) for k in allowed if data.get(k) is not None}
    payload["name"] = name
    payload["revision"] = revision
    payload["is_template"] = True
    payload["active"] = True
    # Force IPN
    ipn = payload.get("IPN")
    if force_ipn and (not ipn or ipn.strip() == ""):
        ipn = name[:50]
        payload["IPN"] = ipn
        print(f"DEBUG: Generated IPN -> {ipn}")
    # Folder-based category
    folder = os.path.dirname(part_path)
    cat_pk = build_category_from_path(folder)
    payload["category"] = cat_pk
    print(f"DEBUG: Payload -> {payload}")
    # Check existence
    existing = part_exists(name, revision, ipn)
    if existing:
        if force:
            for p in existing:
                print(f"DEBUG: --force: deleting existing PK {p['pk']}")
                delete_part(p["name"], p["pk"], clean)
        else:
            print(f"DEBUG: Template '{name}' rev '{revision}' exists – skipping")
            return
    # CREATE PART FIRST
    try:
        r = requests.post(BASE_URL_PARTS, headers=HEADERS, json=payload)
        if r.status_code != 201:
            raise RuntimeError(f"Create failed: {r.text}")
        new = r.json()
        part_pk = new["pk"]
        print(f"DEBUG: Created '{name}' rev '{revision}' (PK {part_pk})")
        print(f"Part created at: {BASE_URL}/web/part/{part_pk}/details")
    except Exception as e:
        raise RuntimeError(f"Failed to create template: {e}")
    # IMPORT SUPPLIERS/MANUFACTURERS/PRICE BREAKS
    suppliers = data.get("suppliers", [])
    for supplier in suppliers:
        supplier_name = supplier.get("supplier_name")
        if not supplier_name:
            print(f"ERROR: Missing supplier name for template {name}")
            continue
        # Check supplier exists
        sup_params = {"name": supplier_name, "is_supplier": True}
        sup_r = requests.get(BASE_URL_COMPANY, headers=HEADERS, params=sup_params)
        if sup_r.status_code != 200:
            print(f"ERROR: Failed to search for supplier {supplier_name}")
            continue
        sup_data = sup_r.json()
        sup_results = sup_data.get("results", []) if isinstance(sup_data, dict) else sup_data
        if not sup_results:
            print(f"ERROR: Supplier '{supplier_name}' not found in the system")
            continue
        supplier_pk = sup_results[0]["pk"]
        # Check manufacturer if present
        mp_pk = None
        if "manufacturer_name" in supplier:
            man_name = supplier["manufacturer_name"]
            if not man_name:
                print(f"ERROR: Missing manufacturer name for supplier {supplier_name} in template {name}")
                continue
            man_params = {"name": man_name, "is_manufacturer": True}
            man_r = requests.get(BASE_URL_COMPANY, headers=HEADERS, params=man_params)
            if man_r.status_code != 200:
                print(f"ERROR: Failed to search for manufacturer {man_name}")
                continue
            man_data = man_r.json()
            man_results = man_data.get("results", []) if isinstance(man_data, dict) else man_data
            if not man_results:
                print(f"ERROR: Manufacturer '{man_name}' not found in the system")
                continue
            man_pk = man_results[0]["pk"]
            # Create ManufacturerPart
            mp_payload = {
                "part": part_pk,
                "manufacturer": man_pk,
                "MPN": supplier.get("MPN", ""),
                "description": supplier.get("mp_description", ""),
                "link": supplier.get("mp_link", "")
            }
            mp_r = requests.post(BASE_URL_MANUFACTURER_PART, headers=HEADERS, json=mp_payload)
            if mp_r.status_code != 201:
                print(f"ERROR: Failed to create ManufacturerPart for {man_name}: {mp_r.text}")
                continue
            mp_pk = mp_r.json()["pk"]
        # Create SupplierPart
        sp_payload = {
            "part": part_pk,
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
            continue
        sp_pk = sp_r.json()["pk"]
        # Create price breaks
        for pb in supplier.get("price_breaks", []):
            pb_payload = {
                "part": sp_pk,
                "quantity": pb.get("quantity", 0),
                "price": pb.get("price", 0.0),
                "price_currency": pb.get("price_currency", "")
            }
            pb_r = requests.post(BASE_URL_PRICE_BREAK, headers=HEADERS, json=pb_payload)
            if pb_r.status_code != 201:
                print(f"ERROR: Failed to create price break: {pb_r.text}")
    # IMPORT BOM (only if exists)
    bom_path = Path(part_path).with_name(f"{name}{f'.{revision}' if revision else ''}.bom.json")
    if bom_path.is_file():
        print(f"DEBUG: Importing BOM from {bom_path}")
        import_bom(part_pk, bom_path)
    else:
        print(f"DEBUG: No .bom.json for {name} - skipping BOM")
# ----------------------------------------------------------------------
# Single-level BOM import with retry
# ----------------------------------------------------------------------
def import_bom(parent_pk: int, bom_path: Path, level: int = 0):
    indent = " " * level
    try:
        with open(bom_path, "r", encoding="utf-8") as f:
            tree = json.load(f)
    except Exception as e:
        print(f"{indent}ERROR: Failed to read BOM: {e}")
        return
    for node in tree:
        qty = node.get("quantity", 1)
        note = node.get("note", "")
        sub = node["sub_part"]
        sub_name = sub["name"]
        sub_ipn = sub.get("IPN", "")
        sub_parts = part_exists(sub_name, "", sub_ipn)
        if not sub_parts:
            print(f"{indent}WARNING: Sub-part '{sub_name}' not found – skipping")
            continue
        sub_pk = sub_parts[0]["pk"]
        payload = {
            "part": parent_pk,
            "sub_part": sub_pk,
            "quantity": qty,
            "note": note,
        }
        def try_post_bom(attempt=1):
            existing = requests.get(
                BASE_URL_BOM, headers=HEADERS,
                params={"part": parent_pk, "sub_part": sub_pk}
            ).json()
            existing = existing.get("results", existing) if isinstance(existing, dict) else existing
            if existing:
                bom_pk = existing[0]["pk"]
                r = requests.patch(f"{BASE_URL_BOM}{bom_pk}/", headers=HEADERS, json=payload)
                action = "UPDATED"
            else:
                r = requests.post(BASE_URL_BOM, headers=HEADERS, json=payload)
                action = "CREATED"
            if r.status_code in (200, 201):
                print(f"{indent}{action} BOM: {qty} × {sub_name}")
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
        description="Import template parts + single-level BOM from data/templates/ ? InvenTree"
    )
    parser.add_argument(
        "patterns", nargs="*", default=["**/*.json"],
        help="Glob patterns (default: all *.json under data/templates)"
    )
    parser.add_argument("--force-ipn", action="store_true",
                        help="Generate IPN from name when missing")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing template (name+revision) before import")
    parser.add_argument("--clean-dependencies", action="store_true",
                        help="Delete dependencies (requires two confirmations)")
    args = parser.parse_args()
    root = "data/templates"
    if not os.path.isdir(root):
        raise FileNotFoundError(f"{root} missing")
    files = []
    for pat in args.patterns:
        full = os.path.join(root, pat)
        matches = glob.glob(full, recursive=True)
        files.extend(matches)
    files = sorted({
        f for f in files
        if f.endswith(".json") and not f.endswith(".bom.json") and os.path.basename(f) != "category.json"
    })
    print(f"DEBUG: {len(files)} template files to import")
    for f in files:
        try:
            import_template_part(f, args.force_ipn, args.force, args.clean_dependencies)
        except Exception as e:
            print(f"ERROR: {e}")
if __name__ == "__main__":
    main()
