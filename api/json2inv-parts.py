#!/usr/bin/env python3
# file name: json2inv-parts.py
# Use InvenTree API for Parts with the goal of pulling data from a folder `data/parts` and populating another InvenTree instance.
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
# Each part was exported from InvenTree into a JSON file under the `data/parts` folder.
# Supports individual file imports via command-line arguments with globbing (e.g., 'Electronics/Passives/Capacitors/C_*.json').
# If no arguments are provided, imports all JSON files in data/parts recursively (equivalent to '**/*.json').
# Checks and creates categories as needed, preferring JSON category if valid.
# Optional --force-ipn flag to generate default IPN from part name if null or missing.
# Optional --force flag to overwrite existing parts by deleting them after checking dependencies.
# Optional --clean-dependencies flag to delete dependencies (stock, BOMs, test templates, build orders, sales orders, attachments) with multiple confirmation prompts.
# Compatibility: This program is compatible with the export of inv-parts2json.py.
# Example usage:
#   python3 ./api/json2inv-parts.py "Electronics/Passives/Capacitors/C_*.json" --force-ipn --force --clean-dependencies
#   python3 ./api/json2inv-parts.py "Paint/Yellow_Paint.json" --force-ipn
#   python3 ./api/json2inv-parts.py  # Imports all parts
#   python3 ./api/json2inv-parts.py "**/*.json" --force-ipn --force

import requests
import json
import os
import glob
import sys
import argparse

# API endpoints and authentication
if os.getenv("INVENTREE_URL"):
    BASE_URL = os.getenv("INVENTREE_URL")
    BASE_URL_PARTS = BASE_URL + "api/part/"
    BASE_URL_CATEGORIES = BASE_URL + "api/part/category/"
    BASE_URL_BOM = BASE_URL + "api/bom/"
    BASE_URL_TEST = BASE_URL + "api/part/test-template/"
    BASE_URL_STOCK = BASE_URL + "api/stock/"
    BASE_URL_BUILD = BASE_URL + "api/build/"
    BASE_URL_SALES = BASE_URL + "api/sales/order/"
    BASE_URL_ATTACHMENTS = BASE_URL + "api/part/attachment/"
else:
    BASE_URL = None
    BASE_URL_PARTS = None
    BASE_URL_CATEGORIES = None
    BASE_URL_BOM = None
    BASE_URL_TEST = None
    BASE_URL_STOCK = None
    BASE_URL_BUILD = None
    BASE_URL_SALES = None
    BASE_URL_ATTACHMENTS = None
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

def check_part_exists(name, ipn, category_pk):
    """Check if a part with given name, IPN, and category already exists."""
    print(f"DEBUG: Checking if part '{name}' with IPN '{ipn}' exists in category {category_pk}")
    params = {'name': name, 'category': category_pk}
    if ipn:
        params['IPN'] = ipn
    
    try:
        response = requests.get(BASE_URL_PARTS, headers=HEADERS, params=params)
        print(f"DEBUG: Part check response status: {response.status_code}")
        if response.status_code != 200:
            print(f"DEBUG: Failed to check part: {response.text}")
            raise Exception(f"Failed to check existing part: {response.status_code} - {response.text}")
        
        results = response.json()
        if isinstance(results, dict) and 'results' in results:
            results = results['results']
            print(f"DEBUG: Found {len(results)} matching parts")
            if results:
                print(f"DEBUG: Existing part details: {[{k: v for k, v in part.items() if k in ['pk', 'name', 'IPN', 'active']} for part in results]}")
            return results
        else:
            print(f"DEBUG: Direct list response with {len(results)} parts")
            if results:
                print(f"DEBUG: Existing part details: {[{k: v for k, v in part.items() if k in ['pk', 'name', 'IPN', 'active']} for part in results]}")
            return results
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error checking part: {str(e)}")
        raise Exception(f"Network error checking part: {str(e)}")

