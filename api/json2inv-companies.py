#!/usr/bin/env python3
# file name: json2inv-companies.py
# version: 2025-11-09-v2  # Updated for full address import
# --------------------------------------------------------------
# Import companies + all addresses from data/companies/*.json -> InvenTree
#
# * CLI glob patterns (e.g. "Customer_?.json", "Bourns_Inc.json")
# * No arguments: import **all** JSON files (equivalent to "*.json")
# * Skips duplicates (checks by exact name)
# * Compatible with inv-companies2json.py export
#
# example usage:
# python3 ./api/json2inv-companies.py "Customer_?.json"
# python3 ./api/json2inv-companies.py "Bourns_Inc.json"
# python3 ./api/json2inv-companies.py # all
# python3 ./api/json2inv-companies.py "*.json"
# --------------------------------------------------------------
# if debugging is needed: https://grok.com/share/c2hhcmQtMw%3D%3D_5cacf023-0403-4114-82c1-8decc20f700a
import requests
import json
import os
import glob
import argparse
# ----------------------------------------------------------------------
# API endpoint & auth
# ----------------------------------------------------------------------
BASE_URL = os.getenv("INVENTREE_URL")
if BASE_URL:
    BASE_URL = BASE_URL.rstrip("/") + "/api/company/"
    ADDRESS_URL = BASE_URL.rstrip("/") + "/address/"
else:
    BASE_URL = None
    ADDRESS_URL = None
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
# ----------------------------------------------------------------------
# Helper: check if company exists (by exact name)
# ----------------------------------------------------------------------
def check_company_exists(name):
    """Return list of matching companies (or empty list)."""
    print(f"DEBUG: Checking if company '{name}' exists")
    params = {"name": name}
    try:
        r = requests.get(BASE_URL, headers=HEADERS, params=params)
        print(f"DEBUG: Company check status {r.status_code}")
        if r.status_code != 200:
            raise Exception(f"Check failed: {r.status_code} – {r.text}")
        data = r.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        print(f"DEBUG: Found {len(results)} matches")
        return results
    except requests.RequestException as e:
        raise Exception(f"Network error checking company: {e}")
# ----------------------------------------------------------------------
# Import addresses for a newly created company
# ----------------------------------------------------------------------
def import_addresses(new_pk, addresses):
    """Create addresses for the new company PK."""
    imported_addresses = 0
    for addr in addresses:
        # Allowed writable fields for address
        allowed_addr = [
            "title", "primary", "line1", "line2", "postal_code", "postal_city",
            "province", "country", "shipping_notes", "internal_shipping_notes", "link"
        ]
        payload = {k: addr.get(k) for k in allowed_addr if k in addr}
        payload["company"] = new_pk
        print(f"DEBUG: Address payload ? {payload}")
        try:
            r = requests.post(ADDRESS_URL, headers=HEADERS, json=payload)
            print(f"DEBUG: POST address ? {r.status_code}")
            if r.status_code != 201:
                raise Exception(f"Address create failed: {r.text}")
            new_addr = r.json()
            print(f"DEBUG: Created address '{new_addr['title']}' (PK {new_addr['pk']}) for company {new_pk}")
            imported_addresses += 1
        except requests.RequestException as e:
            print(f"ERROR: Network error creating address: {e}")
    return imported_addresses
# ----------------------------------------------------------------------
# Import one company from a JSON file (now includes addresses)
# ----------------------------------------------------------------------
def import_company(filepath):
    """Read JSON, validate, create company, then import addresses."""
    print(f"DEBUG: Importing {filepath}")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise Exception(f"Failed to read {filepath}: {e}")
    if isinstance(data, list):
        data = data[0]
    # Allowed writable fields for company
    allowed = [
        "name", "description", "website", "address", "phone", "email",
        "contact", "currency", "is_supplier", "is_manufacturer", "is_customer"
    ]
    payload = {k: data.get(k) for k in allowed if k in data}
    if not payload.get("name"):
        print("DEBUG: Skipping – no name")
        return None
    print(f"DEBUG: Company payload -> {payload}")
    # Skip if already exists
    existing = check_company_exists(payload["name"])
    if existing:
        pk = existing[0]["pk"]
        print(f"DEBUG: Company already exists (PK {pk}) – skipping")
        return pk
    # Create company
    try:
        r = requests.post(BASE_URL, headers=HEADERS, json=payload)
        print(f"DEBUG: POST company -> {r.status_code}")
        if r.status_code != 201:
            raise Exception(f"Create failed: {r.text}")
        new = r.json()
        new_pk = new["pk"]
        print(f"DEBUG: Created company '{new['name']}' (PK {new_pk})")
        # Import addresses if present
        addresses = data.get("addresses", [])
        if addresses:
            imported_addrs = import_addresses(new_pk, addresses)
            print(f"DEBUG: Imported {imported_addrs} addresses for company {new_pk}")
        return new_pk
    except requests.RequestException as e:
        raise Exception(f"Network error creating company: {e}")
# ----------------------------------------------------------------------
# CLI + glob handling
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Import InvenTree companies from data/companies/*.json"
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns (e.g. 'Customer_?.json'). Default: all *.json"
    )
    args = parser.parse_args()
    if not TOKEN:
        raise Exception("INVENTREE_TOKEN not set")
    if not BASE_URL:
        raise Exception("INVENTREE_URL not set")
    print(f"DEBUG: Using BASE_URL: {BASE_URL}")
    dirname = "data/companies"
    if not os.path.isdir(dirname):
        raise FileNotFoundError(f"{dirname} not found")
    # ------------------------------------------------------------------
    # Resolve files
    # ------------------------------------------------------------------
    files = []
    for pat in args.patterns or ["*.json"]:
        full = os.path.join(dirname, pat)
        matches = glob.glob(full, recursive=False)
        files.extend(matches)
    # Fallback: treat args as literal filenames
    if not files:
        for pat in args.patterns:
            fp = os.path.join(dirname, pat)
            if os.path.isfile(fp) and fp.endswith(".json"):
                files.append(fp)
    files = sorted(set(f for f in files if f.endswith(".json")))
    print(f"DEBUG: {len(files)} files to import")
    if not files:
        print("DEBUG: No JSON files found – exiting")
        return
    # ------------------------------------------------------------------
    # Import loop
    # ------------------------------------------------------------------
    imported = 0
    for f in files:
        try:
            pk = import_company(f)
            if pk:
                imported += 1
        except Exception as e:
            print(f"ERROR: {e}")
    print(f"SUMMARY: Imported {imported} companies")
if __name__ == "__main__":
    main()