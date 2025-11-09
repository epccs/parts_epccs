#!/usr/bin/env python3
# file name: rm-inv-companies.py
# version: 2025-11-09-v1
# --------------------------------------------------------------
# Use InvenTree API to delete companies from an InvenTree instance based on JSON files in data/companies.
# * Accepts Linux globbing patterns (e.g., '*.json', 'Customer_?.json') to specify companies to delete.
# * Optional CLI flag --remove-json to delete company JSON files after successful deletion.
# * Optional CLI flag --clean-dependencies to delete all dependencies (with two confirmations if dependencies exist).
# * Compatibility: Uses the company JSON files produced by inv-companies2json.py.
# * Deletes addresses and other dependencies (contacts, supplier parts, etc.) if --clean-dependencies is used.
# --------------------------------------------------------------
# Example usage:
# python3 ./api/rm-inv-companies.py "Customer_?.json"
# python3 ./api/rm-inv-companies.py "Bourns_Inc.json"
# python3 ./api/rm-inv-companies.py "*.json" --remove-json --clean-dependencies
# --------------------------------------------------------------
# grok share <https://grok.com/share/c2hhcmQtMw%3D%3D_fe21cf13-2e9e-48d5-81c2-a628d7dc6db7>

import requests
import json
import os
import glob
import sys
import argparse
# ----------------------------------------------------------------------
# API endpoints
# ----------------------------------------------------------------------
if os.getenv("INVENTREE_URL"):
    BASE_URL = os.getenv("INVENTREE_URL").rstrip("/")
    BASE_URL_COMPANY = f"{BASE_URL}/api/company/"
    BASE_URL_ADDRESS = f"{BASE_URL}/api/company/address/"
    BASE_URL_CONTACT = f"{BASE_URL}/api/company/contact/"
    BASE_URL_PRICE_BREAK = f"{BASE_URL}/api/company/price_break/"
    BASE_URL_SUPPLIER_PART = f"{BASE_URL}/api/part/supplier/"
    BASE_URL_MANUFACTURER_PART = f"{BASE_URL}/api/part/manufacturer/"
    BASE_URL_PURCHASE_ORDER = f"{BASE_URL}/api/order/po/"
    BASE_URL_SALES_ORDER = f"{BASE_URL}/api/order/so/"
    BASE_URL_RETURN_ORDER = f"{BASE_URL}/api/order/ro/"
else:
    BASE_URL = None
    BASE_URL_COMPANY = BASE_URL_ADDRESS = BASE_URL_CONTACT = None
    BASE_URL_PRICE_BREAK = BASE_URL_SUPPLIER_PART = BASE_URL_MANUFACTURER_PART = None
    BASE_URL_PURCHASE_ORDER = BASE_URL_SALES_ORDER = BASE_URL_RETURN_ORDER = None
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
# ----------------------------------------------------------------------
# Helper: check if company exists (by exact name)
# ----------------------------------------------------------------------
def check_company_exists(name):
    """Check if a company with the given name exists and return its pk if found."""
    print(f"DEBUG: Checking if company '{name}' exists")
    params = {'name': name}
    try:
        response = requests.get(BASE_URL_COMPANY, headers=HEADERS, params=params)
        print(f"DEBUG: Company check response status: {response.status_code}")
        if response.status_code != 200:
            print(f"DEBUG: Failed to check company: {response.text}")
            raise Exception(f"Failed to check existing company: {response.status_code} - {response.text}")
        results = response.json()
        if isinstance(results, dict) and 'results' in results:
            print(f"DEBUG: Found {len(results['results'])} matching companies")
            return results['results'][0]['pk'] if results['results'] else None
        else:
            print(f"DEBUG: Direct list response with {len(results)} companies")
            return results[0]['pk'] if results else None
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error checking company: {str(e)}")
        raise Exception(f"Network error checking company: {str(e)}")
# ----------------------------------------------------------------------
# Dependency handling
# ----------------------------------------------------------------------
def check_dependencies(company_pk):
    deps = {
        "addresses": [], "contacts": [], "price_breaks": [], "supplier_parts": [], "manufacturer_parts": [],
        "purchase_orders": [], "sales_orders": [], "return_orders": []
    }
    for endpoint, key, filter_param in [
        (BASE_URL_ADDRESS, "addresses", "company"),
        (BASE_URL_CONTACT, "contacts", "company"),
        (BASE_URL_PRICE_BREAK, "price_breaks", "supplier"),
        (BASE_URL_SUPPLIER_PART, "supplier_parts", "supplier"),
        (BASE_URL_MANUFACTURER_PART, "manufacturer_parts", "manufacturer"),
        (BASE_URL_PURCHASE_ORDER, "purchase_orders", "supplier"),
        (BASE_URL_SALES_ORDER, "sales_orders", "customer"),
        (BASE_URL_RETURN_ORDER, "return_orders", "customer"),
    ]:
        params = {filter_param: company_pk}
        try:
            r = requests.get(endpoint, headers=HEADERS, params=params)
            print(f"DEBUG: Dep {key} -> {r.status_code}")
            if r.status_code == 200:
                js = r.json()
                deps[key] = js.get("results", js) if isinstance(js, dict) else js
        except requests.RequestException as e:
            print(f"DEBUG: Dep {key} network error: {e}")
    return deps