def check_dependencies(part_pk):
    """Check and return dependencies for a part."""
    dependencies = {'stock': [], 'bom': [], 'test': [], 'build': [], 'sales': [], 'attachments': []}
    
    for endpoint, key in [
        (BASE_URL_STOCK, 'stock'),
        (BASE_URL_BOM, 'bom'),
        (BASE_URL_TEST, 'test'),
        (BASE_URL_BUILD, 'build'),
        (BASE_URL_SALES, 'sales'),
        (BASE_URL_ATTACHMENTS, 'attachments')
    ]:
        try:
            response = requests.get(f"{endpoint}?part={part_pk}", headers=HEADERS)
            print(f"DEBUG: Dependency check for {key} response status: {response.status_code}")
            if response.status_code == 200:
                results = response.json()
                count = results['count'] if isinstance(results, dict) and 'count' in results else len(results)
                if count > 0:
                    dependencies[key] = results['results'] if isinstance(results, dict) else results
                    print(f"DEBUG: Found {count} {key} dependencies for part {part_pk}")
        except requests.exceptions.RequestException as e:
            print(f"DEBUG: Network error checking {key} dependencies: {str(e)}")
    
    return dependencies

def delete_dependencies(part_name, part_pk, clean_dependencies):
    """Delete dependencies for a part if clean_dependencies is True."""
    if not clean_dependencies:
        return False
    
    dependencies = check_dependencies(part_pk)
    total_deps = sum(len(items) for items in dependencies.values())
    if total_deps == 0:
        print(f"DEBUG: No dependencies found for part '{part_name}' (PK {part_pk})")
        return True
    
    print(f"WARNING: Found {total_deps} dependencies for part '{part_name}' (PK {part_pk}): {dependencies}")
    print("This operation will permanently delete the following dependencies:")
    for key, items in dependencies.items():
        if items:
            print(f"  - {len(items)} {key} items: {[item.get('pk') for item in items]}")
    
    # First confirmation
    confirm1 = input(f"Type 'YES' to confirm deletion of {total_deps} dependencies for '{part_name}' (PK {part_pk}): ")
    if confirm1 != 'YES':
        print(f"DEBUG: Deletion cancelled for part '{part_name}' (first confirmation failed)")
        return False
    
    # Second confirmation
    confirm2 = input(f"Type 'CONFIRM' to permanently delete dependencies for '{part_name}' (PK {part_pk}): ")
    if confirm2 != 'CONFIRM':
        print(f"DEBUG: Deletion cancelled for part '{part_name}' (second confirmation failed)")
        return False
    
    # Delete dependencies
    for key, items in dependencies.items():
        for item in items:
            item_pk = item.get('pk')
            endpoint = f"{BASE_URL_STOCK}{item_pk}/" if key == 'stock' else \
                      f"{BASE_URL_BOM}{item_pk}/" if key == 'bom' else \
                      f"{BASE_URL_TEST}{item_pk}/" if key == 'test' else \
                      f"{BASE_URL_BUILD}{item_pk}/" if key == 'build' else \
                      f"{BASE_URL_SALES}{item_pk}/" if key == 'sales' else \
                      f"{BASE_URL_ATTACHMENTS}{item_pk}/"
            try:
                response = requests.delete(endpoint, headers=HEADERS)
                print(f"DEBUG: Deletion of {key} item PK {item_pk} response status: {response.status_code}")
                if response.status_code != 204:
                    print(f"DEBUG: Failed to delete {key} item PK {item_pk}: {response.text}")
                    raise Exception(f"Failed to delete {key} item PK {item_pk}")
                print(f"DEBUG: Successfully deleted {key} item PK {item_pk} for part '{part_name}'")
            except requests.exceptions.RequestException as e:
                print(f"DEBUG: Network error deleting {key} item PK {item_pk}: {str(e)}")
                raise Exception(f"Network error deleting {key} item PK {item_pk}")
    
    return True

def delete_part(part_name, part_pk, clean_dependencies):
    """Delete a part by its PK after checking and optionally deleting dependencies."""
    print(f"DEBUG: Attempting to delete part '{part_name}' with PK {part_pk}")
    
    # Check and delete dependencies if requested
    if not delete_dependencies(part_name, part_pk, clean_dependencies):
        raise Exception(f"Cannot delete part '{part_name}' due to dependencies")
    
    delete_url = f"{BASE_URL_PARTS}{part_pk}/"
    try:
        response = requests.delete(delete_url, headers=HEADERS)
        print(f"DEBUG: Part deletion response status: {response.status_code}")
        if response.status_code != 204:
            print(f"DEBUG: Failed to delete part '{part_name}': {response.text}")
            raise Exception(f"Failed to delete part '{part_name}': {response.status_code} - {response.text}")
        print(f"DEBUG: Successfully deleted part '{part_name}' with PK {part_pk}")
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error deleting part '{part_name}': {str(e)}")
        raise Exception(f"Network error deleting part '{part_name}': {str(e)}")

