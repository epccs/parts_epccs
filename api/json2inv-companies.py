# file name: json2inv-companies.py
# Use InvenTree API for Companies with the goal of pulling data from a folder `data/companies` and populating an InvenTree instance.
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
# Each company was exported from InvenTree into a JSON file under the `data/companies` folder.
# Supports individual file imports via command-line arguments with globbing (e.g., 'Customer_?.json').
# If no arguments are provided, imports all JSON files in data/companies (equivalent to '*.json').
# Compatibility: This program is compatible with the export of inv-companies2json.py.
# Example usage:
#   python3 ./api/json2inv-companies.py "Customer_?.json"
#   python3 ./api/json2inv-companies.py "Bourns_Inc.json"
#   python3 ./api/json2inv-companies.py  # Imports all companies
#   python3 ./api/json2inv-companies.py "*.json"

import requests
import json
import os
import glob
import sys
import argparse

# API endpoint and authentication
BASE_URL = os.getenv("INVENTREE_URL") + "api/company/" if os.getenv("INVENTREE_URL") else None
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def check_company_exists(name):
    """Check if a company with the given name already exists."""
    print(f"DEBUG: Checking if company '{name}' exists")
    params = {'name': name}
    
    try:
        response = requests.get(BASE_URL, headers=HEADERS, params=params)
        print(f"DEBUG: Company check response status: {response.status_code}")
        if response.status_code != 200:
            print(f"DEBUG: Failed to check company: {response.text}")
            raise Exception(f"Failed to check existing company: {response.status_code} - {response.text}")
        
        results = response.json()
        if isinstance(results, dict) and 'results' in results:
            print(f"DEBUG: Found {len(results['results'])} matching companies")
            return results['results']
        else:
            print(f"DEBUG: Direct list response with {len(results)} companies")
            return results
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error checking company: {str(e)}")
        raise Exception(f"Network error checking company: {str(e)}")

def import_company(company_file):
    """Import a single company from a JSON file."""
    print(f"DEBUG: Reading company file: {company_file}")
    try:
        with open(company_file, 'r', encoding='utf-8') as f:
            company_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"DEBUG: Invalid JSON in {company_file}: {str(e)}")
        raise Exception(f"Invalid JSON in {company_file}: {str(e)}")
    except Exception as e:
        print(f"DEBUG: Error reading {company_file}: {str(e)}")
        raise Exception(f"Error reading {company_file}: {str(e)}")
    
    # Handle both single object and list formats
    if isinstance(company_data, list):
        print(f"DEBUG: Company data is a list, using first item")
        company_data = company_data[0]
    
    # Prepare POST data with writable fields
    post_data = {}
    allowed_fields = [
        'name', 'description', 'website', 'address', 'phone', 'email',
        'contact', 'currency', 'is_supplier', 'is_manufacturer', 'is_customer'
    ]
    for field in allowed_fields:
        if field in company_data:
            post_data[field] = company_data[field]
    
    if not post_data.get('name'):
        print(f"DEBUG: Skipping company with missing name in {company_file}")
        return None
    
    print(f"DEBUG: Prepared company POST data: {post_data}")
    
    # Check if company already exists
    existing_companies = check_company_exists(post_data['name'])
    if existing_companies:
        print(f"DEBUG: Company '{post_data['name']}' already exists with PK {existing_companies[0]['pk']}")
        return existing_companies[0]['pk']
    
    # Create company
    try:
        print(f"DEBUG: Posting company to {BASE_URL}")
        response = requests.post(BASE_URL, headers=HEADERS, json=post_data)
        print(f"DEBUG: Company creation response status: {response.status_code}")
        if response.status_code != 201:
            print(f"DEBUG: Failed to create company from {company_file}: {response.text}")
            raise Exception(f"Failed to create company from {company_file}: {response.status_code} - {response.text}")
        new_company = response.json()
        print(f"DEBUG: Created company '{new_company['name']}' with PK {new_company['pk']}")
        return new_company['pk']
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error creating company: {str(e)}")
        raise Exception(f"Network error creating company from {company_file}: {str(e)}")
    except json.JSONDecodeError as e:
        print(f"DEBUG: Invalid JSON response creating company: {str(e)}")
        raise Exception(f"Invalid JSON response creating company from {company_file}: {str(e)}")

def main():
    # Parse CLI arguments
    parser = argparse.ArgumentParser(description="Import InvenTree companies from data/companies JSON files.")
    parser.add_argument('patterns', nargs='*', default=['*.json'], help="Glob patterns for companies (e.g., 'Customer_?.json', 'Bourns_Inc.json'); defaults to '*.json'")
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
    
    try:
        print(f"DEBUG: Glob patterns provided: {args.patterns}")
        company_files = []
        for pattern in args.patterns:
            pattern_path = os.path.join(dirname, pattern)
            print(f"DEBUG: Expanding glob pattern: {pattern_path}")
            matched_files = glob.glob(pattern_path, recursive=False)
            print(f"DEBUG: Matched {len(matched_files)} files for pattern '{pattern}': {matched_files}")
            company_files.extend(matched_files)
        
        # Handle case where pattern is a literal file
        if not company_files:
            print(f"DEBUG: No files matched, attempting to interpret patterns as filenames")
            for pattern in args.patterns:
                pattern_path = os.path.join(dirname, pattern)
                if os.path.isfile(pattern_path) and pattern_path.endswith('.json'):
                    print(f"DEBUG: Adding literal file: {pattern_path}")
                    company_files.append(pattern_path)
        
        company_files = sorted(set(company_files))  # Remove duplicates and sort
        print(f"DEBUG: Found {len(company_files)} company files: {company_files}")
        if not company_files:
            print(f"DEBUG: No JSON files matched or found, exiting")
            return
        
        for company_file in company_files:
            if not company_file.endswith('.json'):
                print(f"DEBUG: Skipping non-JSON file: {company_file}")
                continue
            print(f"DEBUG: Processing company file: {company_file}")
            import_company(company_file)
            
    except PermissionError as e:
        print(f"DEBUG: Permission error accessing {dirname}: {str(e)}")
        raise
    except Exception as e:
        print(f"DEBUG: Error in main loop: {str(e)}")
        raise

if __name__ == "__main__":
    main()