def delete_dependencies(company_name, company_pk, clean):
    deps = check_dependencies(company_pk)
    total = sum(len(v) for v in deps.values())
    if total == 0:
        print(f"DEBUG: No dependencies for '{company_name}' (PK {company_pk})")
        return True
    print(f"WARNING: {total} dependencies for '{company_name}' (PK {company_pk})")
    for k, items in deps.items():
        if items:
            print(f" • {len(items)} {k}: {[i.get('pk') for i in items]}")
    if not clean:
        print("DEBUG: Dependencies exist – use --clean-dependencies to delete them")
        return False
    if input(f"Type 'YES' to delete {total} deps: ") != "YES":
        print("DEBUG: Cancelled (first)")
        return False
    if input(f"Type 'CONFIRM' to PERMANENTLY delete: ") != "CONFIRM":
        print("DEBUG: Cancelled (second)")
        return False
    for key, items in deps.items():
        if items:
            endpoint = {
                "addresses": BASE_URL_ADDRESS,
                "contacts": BASE_URL_CONTACT,
                "price_breaks": BASE_URL_PRICE_BREAK,
                "supplier_parts": BASE_URL_SUPPLIER_PART,
                "manufacturer_parts": BASE_URL_MANUFACTURER_PART,
                "purchase_orders": BASE_URL_PURCHASE_ORDER,
                "sales_orders": BASE_URL_SALES_ORDER,
                "return_orders": BASE_URL_RETURN_ORDER,
            }[key]
            for it in items:
                pk = it.get("pk")
                url = f"{endpoint}{pk}/"
                try:
                    r = requests.delete(url, headers=HEADERS)
                    print(f"DEBUG: Delete {key} {pk} -> {r.status_code}")
                    if r.status_code != 204:
                        raise Exception(f"Delete failed: {r.text}")
                except requests.RequestException as e:
                    raise Exception(f"Network error deleting {key} {pk}: {e}")
    print(f"DEBUG: All dependencies for '{company_name}' deleted")
    return True
# ----------------------------------------------------------------------
# Delete one company
# ----------------------------------------------------------------------
def delete_company(company_name, company_pk, clean_deps):
    """Delete a company by its pk, handling dependencies if flagged."""
    print(f"DEBUG: Attempting to delete company '{company_name}' with PK {company_pk}")
    if not delete_dependencies(company_name, company_pk, clean_deps):
        print(f"DEBUG: Deletion blocked for '{company_name}' due to dependencies or cancellation")
        return
    # Set active=False
    try:
        patch_url = f"{BASE_URL_COMPANY}{company_pk}/"
        r = requests.patch(patch_url, headers=HEADERS, json={"active": False})
        print(f"DEBUG: Patch active=False -> {r.status_code}")
        if r.status_code not in (200, 201):
            raise Exception(f"Patch failed: {r.text}")
    except requests.RequestException as e:
        print(f"DEBUG: Network error patching active: {str(e)}")
        raise Exception(f"Network error patching active: {str(e)}")
    # Delete
    delete_url = f"{BASE_URL_COMPANY}{company_pk}/"
    try:
        response = requests.delete(delete_url, headers=HEADERS)
        print(f"DEBUG: Company deletion response status: {response.status_code}")
        if response.status_code != 204:
            print(f"DEBUG: Failed to delete company '{company_name}': {response.text}")
            raise Exception(f"Failed to delete company '{company_name}': {response.status_code} - {response.text}")
        print(f"DEBUG: Successfully deleted company '{company_name}' with PK {company_pk}")
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error deleting company '{company_name}': {str(e)}")
        raise Exception(f"Network error deleting company '{company_name}': {str(e)}")
