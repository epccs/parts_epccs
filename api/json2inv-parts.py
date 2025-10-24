# The script traverses `data/parts` that the inv-parts2json.py script produced and recreates the categories and parts in another InvenTree instance.
# Skip parts and categories that already exist (based on name).
# Use API for Inventree with the goal of pushing data from json files to InvenTree `Parts and Part Categories`.
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation

import requests
import json
import os

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
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def check_category_exists(name, parent_pk=None):
    """Check if a category with given name and parent already exists."""
    print(f"DEBUG: Checking if category '{name}' exists with parent_pk={parent_pk}")
    params = {'name': name}
    if parent_pk is not None:
        params['parent'] = parent_pk
    
    try:
        response = requests.get(BASE_URL_CATEGORIES, headers=HEADERS, params=params)
        print(f"DEBUG: Category check response status: {response.status_code}")
        if response.status_code != 200:
            print(f"DEBUG: Failed to check category: {response.text}")
            raise Exception(f"Failed to check existing category: {response.status_code} - {response.text}")
        
        results = response.json()
        if isinstance(results, dict) and 'results' in results:
            print(f"DEBUG: Found {len(results['results'])} matching categories")
            return results['results']
        else:
            print(f"DEBUG: Direct list response with {len(results)} categories")
            return results
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error checking category: {str(e)}")
        raise Exception(f"Network error checking category: {str(e)}")

def check_part_exists(name, category_pk):
    """Check if a part with given name and category already exists."""
    print(f"DEBUG: Checking if part '{name}' exists in category {category_pk}")
    params = {'name': name, 'category': category_pk}
    
    try:
        response = requests.get(BASE_URL_PARTS, headers=HEADERS, params=params)
        print(f"DEBUG: Part check response status: {response.status_code}")
        if response.status_code != 200:
            print(f"DEBUG: Failed to check part: {response.text}")
            raise Exception(f"Failed to check existing part: {response.status_code} - {response.text}")
        
        results = response.json()
        if isinstance(results, dict) and 'results' in results:
            print(f"DEBUG: Found {len(results['results'])} matching parts")
            return results['results']
        else:
            print(f"DEBUG: Direct list response with {len(results)} parts")
            return results
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error checking part: {str(e)}")
        raise Exception(f"Network error checking part: {str(e)}")

