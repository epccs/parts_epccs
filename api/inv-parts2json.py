# file name: inv-parts2json.py
# Use API for Parts and Part Categories with the goal of pulling data from InvenTree to populate a hierarchical structure of categories and parts.
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
# Use each category and any subcategories to create a file system structure under a 'data/parts' folder
# Each folder (representing a category) should contain a category.json file that lists all immediate
# subcategories of that folder’s category (not all categories globally).
# Sanitize the category (and subcategories) for both the filename and JSON by replacing spaces with underscores
# and removing dots (e.g., Acme Inc. becomes Acme_Inc), also replace invalid chars.
# Sanitize the part for both the filename and JSON by replacing spaces with underscores and dots with commas
# (e.g., C 0.1uF 0402 becomes C_0,1uF_0402), also replace invalid chars.
# Set image and thumbnail fields to "" for parts to avoid issues with image paths.
# Populate the parts in the proper category file structure as a separate JSON file named after the sanitized part name.
# Import Compatibility: The structure is compatible with json2inv-parts.py to recreate the categories and parts in another InvenTree instance.

import requests
import json
import os
import re

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

def sanitize_category_name(name):
    """Sanitize category name for JSON and folder name by replacing spaces with underscores and removing dots."""
    print(f"DEBUG: Sanitizing category name: {name}")
    sanitized = name.replace(' ', '_').replace('.', '')
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', sanitized.strip())  # Replace invalid chars
    print(f"DEBUG: Sanitized category name to: {sanitized}")
    return sanitized

def sanitize_part_name(name):
    """Sanitize part name for JSON and filename by replacing spaces with underscores and dots with commas."""
    print(f"DEBUG: Sanitizing part name: {name}")
    sanitized = name.replace(' ', '_').replace('.', ',')
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', sanitized.strip())  # Replace invalid chars
    print(f"DEBUG: Sanitized part name to: {sanitized}")
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
            name = category.get('name')
            pathstring = category.get('pathstring')
            parent_pk = str(category.get('parent')) if category.get('parent') is not None else 'None'
            if not pathstring or not pk or not name:
                print(f"DEBUG: Skipping category {name or 'unknown'} (missing pk, name, or pathstring)")
                continue
            
            # Sanitize category name and update pathstring
            sanitized_name = sanitize_category_name(name)
            category_modified = category.copy()
            category_modified['name'] = sanitized_name
            category_modified['image'] = ""
            path_parts = pathstring.split('/')
            path_parts[-1] = sanitized_name  # Update last part with sanitized name
            sanitized_pathstring = '/'.join(path_parts)
            pk_to_pathstring[pk] = sanitized_pathstring
            print(f"DEBUG: Mapping category PK {pk} to sanitized pathstring {sanitized_pathstring}")
            
            if parent_pk not in parent_to_subcategories:
                parent_to_subcategories[parent_pk] = []
            parent_to_subcategories[parent_pk].append(category_modified)
        
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
            dir_path = os.path.join(root_dir, *[sanitize_category_name(p) for p in path_parts])
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
            # Sanitize part name
            sanitized_part_name = sanitize_part_name(part_name)
            part_modified = part.copy()
            part_modified['name'] = sanitized_part_name
            part_modified['image'] = ""
            part_modified['thumbnail'] = ""
            
            path_parts = pathstring.split('/')
            dir_path = os.path.join(root_dir, *[sanitize_category_name(p) for p in path_parts])
            part_filename = f"{sanitized_part_name}.json"
            part_file = os.path.join(dir_path, part_filename)
            print(f"DEBUG: Saving part {sanitized_part_name} to {part_file}")
            save_to_file(part_modified, part_file)
            
    except Exception as e:
        print(f"DEBUG: Error in main: {str(e)}")
        raise

if __name__ == "__main__":
    main()