# ----------------------------------------------------------------------
# Process one JSON file
# ----------------------------------------------------------------------
def process_company_file(company_file, remove_json=False, clean_deps=False):
    """Process a single company JSON file to delete the corresponding company."""
    print(f"DEBUG: Processing company file: {company_file}")
    try:
        with open(company_file, 'r', encoding='utf-8') as f:
            company_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"DEBUG: Invalid JSON in {company_file}: {str(e)}")
        return
    except Exception as e:
        print(f"DEBUG: Error reading {company_file}: {str(e)}")
        return
    # Handle both single object and list formats
    if isinstance(company_data, list):
        print(f"DEBUG: Company data is a list, using first item")
        company_data = company_data[0]
    company_name = company_data.get('name')
    if not company_name:
        print(f"DEBUG: Skipping company with missing name in {company_file}")
        return
    # Check if company exists
    company_pk = check_company_exists(company_name)
    if not company_pk:
        print(f"DEBUG: Company '{company_name}' does not exist in InvenTree, skipping")
        return
    # Delete the company
    delete_company(company_name, company_pk, clean_deps)
    # Optionally remove JSON file
    if remove_json:
        print(f"DEBUG: Removing company file {company_file}")
        try:
            os.remove(company_file)
            print(f"DEBUG: Successfully removed {company_file}")
        except Exception as e:
            print(f"DEBUG: Error removing {company_file}: {str(e)}")
# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    # Parse CLI arguments
    parser = argparse.ArgumentParser(description="Delete InvenTree companies based on data/companies JSON files.")
    parser.add_argument('patterns', nargs='*', help="Glob patterns for companies (e.g., '*.json', 'Customer_?.json')")
    parser.add_argument('--remove-json', action='store_true', help="Remove company JSON files after deletion")
    parser.add_argument('--clean-dependencies', action='store_true',
                        help="Delete all dependencies (two confirmations if dependencies exist)")
    args = parser.parse_args()
    print("DEBUG: Starting main function")
    if not TOKEN:
        print("DEBUG: INVENTREE_TOKEN not set")
        raise Exception("INVENTREE_TOKEN environment variable not set. Set it with: export INVENTREE_TOKEN='your-token'")
    if not BASE_URL:
        print("DEBUG: INVENTREE_URL not set")
        raise Exception("INVENTREE_URL environment variable not set. Set it with: export INVENTREE_URL='http://localhost:8000/'")
    print(f"DEBUG: Using BASE_URL: {BASE_URL}")
    dirname = "data/companies"
    print(f"DEBUG: Checking directory: {dirname}")
    if not os.path.exists(dirname):
        print(f"DEBUG: Directory '{dirname}' does not exist")
        raise FileNotFoundError(f"Directory '{dirname}' not found. Please ensure you're running the script from the correct location.")
    if not os.access(dirname, os.R_OK):
        print(f"DEBUG: Cannot read {dirname}")
        raise PermissionError(f"Insufficient permissions to read {dirname}")
    # Get glob patterns from command-line arguments
    print(f"DEBUG: Raw command-line arguments: {sys.argv[1:]}")
    glob_patterns = args.patterns
    print(f"DEBUG: Glob patterns provided: {glob_patterns}")
    if not glob_patterns:
        print("DEBUG: No glob patterns provided")
        raise Exception("Usage: python3 rm-inv-companies.py [glob_pattern...] [--remove-json] [--clean-dependencies]")
    try:
        company_files = []
        for pattern in glob_patterns:
            pattern_path = os.path.join(dirname, pattern)
            print(f"DEBUG: Expanding glob pattern: {pattern_path}")
            matched_files = glob.glob(pattern_path, recursive=False)
            print(f"DEBUG: Matched {len(matched_files)} files for pattern '{pattern}': {matched_files}")
            company_files.extend(matched_files)
        # Handle case where pattern is passed literally (e.g., no shell expansion)
        if not company_files:
            print(f"DEBUG: No files matched, attempting to interpret patterns as filenames")
            for pattern in glob_patterns:
                pattern_path = os.path.join(dirname, pattern)
                if os.path.isfile(pattern_path) and pattern_path.endswith('.json'):
                    print(f"DEBUG: Adding literal file: {pattern_path}")
                    company_files.append(pattern_path)
        company_files = sorted(set(company_files))  # Remove duplicates and sort
        print(f"DEBUG: Total unique company files to process: {len(company_files)}: {company_files}")
        if not company_files:
            print(f"DEBUG: No JSON files matched or found, exiting")
            return
        for company_file in company_files:
            if not company_file.endswith('.json'):
                print(f"DEBUG: Skipping non-JSON file: {company_file}")
                continue
            process_company_file(company_file, args.remove_json, args.clean_dependencies)
    except Exception as e:
        print(f"DEBUG: Error in main loop: {str(e)}")
        raise
if __name__ == "__main__":
    main()