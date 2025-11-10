#!/usr/bin/env python3
# file name: inv-companies2json.py
# version: 2025-11-10-v1
# --------------------------------------------------------------
# Export InvenTree companies + all addresses to data/companies/*.json
# * CLI glob patterns (e.g. "Customer_?", "DigiKey")
# * Matches sanitized company name (spaces->_, dots->removed)
# * Strips .json from pattern automatically
# * Compatible with json2inv-companies.py import script
# --------------------------------------------------------------
# example usage:
# Export everything
# python3 ./api/inv-companies2json.py
#
# Export all (*) or a single-character (?) companies
# python3 ./api/inv-companies2json.py "Customer_*"
# python3 ./api/inv-companies2json.py "Customer_?"
#
# Export one company
# python3 ./api/inv-companies2json.py "DigiKey"
# --------------------------------------------------------------
import requests
import json
import os
import re
import argparse
# ----------------------------------------------------------------------
# API endpoint & auth
# ----------------------------------------------------------------------
if os.getenv("INVENTREE_URL"):
    BASE_URL = os.getenv("INVENTREE_URL") + "api/company/"
else:
    BASE_URL = None
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json"
}
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
# Fetch all companies (handles pagination)
# ----------------------------------------------------------------------
def fetch_companies(url):
    """Return a flat list of all companies."""
    print(f"DEBUG: Fetching companies from {url}")
    companies = []
    try:
        while url:
            resp = requests.get(url, headers=HEADERS)
            print(f"DEBUG: GET {url} ? {resp.status_code}")
            if resp.status_code != 200:
                raise Exception(f"API error {resp.status_code}: {resp.text}")
            data = resp.json()
            if isinstance(data, dict) and "results" in data:
                companies.extend(data["results"])
                url = data.get("next")
                print(f"DEBUG: Next page -> {url}")
            else:
                companies.extend(data)
                url = None
        print(f"DEBUG: Total companies fetched: {len(companies)}")
        return companies
    except requests.RequestException as e:
        raise Exception(f"Network error: {e}")
# ----------------------------------------------------------------------
# Fetch all addresses for a company (handles pagination if needed)
# ----------------------------------------------------------------------
def fetch_addresses(company_pk):
    """Fetch all addresses for a given company PK."""
    address_url = os.getenv("INVENTREE_URL") + f"api/company/address/?company={company_pk}"
    print(f"DEBUG: Fetching addresses from {address_url}")
    addresses = []
    try:
        url = address_url
        while url:
            resp = requests.get(url, headers=HEADERS)
            print(f"DEBUG: GET {url} -> {resp.status_code}")
            if resp.status_code != 200:
                raise Exception(f"API error {resp.status_code}: {resp.text}")
            data = resp.json()
            if isinstance(data, dict) and "results" in data:
                addresses.extend(data["results"])
                url = data.get("next")
                print(f"DEBUG: Next address page -> {url}")
            else:
                addresses.extend(data)
                url = None
        print(f"DEBUG: Fetched {len(addresses)} addresses for company PK {company_pk}")
        return addresses
    except requests.RequestException as e:
        raise Exception(f"Network error fetching addresses: {e}")
# ----------------------------------------------------------------------
# Save one company to file (now includes all addresses)
# ----------------------------------------------------------------------
def save_company_to_file(company):
    name = company.get("name")
    if not name:
        print(f"DEBUG: Skipping company with no name: {company}")
        return
    sanitized = sanitize_company_name(name)
    company_mod = company.copy()
    company_mod["name"] = sanitized
    company_mod["image"] = ""
    # Fetch and add all addresses if address_count > 0
    if company.get("address_count", 0) > 0:
        addresses = fetch_addresses(company["pk"])
        # Remove pk and company from each address
        for addr in addresses:
            addr.pop("pk", None)
            addr.pop("company", None)
        company_mod["addresses"] = addresses
    else:
        company_mod["addresses"] = []
    # Remove read-only fields that aren't needed for import
    for key in ["pk", "primary_address", "address_count", "parts_supplied", "parts_manufactured"]:
        company_mod.pop(key, None)
    dirname = "data/companies"
    os.makedirs(dirname, exist_ok=True)
    filename = f"{dirname}/{sanitized}.json"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(company_mod, f, indent=4)
            f.write("\n")
        print(f"DEBUG: Saved -> {filename}")
    except Exception as e:
        print(f"DEBUG: Failed to write {filename}: {e}")
# ----------------------------------------------------------------------
# Main – supports glob patterns (without .json)
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Export InvenTree companies to data/companies/*.json (with glob support)."
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns for company names (e.g. 'Customer_?', 'DigiKey'). "
             "Default: export ALL companies. .json suffix is ignored."
    )
    args = parser.parse_args()
    if not TOKEN:
        raise Exception("INVENTREE_TOKEN not set")
    if not BASE_URL:
        raise Exception("INVENTREE_URL not set")
    print(f"DEBUG: Using BASE_URL: {BASE_URL}")
    # ------------------------------------------------------------------
    # 1. Fetch ALL companies
    # ------------------------------------------------------------------
    all_companies = fetch_companies(BASE_URL)
    # ------------------------------------------------------------------
    # 2. Build list of compiled regex patterns from glob args (strip .json)
    # ------------------------------------------------------------------
    patterns = []
    if args.patterns:
        for raw_pat in args.patterns:
            # Remove .json if present
            pat = raw_pat.removesuffix(".json").strip()
            if not pat:
                continue
            # Convert glob -> regex
            regex = "^" + re.escape(pat).replace("\\*", ".*").replace("\\?", ".") + "$"
            pattern = re.compile(regex, re.IGNORECASE)
            patterns.append(pattern)
        print(f"DEBUG: Filtering with {len(patterns)} patterns: {[p.pattern for p in patterns]}")
    else:
        patterns = None
    # ------------------------------------------------------------------
    # 3. Export matching companies
    # ------------------------------------------------------------------
    exported = 0
    for comp in all_companies:
        orig_name = comp.get("name", "")
        if not orig_name:
            continue
        sanitized = sanitize_company_name(orig_name)
        # Match against sanitized name
        if patterns and not any(pat.search(sanitized) for pat in patterns):
            print(f"DEBUG: Skipping (no pattern match): {sanitized}")
            continue
        save_company_to_file(comp)
        exported += 1
    print(f"SUMMARY: Exported {exported} companies")
if __name__ == "__main__":
    main()