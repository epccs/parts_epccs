# Use API for Parts and Part Categories with the goal of pulling data from InvenTree to populate a hierarchical structure of categories and parts.
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
# Use each category and any subcategories to create a file system structure under a 'data/parts' folder
# Each folder (representing a category) should contain a category.json file that lists all immediate 
# subcategories of that folder’s category (not all categories globally).
# Populate the parts in the proper category file structure as a separate JSON file named after the part
# Import Compatibility: The structure should be compatible with an import script that can recreate the categories and parts in another InvenTree instance.
import requests
import json
import os
import re

# API endpoints and authentication
# API endpoints and authentication
if os.getenv("INVENTREE_URL"):
    BASE_URL = os.getenv("INVENTREE_URL")
    BASE_URL_PARTS = BASE_URL + "api/part/"
    BASE_URL_CATEGORIES = BASE_URL + "api/part/category/"
else:
    BASE_URL = None
    BASE_URL_PARTS = None
    BASE_URL_CATEGORIES = None
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json"
}

def sanitize_filename(name):
    """Sanitize name to create a valid filename or folder name."""
    print(f"DEBUG: Sanitizing name: {name}")
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', name.strip())
    print(f"DEBUG: Sanitized to: {sanitized}")
    return sanitized

def fetch_data(url):
    """Fetch data (parts or categories), handling pagination."""
    print(f"DEBUG: Fetching data from URL: {url}")
    items = []
    try:
        while url:
            response = requests.get(url, headers=HEADERS)
            print(f"DEBUG: API response status: {response.status_code}")
            if response.status_code != 200:
                print(f"DEBUG: API request failed: {response.text}")
                raise Exception(f"API request failed: {response.status_code} - {response.text}")
            
            data = response.json()
            if isinstance(data, dict) and "results" in data:
                print(f"DEBUG: Paginated response, found {len(data['results'])} items")
                items.extend(data["results"])
                url = data.get("next")
                print(f"DEBUG: Next page URL: {url}")
            else:
                print(f"DEBUG: Direct list response, found {len(data)} items")
                items.extend(data)
                url = None
        print(f"DEBUG: Total items fetched: {len(items)}")
        return items
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error fetching data: {str(e)}")
        raise Exception(f"Network error: {str(e)}")

def save_to_file(data, filepath):
    """Save data to a JSON file."""
    print(f"DEBUG: Saving data to {filepath}")
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            f.write('\n')
        print(f"DEBUG: Successfully saved {filepath}")
    except Exception as e:
        print(f"DEBUG: Error saving {filepath}: {str(e)}")
        raise Exception(f"Error saving {filepath}: {str(e)}")

def main():
    print("DEBUG: Starting main function")
    if not TOKEN:
        print("DEBUG: INVENTREE_TOKEN not set")
        raise Exception("INVENTREE_TOKEN environment variable not set. Set it with: export INVENTREE_TOKEN='your-token'")
    if not BASE_URL:
        print("DEBUG: INVENTREE_URL not set")
        raise Exception("INVENTREE_URL environment variable not set. Set it with: export INVENTREE_URL='http://localhost:8000/'")

    root_dir = 'data/parts'
    print(f"DEBUG: Ensuring root directory exists: {root_dir}")
    os.makedirs(root_dir, exist_ok=True)
    
    try:
        # Fetch all categories
        print(f"DEBUG: Fetching categories from {BASE_URL_CATEGORIES}")
        categories = fetch_data(BASE_URL_CATEGORIES)
        print(f"DEBUG: Retrieved {len(categories)} categories")
        
        # Build PK-to-pathstring map and parent-to-subcategories map
        pk_to_pathstring = {}
        parent_to_subcategories = {'None': []}  # 'None' for top-level categories
        for category in categories:
            pk = category.get('pk')
            pathstring = category.get('pathstring')
            parent_pk = str(category.get('parent')) if category.get('parent') is not None else 'None'
            if not pathstring or not pk:
                print(f"DEBUG: Skipping category {category.get('name', 'unknown')} (missing pk or pathstring)")
                continue
            pk_to_pathstring[pk] = pathstring
            print(f"DEBUG: Mapping category PK {pk} to pathstring {pathstring}")
            if parent_pk not in parent_to_subcategories:
                parent_to_subcategories[parent_pk] = []
            parent_to_subcategories[parent_pk].append(category)
        
        # Save top-level categories to data/parts/category.json
        top_level_cats = parent_to_subcategories.get('None', [])
        if top_level_cats:
            categories_file = os.path.join(root_dir, 'category.json')
            print(f"DEBUG: Saving {len(top_level_cats)} top-level categories to {categories_file}")
            save_to_file(top_level_cats, categories_file)
        
        # Save subcategories to their parent folders' category.json
        for parent_pk, subcats in parent_to_subcategories.items():
            if parent_pk == 'None' or not subcats:
                continue
            parent_pathstring = pk_to_pathstring.get(int(parent_pk))
            if not parent_pathstring:
                print(f"DEBUG: Skipping subcategories for parent PK {parent_pk} (no pathstring)")
                continue
            path_parts = parent_pathstring.split('/')
            dir_path = os.path.join(root_dir, *[sanitize_filename(p) for p in path_parts])
            subcats_file = os.path.join(dir_path, 'category.json')
            print(f"DEBUG: Saving {len(subcats)} subcategories to {subcats_file}")
            save_to_file(subcats, subcats_file)
        
        # Fetch all parts
        print(f"DEBUG: Fetching parts from {BASE_URL_PARTS}")
        parts = fetch_data(BASE_URL_PARTS)
        print(f"DEBUG: Retrieved {len(parts)} parts")
        
        # Save parts in their category folders
        for part in parts:
            cat_pk = part.get('category')
            part_name = part.get('name')
            if not cat_pk or not part_name:
                print(f"DEBUG: Skipping part {part_name or 'unknown'} (missing category or name)")
                continue
            pathstring = pk_to_pathstring.get(cat_pk)
            if not pathstring:
                print(f"DEBUG: Skipping part {part_name} (no pathstring for category PK {cat_pk})")
                continue
            path_parts = pathstring.split('/')
            dir_path = os.path.join(root_dir, *[sanitize_filename(p) for p in path_parts])
            part_filename = f"{sanitize_filename(part_name)}.json"
            part_file = os.path.join(dir_path, part_filename)
            print(f"DEBUG: Saving part {part_name} to {part_file}")
            save_to_file(part, part_file)
            
    except Exception as e:
        print(f"DEBUG: Error in main: {str(e)}")
        raise

if __name__ == "__main__":
    main()