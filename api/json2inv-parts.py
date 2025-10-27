#!/usr/bin/env python3
# file name: json2inv-parts.py
# Use InvenTree API for Parts with the goal of pulling data from a folder `data/parts` and populating another InvenTree instance.
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
# Each part was exported from InvenTree into a JSON file under the `data/parts` folder.
# Supports individual file imports via command-line arguments with globbing (e.g., 'Electronics/Passives/Capacitors/C_*.json').
# If no arguments are provided, imports all JSON files in data/parts recursively (equivalent to '**/*.json').
# Checks and creates categories as needed for the imported parts.
# Optional --force-ipn flag to generate a default IPN when null or missing (uses part name).
# Compatibility: This program is compatible with the export of inv-parts2json.py.
# Example usage:
#   python3 ./api/json2inv-parts.py "Electronics/Passives/Capacitors/C_*.json" --force-ipn
#   python3 ./api/json2inv-parts.py "Paint/Yellow_Paint.json" --force-ipn
#   python3 ./api/json2inv-parts.py  # Imports all parts
#   python3 ./api/json2inv-parts.py "**/*.json" --force-ipn

# WIP: this has known issues with parts not importing correctly. 

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
                print(f"DEBUG: Created category '{new_cat['name']}' with PK {current_pk} (parent: {current_pk})")
            except requests.exceptions.RequestException as e:
                print(f"DEBUG: Network error creating category: {str(e)}")
                raise Exception(f"Network error creating category {cat_name}: {str(e)}")
            except json.JSONDecodeError as e:
                print(f"DEBUG: Invalid JSON response creating category: {str(e)}")
                raise Exception(f"Invalid JSON response creating category {cat_name}: {str(e)}")
    
    return current_pk

def import_part(part_path, force_ipn=False):
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
        'trackable', 'purchaseable', 'salable', 'virtual'
    ]
    for field in allowed_fields:
        if field in part_data:
            post_part[field] = part_data[field]
    
    if not post_part.get('name'):
        print(f"DEBUG: Skipping part with missing name in {part_path}")
        return
    
    # Handle null or missing IPN
    if force_ipn and (post_part.get('IPN') is None or not post_part.get('IPN')):
        post_part['IPN'] = post_part['name'][:50]  # Use part name as IPN, truncated to 50 chars
        print(f"DEBUG: Generated default IPN: {post_part['IPN']} for part {post_part['name']}")
    
    # Create category hierarchy
    folder_path = os.path.dirname(part_path)
    category_pk = create_category_hierarchy(folder_path)
    post_part['category'] = category_pk
    print(f"DEBUG: Prepared part POST data: {post_part}")
    
    # Check if part already exists
    existing_parts = check_part_exists(post_part['name'], category_pk)
    if existing_parts:
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
            import_part(part_file, args.force_ipn)
            
    except PermissionError as e:
        print(f"DEBUG: Permission error accessing {root_dir}: {str(e)}")
        raise
    except Exception as e:
        print(f"DEBUG: Error in main loop: {str(e)}")
        raise

if __name__ == "__main__":
    main()