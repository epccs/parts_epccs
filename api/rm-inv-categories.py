# file name: rm-inv-categories.py
# Use InvenTree API to delete categories from an InvenTree instance based on the hierarchical structure in data/parts.
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
# Accepts Linux globbing patterns (e.g., '*', 'Electronics/Passives/*') to specify categories to delete (folders).
# Only deletes categories if they are empty (no parts under them).
# Optional CLI flag --remove-json to delete the category.json files after successful deletion.
# Compatibility: Uses the structure produced by inv-parts2json.py.

import requests
import json
import os
import glob
import sys
import argparse

# API endpoints and authentication
BASE_URL_CATEGORIES = os.getenv("INVENTREE_URL") + "api/part/category/" if os.getenv("INVENTREE_URL") else None
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json"
}

def check_category_exists(name, parent_pk=None):
    """Check if a category with the given name and parent exists and return its pk if found."""
    print(f"DEBUG: Checking if category '{name}' exists with parent {parent_pk}")
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
            return results['results'][0]['pk'] if results['results'] else None
        else:
            print(f"DEBUG: Direct list response with {len(results)} categories")
            return results[0]['pk'] if results else None
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error checking category: {str(e)}")
        raise Exception(f"Network error checking category: {str(e)}")

def is_category_empty(category_pk):
    """Check if a category is empty (no parts in it or its subcategories)."""
    print(f"DEBUG: Checking if category PK {category_pk} is empty")
    params = {'category': category_pk, 'cascade': True}  # Cascade to check subcategories
    try:
        response = requests.get(os.getenv("INVENTREE_URL") + "api/part/", headers=HEADERS, params=params)
        print(f"DEBUG: Part count response status: {response.status_code}")
        if response.status_code != 200:
            print(f"DEBUG: Failed to check part count: {response.text}")
            raise Exception(f"Failed to check part count for category {category_pk}")
        
        results = response.json()
        count = results['count'] if isinstance(results, dict) and 'count' in results else len(results)
        print(f"DEBUG: Found {count} parts in category {category_pk} (including subcategories)")
        return count == 0
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error checking category emptiness: {str(e)}")
        raise Exception(f"Network error checking category emptiness: {str(e)}")

def delete_category(category_name, category_pk):
    """Delete a category by its pk."""
    print(f"DEBUG: Attempting to delete category '{category_name}' with PK {category_pk}")
    delete_url = f"{BASE_URL_CATEGORIES}{category_pk}/"
    
    try:
        response = requests.delete(delete_url, headers=HEADERS)
        print(f"DEBUG: Category deletion response status: {response.status_code}")
        if response.status_code != 204:
            print(f"DEBUG: Failed to delete category '{category_name}': {response.text}")
            raise Exception(f"Failed to delete category '{category_name}': {response.status_code} - {response.text}")
        print(f"DEBUG: Successfully deleted category '{category_name}' with PK {category_pk}")
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error deleting category '{category_name}': {str(e)}")
        raise Exception(f"Network error deleting category '{category_name}': {str(e)}")

def process_category_folder(category_folder, parent_pk=None, remove_json=False):
    """Process a category folder to delete the corresponding category if empty."""
    print(f"DEBUG: Processing category folder: {category_folder} with parent PK {parent_pk}")
    category_name = os.path.basename(category_folder)
    
    # Check if category exists
    category_pk = check_category_exists(category_name, parent_pk)
    if not category_pk:
        print(f"DEBUG: Category '{category_name}' does not exist in InvenTree, skipping")
        return
    
    # Check if category is empty
    if not is_category_empty(category_pk):
        print(f"DEBUG: Category '{category_name}' is not empty (has parts), skipping deletion")
        return
    
    # Delete the category
    delete_category(category_name, category_pk)
    
    # Optionally remove category.json
    if remove_json:
        cat_file = os.path.join(category_folder, 'category.json')
        if os.path.exists(cat_file):
            print(f"DEBUG: Removing category.json from {category_folder}")
            os.remove(cat_file)
        else:
            print(f"DEBUG: No category.json found in {category_folder}")

def main():
    # Parse CLI arguments
    parser = argparse.ArgumentParser(description="Delete InvenTree categories based on data/parts structure.")
    parser.add_argument('patterns', nargs='*', help="Glob patterns for categories (e.g., '*', 'Electronics/Passives/*')")
    parser.add_argument('--remove-json', action='store_true', help="Remove category.json files after deletion")
    args = parser.parse_args()
    
    print("DEBUG: Starting main function")
    if not TOKEN:
        print("DEBUG: INVENTREE_TOKEN not set")
        raise Exception("INVENTREE_TOKEN environment variable not set. Set it with: export INVENTREE_TOKEN='your-token'")
    if not BASE_URL_CATEGORIES:
        print("DEBUG: INVENTREE_URL not set")
        raise Exception("INVENTREE_URL environment variable not set. Set it with: export INVENTREE_URL='http://localhost:8000/'")
    
    print(f"DEBUG: Using BASE_URL_CATEGORIES: {BASE_URL_CATEGORIES}")
    dirname = "data/parts"
    
    print(f"DEBUG: Checking directory: {dirname}")
    if not os.path.exists(dirname):
        print(f"DEBUG: Directory '{dirname}' does not exist")
        raise FileNotFoundError(f"Directory '{dirname}' not found. Please ensure you're running the script from the correct location.")
    
    if not os.access(dirname, os.R_OK):
        print(f"DEBUG: Cannot read {dirname}")
        raise PermissionError(f"Insufficient permissions to read {dirname}")
    
    # Get glob patterns from command-line arguments
    glob_patterns = args.patterns
    print(f"DEBUG: Glob patterns provided: {glob_patterns}")
    if not glob_patterns:
        print("DEBUG: No glob patterns provided")
        raise Exception("Usage: python3 rm-inv-categories.py [glob_pattern...] [--remove-json]")
    
    try:
        category_folders = []
        for pattern in glob_patterns:
            pattern_path = os.path.join(dirname, pattern)
            print(f"DEBUG: Expanding glob pattern: {pattern_path}")
            matched_folders = glob.glob(pattern_path, recursive=True)
            matched_folders = [f for f in matched_folders if os.path.isdir(f)]
            print(f"DEBUG: Matched {len(matched_folders)} folders for pattern '{pattern}': {matched_folders}")
            category_folders.extend(matched_folders)
        
        category_folders = sorted(set(category_folders))  # Remove duplicates and sort
        print(f"DEBUG: Total unique category folders to process: {len(category_folders)}: {category_folders}")
        if not category_folders:
            print(f"DEBUG: No folders matched the provided patterns, exiting")
            return
        
        # Process categories bottom-up (delete leaves first)
        category_folders.sort(key=lambda x: -x.count(os.sep))  # Sort by depth (deepest first)
        print(f"DEBUG: Processing categories in bottom-up order: {category_folders}")
        
        for category_folder in category_folders:
            process_category_folder(category_folder, None, args.remove_json)
            
    except Exception as e:
        print(f"DEBUG: Error in main loop: {str(e)}")
        raise

if __name__ == "__main__":
    main()