def import_category(folder_path, parent_pk=None):
    """Import a category from folder, create it, import parts, then subcategories."""
    print(f"DEBUG: Processing category folder: {folder_path}")
    cat_file = os.path.join(folder_path, 'category.json')
    
    # Derive category name from folder
    cat_name = os.path.basename(folder_path)
    print(f"DEBUG: Derived category name: {cat_name}")
    
    # Check if category already exists
    existing_cats = check_category_exists(cat_name, parent_pk)
    if existing_cats:
        print(f"DEBUG: Category '{cat_name}' already exists with PK {existing_cats[0]['pk']}")
        new_pk = existing_cats[0]['pk']
    else:
        # Create category
        post_data = {'name': cat_name}
        try:
            print(f"DEBUG: Posting category to {BASE_URL_CATEGORIES}")
            post_data['parent'] = parent_pk
            resp = requests.post(BASE_URL_CATEGORIES, headers=HEADERS, json=post_data)
            print(f"DEBUG: Category creation response status: {resp.status_code}")
            if resp.status_code != 201:
                print(f"DEBUG: Failed to create category: {resp.text}")
                raise Exception(f"Failed to create category {cat_name}: {resp.status_code} - {resp.text}")
            new_cat = resp.json()
            new_pk = new_cat['pk']
            print(f"DEBUG: Created category '{new_cat['name']}' with PK {new_pk} (parent: {parent_pk})")
        except requests.exceptions.RequestException as e:
            print(f"DEBUG: Network error creating category: {str(e)}")
            raise Exception(f"Network error creating category {cat_name}: {str(e)}")
        except json.JSONDecodeError as e:
            print(f"DEBUG: Invalid JSON response creating category: {str(e)}")
            raise Exception(f"Invalid JSON response creating category {cat_name}: {str(e)}")
    
    # Import parts in this folder
    print(f"DEBUG: Scanning for parts in {folder_path}")
    for filename in os.listdir(folder_path):
        if filename == 'category.json' or not filename.endswith('.json'):
            print(f"DEBUG: Skipping non-part file: {filename}")
            continue
        part_path = os.path.join(folder_path, filename)
        print(f"DEBUG: Reading part file: {part_path}")
        try:
            with open(part_path, 'r', encoding='utf-8') as f:
                part_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"DEBUG: Invalid JSON in {part_path}: {str(e)}")
            continue
        except Exception as e:
            print(f"DEBUG: Error reading {part_path}: {str(e)}")
            continue
        
        # Handle both single object and list formats
        if isinstance(part_data, list):
            print(f"DEBUG: Part data is a list, using first item")
            part_data = part_data[0]
        
        # Prepare POST data
        post_part = {}
        allowed_fields = [
            'name', 'description', 'IPN', 'revision', 'keywords',
            'barcode', 'minimum_stock', 'units', 'assembly', 'component',
            'trackable', 'purchaseable', 'salable', 'virtual'
        ]
        for field in allowed_fields:
            if field in part_data:
                post_part[field] = part_data[field]
        post_part['category'] = new_pk
        print(f"DEBUG: Prepared part POST data: {post_part}")
        
        # Check if part already exists
        existing_parts = check_part_exists(post_part['name'], new_pk)
        if existing_parts:
            print(f"DEBUG: Part '{post_part['name']}' already exists in category {new_pk}")
            continue
        
        # Create part
        try:
            print(f"DEBUG: Posting part to {BASE_URL_PARTS}")
            resp_part = requests.post(BASE_URL_PARTS, headers=HEADERS, json=post_part)
            print(f"DEBUG: Part creation response status: {resp_part.status_code}")
            if resp_part.status_code != 201:
                print(f"DEBUG: Failed to create part from {filename}: {resp_part.text}")
                continue
            new_part = resp_part.json()
            print(f"DEBUG: Created part '{new_part['name']}' with PK {new_part['pk']} in category {new_pk}")
        except Exception as e:
            print(f"DEBUG: Error creating part from {filename}: {str(e)}")
            continue
    
    # Load subcategories from category.json
    if not os.path.exists(cat_file):
        print(f"DEBUG: No category.json in {folder_path}, assuming leaf category")
        subcategories = []
    else:
        print(f"DEBUG: Reading category file: {cat_file}")
        try:
            with open(cat_file, 'r', encoding='utf-8') as f:
                subcategories = json.load(f)
            print(f"DEBUG: Loaded {len(subcategories)} subcategories from {cat_file}")
        except json.JSONDecodeError as e:
            print(f"DEBUG: Invalid JSON in {cat_file}: {str(e)}")
            raise Exception(f"Invalid JSON in {cat_file}: {str(e)}")
        except Exception as e:
            print(f"DEBUG: Error reading {cat_file}: {str(e)}")
            raise Exception(f"Error reading {cat_file}: {str(e)}")
    
    # Recurse into subfolders for subcategories
    print(f"DEBUG: Scanning for subcategories in {folder_path}")
    for subdir in os.listdir(folder_path):
        sub_path = os.path.join(folder_path, subdir)
        if os.path.isdir(sub_path):
            print(f"DEBUG: Found subcategory folder: {sub_path}")
            import_category(sub_path, new_pk)
        else:
            print(f"DEBUG: Skipping non-directory in subcategory scan: {sub_path}")

def main():
    print("DEBUG: Starting main function")
    if not TOKEN:
        print("DEBUG: INVENTREE_TOKEN not set")
        raise Exception("INVENTREE_TOKEN environment variable not set. Set it with: export INVENTREE_TOKEN='your-token'")
    if not BASE_URL:
        print("DEBUG: INVENTREE_URL not set")
        raise Exception("INVENTREE_URL environment variable not set. Set it with: export INVENTREE_URL='http://localhost:8000/'")

    root_dir = 'data/parts'
    if not os.path.exists(root_dir):
        print(f"DEBUG: Root directory '{root_dir}' does not exist")
        raise FileNotFoundError(f"'{root_dir}' directory not found. Please ensure you're running the script from the correct location.")
    
    print(f"DEBUG: Checking permissions for {root_dir}")
    if not os.access(root_dir, os.R_OK | os.X_OK):
        print(f"DEBUG: Cannot read or access {root_dir}")
        raise PermissionError(f"Insufficient permissions to access {root_dir}")
    
    print(f"DEBUG: Scanning root directory: {root_dir}")
    try:
        dir_contents = os.listdir(root_dir)
        print(f"DEBUG: Contents of {root_dir}: {dir_contents}")
        if not dir_contents:
            print(f"DEBUG: No items found in {root_dir}, exiting")
            return
        
        for top_dir in dir_contents:
            top_path = os.path.join(root_dir, top_dir)
            print(f"DEBUG: Evaluating item: {top_path}")
            if os.path.isdir(top_path):
                print(f"DEBUG: Processing top-level directory: {top_path}")
                import_category(top_path, None)
            else:
                print(f"DEBUG: Skipping non-directory: {top_path}")
    except PermissionError as e:
        print(f"DEBUG: Permission error accessing {root_dir}: {str(e)}")
        raise
    except Exception as e:
        print(f"DEBUG: Error in main loop: {str(e)}")
        raise

if __name__ == "__main__":
    main()
