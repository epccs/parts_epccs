# file name: rm-inv-companies.py
# Use InvenTree API to delete companies from an InvenTree instance based on JSON files in data/companies.
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
# Accepts Linux globbing patterns (e.g., *.json, Customer [A-C].json, Customer [!D].json, Customer ?.json) to specify companies to delete.
# run as: python3 ./api/rm-inv-companies.py "Customer [A-C].json"
#         python3 ./api/rm-inv-companies.py 'Customer D.json'
#         python3 ./api/rm-inv-companies.py Customer\ E.json
#         python3 ./api/rm-inv-companies.py *.json
# Compatibility: Uses the company JSON files produced by inv-companies2json.py.

import requests
import json
import os
import glob
import sys

# API endpoint and authentication
BASE_URL = os.getenv("INVENTREE_URL") + "api/company/" if os.getenv("INVENTREE_URL") else None
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json"
}

def check_company_exists(name):
    """Check if a company with the given name exists and return its pk if found."""
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
            return results['results'][0]['pk'] if results['results'] else None
        else:
            print(f"DEBUG: Direct list response with {len(results)} companies")
            return results[0]['pk'] if results else None
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error checking company: {str(e)}")
        raise Exception(f"Network error checking company: {str(e)}")

def delete_company(company_name, company_pk):
    """Delete a company by its pk."""
    print(f"DEBUG: Attempting to delete company '{company_name}' with PK {company_pk}")
    delete_url = f"{BASE_URL}{company_pk}/"
    
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

def process_company_file(company_file):
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
    delete_company(company_name, company_pk)

def main():
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
    if len(sys.argv) < 2:
        print("DEBUG: No glob patterns provided")
        raise Exception("Usage: python3 rm-inv-companies.py <glob_pattern> [glob_pattern...]")
    
    glob_patterns = sys.argv[1:]
    print(f"DEBUG: Glob patterns provided: {glob_patterns}")
    
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
            process_company_file(company_file)
            
    except Exception as e:
        print(f"DEBUG: Error in main loop: {str(e)}")
        raise

if __name__ == "__main__":
    main()