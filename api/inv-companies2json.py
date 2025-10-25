# file name: inv-companies2json.py
# Use InvenTree API for Companies with the goal of pulling data from InvenTree to populate a folder (data/companies).
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
# Use each company from InvenTree to create a json file under the `data/companies` folder
# sanitize the company name for the filename by replacing spaces with underscores and removing dots (e.g., Acme Inc. 
# becomes Acme_Inc), also replace invalid chars. Keep the sanitized name inside the JSON as well to push into another 
# InvenTree instance.
# Import Compatibility: The structure should be compatible with the `json2inv-companies.py` import script that can recreate 
#                       the Companies in another InvenTree instance.

import requests
import json
import os
import re

# API endpoint and authentication (for Company Management)
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
if os.getenv("INVENTREE_URL"):
    BASE_URL = os.getenv("INVENTREE_URL") + "api/company/"
else:
    BASE_URL = None
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json"
}

def sanitize_company_name(name):
    """Sanitize company name for JSON and filename by replacing spaces with underscores and removing dots."""
    print(f"DEBUG: Sanitizing company name: {name}")
    sanitized = name.replace(' ', '_').replace('.', '')
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', sanitized.strip())  # Additional sanitization for invalid chars
    print(f"DEBUG: Sanitized company name to: {sanitized}")
    return sanitized

def fetch_companies(url):
    """Fetch all companies, handling pagination."""
    print(f"DEBUG: Fetching companies from URL: {url}")
    companies = []
    try:
        while url:
            print(f"DEBUG: Sending GET request to {url}")
            response = requests.get(url, headers=HEADERS)
            print(f"DEBUG: API response status: {response.status_code}")
            if response.status_code != 200:
                print(f"DEBUG: API request failed: {response.text}")
                raise Exception(f"API request failed: {response.status_code} - {response.text}")
            
            data = response.json()
            if isinstance(data, dict) and "results" in data:
                print(f"DEBUG: Paginated response, found {len(data['results'])} items")
                companies.extend(data["results"])
                url = data.get("next")
                print(f"DEBUG: Next page URL: {url}")
            else:
                print(f"DEBUG: Direct list response, found {len(data)} items")
                companies.extend(data)
                url = None
        print(f"DEBUG: Total companies fetched: {len(companies)}")
        return companies
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error fetching companies: {str(e)}")
        raise Exception(f"Network error: {str(e)}")

def save_company_to_file(company):
    """Save a single company's data to a JSON file named after the sanitized company name."""
    company_name = company.get("name")
    if not company_name:
        print(f"DEBUG: Skipping company with missing name: {company}")
        return
    
    # Modify company data: sanitize name and clear image
    company_modified = company.copy()
    company_modified['name'] = sanitize_company_name(company_name)
    company_modified['image'] = ""
    print(f"DEBUG: Modified company data: name={company_modified['name']}, image={company_modified['image']}")
    
    dirname = "data/companies"
    print(f"DEBUG: Ensuring directory exists: {dirname}")
    if not os.path.exists(dirname):
        os.makedirs(dirname)
        print(f"DEBUG: Created directory: {dirname}")
    
    filename = f"{dirname}/{company_modified['name']}.json"
    print(f"DEBUG: Saving company {company_modified['name']} to {filename}")
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(company_modified, f, indent=4)
            f.write('\n')
        print(f"DEBUG: Successfully saved {filename}")
    except Exception as e:
        print(f"DEBUG: Error saving {filename}: {str(e)}")
        raise Exception(f"Error saving {filename}: {str(e)}")

def main():
    print("DEBUG: Starting main function")
    if not TOKEN:
        print("DEBUG: INVENTREE_TOKEN not set")
        raise Exception("INVENTREE_TOKEN environment variable not set. Set it with: export INVENTREE_TOKEN='your-token'")
    if not BASE_URL:
        print("DEBUG: INVENTREE_URL not set")
        raise Exception("INVENTREE_URL environment variable not set. Set it with: export INVENTREE_URL='http://localhost:8000/'")
    
    print(f"DEBUG: Using BASE_URL: {BASE_URL}")
    try:
        # Fetch all companies
        print(f"DEBUG: Fetching companies")
        companies = fetch_companies(BASE_URL)
        print(f"DEBUG: Retrieved {len(companies)} companies")
        
        # Save each company to a separate JSON file
        for company in companies:
            print(f"DEBUG: Processing company: {company.get('name', 'unknown')}")
            save_company_to_file(company)
            
    except Exception as e:
        print(f"DEBUG: Error in main: {str(e)}")
        raise

if __name__ == "__main__":
    main()