def create_category_hierarchy(folder_path, parent_pk=None):
    """Create the category hierarchy for a given folder path, returning the leaf category PK."""
    print(f"DEBUG: Creating category hierarchy for path: {folder_path}")
    path_parts = os.path.relpath(folder_path, 'data/parts').split(os.sep)
    current_pk = parent_pk
    
    for part in path_parts:
        if part == '.':
            continue
        cat_name = part
        print(f"DEBUG: Processing category segment: {cat_name}")
        
        existing_cats = check_category_exists(cat_name, current_pk)
        if existing_cats:
            print(f"DEBUG: Category '{cat_name}' already exists with PK {existing_cats[0]['pk']}")
            current_pk = existing_cats[0]['pk']
        else:
            post_data = {'name': cat_name, 'parent': current_pk}
            try:
                print(f"DEBUG: Posting category to {BASE_URL_CATEGORIES}")
                resp = requests.post(BASE_URL_CATEGORIES, headers=HEADERS, json=post_data)
                print(f"DEBUG: Category creation response status: {resp.status_code}")
                if resp.status_code != 201:
                    print(f"DEBUG: Failed to create category: {resp.text}")
                    raise Exception(f"Failed to create category {cat_name}: {resp.status_code} - {resp.text}")
                new_cat = resp.json()
                current_pk = new_cat['pk']
                print(f"DEBUG: Created category '{new_cat['name']}' with PK {current_pk}")
            except requests.exceptions.RequestException as e:
                print(f"DEBUG: Network error creating category: {str(e)}")
                raise Exception(f"Network error creating category {cat_name}: {str(e)}")
            except json.JSONDecodeError as e:
                print(f"DEBUG: Invalid JSON response creating category: {str(e)}")
                raise Exception(f"Invalid JSON response creating category {cat_name}: {str(e)}")
    
    return current_pk

def import_part(part_path, force_ipn=False, force=False, clean_dependencies=False):
    """Import a single part from a JSON file."""
    print(f"DEBUG: Reading part file: {part_path}")
    try:
        with open(part_path, 'r', encoding='utf-8') as f:
            part_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"DEBUG: Invalid JSON in {part_path}: {str(e)}")
        return
    except Exception as e:
        print(f"DEBUG: Error reading {part_path}: {str(e)}")
        return
    
    # Handle both single object and list formats
    if isinstance(part_data, list):
        print(f"DEBUG: Part data is a list, using first item")
        part_data = part_data[0]
    
    # Prepare POST data
    post_part = {}
    allowed_fields = [
        'name', 'description', 'IPN', 'revision', 'keywords',
        'barcode', 'minimum_stock', 'units', 'assembly', 'component',
        'trackable', 'purchaseable', 'salable', 'virtual', 'active'
    ]
    for field in allowed_fields:
        if field in part_data:
            post_part[field] = part_data[field]
    
    if not post_part.get('name'):
        print(f"DEBUG: Skipping part with missing name in {part_path}")
        return
    
    # Ensure active is true
    post_part['active'] = True
    
    # Handle null or missing IPN
    ipn = post_part.get('IPN')
    if force_ipn and (ipn is None or not ipn):
        ipn = post_part['name'][:50]  # Use part name as IPN, truncated to 50 chars
        post_part['IPN'] = ipn
        print(f"DEBUG: Generated default IPN: {ipn} for part {post_part['name']}")
    
    # Determine category: prefer JSON category if valid, else use folder path
    category_pk = part_data.get('category')
    if category_pk:
        try:
            print(f"DEBUG: Checking JSON category PK {category_pk}")
            response = requests.get(f"{BASE_URL_CATEGORIES}{category_pk}/", headers=HEADERS)
            print(f"DEBUG: Category check response status: {response.status_code}")
            if response.status_code == 200:
                print(f"DEBUG: Using JSON category PK {category_pk}")
            else:
                print(f"DEBUG: JSON category PK {category_pk} not found, using folder path")
                category_pk = None
        except requests.exceptions.RequestException:
            print(f"DEBUG: Error checking JSON category PK {category_pk}, using folder path")
            category_pk = None
    
    if not category_pk:
        folder_path = os.path.dirname(part_path)
        category_pk = create_category_hierarchy(folder_path)
    
    post_part['category'] = category_pk
    print(f"DEBUG: Prepared part POST data: {post_part}")
    
    # Check if part already exists
    existing_parts = check_part_exists(post_part['name'], ipn, category_pk)
    if existing_parts and force:
        for part in existing_parts:
            print(f"DEBUG: Forcing deletion of existing part '{part['name']}' with PK {part['pk']}")
            delete_part(part['name'], part['pk'], clean_dependencies)
    elif existing_parts:
        print(f"DEBUG: Part '{post_part['name']}' already exists in category {category_pk}")
        return
    
    # Create part
    try:
        print(f"DEBUG: Posting part to {BASE_URL_PARTS}")
        resp_part = requests.post(BASE_URL_PARTS, headers=HEADERS, json=post_part)
        print(f"DEBUG: Part creation response status: {resp_part.status_code}")
        if resp_part.status_code != 201:
            print(f"DEBUG: Failed to create part from {part_path}: {resp_part.text}")
            return
        new_part = resp_part.json()
        print(f"DEBUG: Created part '{new_part['name']}' with PK {new_part['pk']} in category {category_pk}")
    except Exception as e:
        print(f"DEBUG: Error creating part from {part_path}: {str(e)}")
        return

