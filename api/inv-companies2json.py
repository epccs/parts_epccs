#!/usr/bin/env python3
# file name: inv-companies2json.py
# version: 2025-10-31-v2
# --------------------------------------------------------------
# Export InvenTree companies → data/companies/*.json
# * CLI glob patterns (e.g. "Customer_?.json", "Acme_Inc.json")
# * Sanitizes name for filename & JSON (spaces→_, dots→removed, invalid chars→_)
# * Compatible with json2inv-companies.py import script
# --------------------------------------------------------------
# example usage:
#    Export everything
#    python3 ./api/inv-companies2json.py
#
#    Export all (*) or a single-character (?) Customer glob
#    python3 ./api/inv-companies2json.py "Customer_*.json"
#    python3 ./api/inv-companies2json.py "Customer_?.json"
#
#    Export one company
#    python3 ./api/inv-companies2json.py "Acme_Inc.json"

import requests
import json
import os
import glob
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
    print(f"DEBUG: Sanitized → {sanitized}")
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
            print(f"DEBUG: GET {url} → {resp.status_code}")
            if resp.status_code != 200:
                raise Exception(f"API error {resp.status_code}: {resp.text}")

            data = resp.json()
            if isinstance(data, dict) and "results" in data:
                companies.extend(data["results"])
                url = data.get("next")
                print(f"DEBUG: Next page → {url}")
            else:                       # non-paginated list
                companies.extend(data)
                url = None
        print(f"DEBUG: Total companies fetched: {len(companies)}")
        return companies
    except requests.RequestException as e:
        raise Exception(f"Network error: {e}")

# ----------------------------------------------------------------------
# Save one company to file
# ----------------------------------------------------------------------
def save_company_to_file(company):
    name = company.get("name")
    if not name:
        print(f"DEBUG: Skipping company with no name: {company}")
        return

    sanitized = sanitize_company_name(name)
    company_mod = company.copy()
    company_mod["name"] = sanitized
    company_mod["image"] = ""           # clear image for import

    dirname = "data/companies"
    os.makedirs(dirname, exist_ok=True)
    filename = f"{dirname}/{sanitized}.json"

    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(company_mod, f, indent=4)
            f.write("\n")
        print(f"DEBUG: Saved → {filename}")
    except Exception as e:
        print(f"DEBUG: Failed to write {filename}: {e}")

# ----------------------------------------------------------------------
# Main – now supports glob patterns
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Export InvenTree companies to data/companies/*.json (with glob support)."
    )
    parser.add_argument(
        "patterns", nargs="*",
        help="Glob patterns for company names (e.g. 'Customer_?.json', 'Acme_Inc.json'). "
             "Default: export ALL companies."
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
    # 2. Build a set of desired sanitized names from glob patterns
    # ------------------------------------------------------------------
    if args.patterns:
        # Expand globs against the *sanitized* names we will create
        desired = set()
        for pat in args.patterns:
            # Replace * with .+ for regex matching (simple glob→regex)
            regex = "^" + pat.replace("*", ".*").replace("?", ".") + "$"
            desired.update(re.compile(regex, re.IGNORECASE))
        print(f"DEBUG: Filtering with {len(desired)} patterns")
    else:
        desired = None  # export all

    # ------------------------------------------------------------------
    # 3. Export matching companies
    # ------------------------------------------------------------------
    exported = 0
    for comp in all_companies:
        orig_name = comp.get("name", "")
        if not orig_name:
            continue

        sanitized = sanitize_company_name(orig_name)

        # Skip if pattern filter is active and name doesn't match
        if desired and not any(pat.search(sanitized) for pat in desired):
            print(f"DEBUG: Skipping (no pattern match): {sanitized}")
            continue

        save_company_to_file(comp)
        exported += 1

    print(f"SUMMARY: Exported {exported} companies")

if __name__ == "__main__":
    main()