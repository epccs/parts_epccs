import requests
import json
import os
import re

# API endpoint and authentication
BASE_URL = "http://localhost:8000/api/company/"
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json"
}

def sanitize_filename(name):
    """Sanitize company name to create a valid filename."""
    # Replace invalid filename characters with underscores
    return re.sub(r'[<>:"/\\|?*]', '_', name.strip())

def fetch_companies(url):
    """Fetch all companies, handling pagination."""
    companies = []
    while url:
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            raise Exception(f"API request failed: {response.status_code} - {response.text}")
        
        data = response.json()
        if isinstance(data, dict) and "results" in data:
            # Handle paginated API response
            companies.extend(data["results"])
            url = data.get("next")
        else:
            # Handle direct list response
            companies.extend(data)
            url = None  # No pagination in this case
        
    return companies

def save_company_to_file(company):
    """Save a single company's data to a JSON file named after the company."""
    company_name = company["name"]
    dirname = "data/companies"
    if not os.path.exists(dirname):
        os.makedirs(dirname)
        
    filename = f"{dirname}/{sanitize_filename(company_name)}.json"
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(company, f, indent=4)
        f.write('\n')
    print(f"Saved {filename}")

def main():
    if not TOKEN:
        raise Exception("INVENTREE_TOKEN environment variable not set. Set it with: export INVENTREE_TOKEN='your-token'")
    
    try:
        # Fetch all companies
        companies = fetch_companies(BASE_URL)
        print(f"Retrieved {len(companies)} companies")
        
        # Save each company to a separate JSON file
        for company in companies:
            save_company_to_file(company)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()