def main():
    # Parse CLI arguments
    parser = argparse.ArgumentParser(description="Import InvenTree parts from data/parts JSON files.")
    parser.add_argument('patterns', nargs='*', default=['**/*.json'], help="Glob patterns for parts (e.g., 'Electronics/Passives/Capacitors/C_*.json', 'Paint/Yellow_Paint.json'); defaults to '**/*.json'")
    parser.add_argument('--force-ipn', action='store_true', help="Generate default IPN from part name if null or missing")
    parser.add_argument('--force', action='store_true', help="Overwrite existing parts by deleting them after checking dependencies")
    parser.add_argument('--clean-dependencies', action='store_true', help="Delete dependencies (stock, BOMs, test templates, build orders, sales orders, attachments) with confirmation prompts")
    args = parser.parse_args()
    
    print("DEBUG: Starting main function")
    if not TOKEN:
        print("DEBUG: INVENTREE_TOKEN not set")
        raise Exception("INVENTREE_TOKEN environment variable not set. Set it with: export INVENTREE_TOKEN='your-token'")
    if not BASE_URL:
        print("DEBUG: INVENTREE_URL not set")
        raise Exception("INVENTREE_URL environment variable not set. Set it with: export INVENTREE_URL='http://localhost:8000/'")
    
    root_dir = 'data/parts'
    print(f"DEBUG: Checking directory: {root_dir}")
    if not os.path.exists(root_dir):
        print(f"DEBUG: Root directory '{root_dir}' does not exist")
        raise FileNotFoundError(f"'{root_dir}' directory not found. Please ensure you're running the script from the correct location.")
    
    print(f"DEBUG: Checking permissions for {root_dir}")
    if not os.access(root_dir, os.R_OK):
        print(f"DEBUG: Cannot read {root_dir}")
        raise PermissionError(f"Insufficient permissions to read {root_dir}")
    
    try:
        print(f"DEBUG: Glob patterns provided: {args.patterns}")
        part_files = []
        for pattern in args.patterns:
            pattern_path = os.path.join(root_dir, pattern)
            print(f"DEBUG: Expanding glob pattern: {pattern_path}")
            matched_files = glob.glob(pattern_path, recursive=True)
            print(f"DEBUG: Matched {len(matched_files)} files for pattern '{pattern}': {matched_files}")
            part_files.extend(matched_files)
        
        # Handle case where pattern is a literal file
        if not part_files:
            print(f"DEBUG: No files matched, attempting to interpret patterns as filenames")
            for pattern in args.patterns:
                pattern_path = os.path.join(root_dir, pattern)
                if os.path.isfile(pattern_path) and pattern_path.endswith('.json'):
                    print(f"DEBUG: Adding literal file: {pattern_path}")
                    part_files.append(pattern_path)
        
        part_files = sorted(set(part_files))  # Remove duplicates and sort
        print(f"DEBUG: Total unique part files to process: {len(part_files)}: {part_files}")
        if not part_files:
            print(f"DEBUG: No JSON files matched or found, exiting")
            return
        
        for part_file in part_files:
            if not part_file.endswith('.json') or os.path.basename(part_file) == 'category.json':
                print(f"DEBUG: Skipping non-part file: {part_file}")
                continue
            import_part(part_file, args.force_ipn, args.force, args.clean_dependencies)
            
    except PermissionError as e:
        print(f"DEBUG: Permission error accessing {root_dir}: {str(e)}")
        raise
    except Exception as e:
        print(f"DEBUG: Error in main loop: {str(e)}")
        raise

if __name__ == "__main__":
    main()