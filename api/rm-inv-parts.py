# file name: rm-inv-parts.py
# Use InvenTree API to delete parts from an InvenTree instance based on JSON files in data/parts.
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
# Accepts Linux globbing patterns (e.g., '*.json', 'Paint/Yellow_Paint.json') to specify parts to delete.
# Patterns are relative to data/parts (e.g., 'Electronics/Passives/Capacitors/C_*_0402.json').
# Optional CLI flag --remove-json to delete part JSON files after successful deletion.
# Compatibility: Uses the part JSON files produced by inv-parts2json.py.
# Deletes parts by name and category, skipping non-existent parts.
# Example usage: 
#   python3 ./api/rm-inv-parts.py "Paint/Yellow_Paint.json" --remove-json
#   python3 ./api/rm-inv-parts.py "Electronics/Passives/Capacitors/C_*_0402.json"

import requests
import json
import os
import glob
import sys
import argparse

# API endpoints and authentication
BASE_URL = os.getenv("INVENTREE_URL") + "api/part/" if os.getenv("INVENTREE_URL") else None
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json"
}

def check_part_exists(name, category_pk):
    """Check if a part with the given name and category exists and return its pk if found."""
    print(f"DEBUG: Checking if part '{name}' exists in category {category_pk}")
    params = {'name': name, 'category': category_pk}
    
    try:
        response = requests.get(BASE_URL, headers=HEADERS, params=params)
        print(f"DEBUG: Part check response status: {response.status_code}")
        if response.status_code != 200:
            print(f"DEBUG: Failed to check part: {response.text}")
            raise Exception(f"Failed to check existing part: {response.status_code} - {response.text}")
        
        results = response.json()
        if isinstance(results, dict) and 'results' in results:
            print(f"DEBUG: Found {len(results['results'])} matching parts")
            return results['results'][0]['pk'] if results['results'] else None
        else:
            print(f"DEBUG: Direct list response with {len(results)} parts")
            return results[0]['pk'] if results else None
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Network error checking part: {str(e)}")
        raise Exception(f"Network error checking part: {str(e)}")

def delete_part(part_name, part_pk):
    """Delete a part by its pk."""
    print(f"DEBUG: Attempting to delete part '{part_name}' with PK {part_pk}")
    delete_url = f"{BASE_URL}{part_pk}/"
    
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

def process_part_file(part_file, remove_json=False):
    """Process a single part JSON file to delete the corresponding part."""
    print(f"DEBUG: Processing part file: {part_file}")
    try:
        with open(part_file, 'r', encoding='utf-8') as f:
            part_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"DEBUG: Invalid JSON in {part_file}: {str(e)}")
        return
    except Exception as e:
        print(f"DEBUG: Error reading {part_file}: {str(e)}")
        return
    
    # Handle both single object and list formats
    if isinstance(part_data, list):
        print(f"DEBUG: Part data is a list, using first item")
        part_data = part_data[0]
    
    part_name = part_data.get('name')
    category_pk = part_data.get('category')
    if not part_name or not category_pk:
        print(f"DEBUG: Skipping part with missing name or category in {part_file}")
        return
    
    # Check if part exists
    part_pk = check_part_exists(part_name, category_pk)
    if not part_pk:
        print(f"DEBUG: Part '{part_name}' does not exist in InvenTree, skipping")
        return
    
    # Delete the part
    delete_part(part_name, part_pk)
    
    # Optionally remove JSON file
    if remove_json:
        print(f"DEBUG: Removing part file {part_file}")
        try:
            os.remove(part_file)
            print(f"DEBUG: Successfully removed {part_file}")
        except Exception as e:
            print(f"DEBUG: Error removing {part_file}: {str(e)}")

def main():
    # Parse CLI arguments
    parser = argparse.ArgumentParser(description="Delete InvenTree parts based on data/parts JSON files.")
    parser.add_argument('patterns', nargs='*', help="Glob patterns for parts (e.g., '*.json', 'Paint/Yellow_Paint.json')")
    parser.add_argument('--remove-json', action='store_true', help="Remove part JSON files after deletion")
    args = parser.parse_args()
    
    print("DEBUG: Starting main function")
    if not TOKEN:
        print("DEBUG: INVENTREE_TOKEN not set")
        raise Exception("INVENTREE_TOKEN environment variable not set. Set it with: export INVENTREE_TOKEN='your-token'")
    if not BASE_URL:
        print("DEBUG: INVENTREE_URL not set")
        raise Exception("INVENTREE_URL environment variable not set. Set it with: export INVENTREE_URL='http://localhost:8000/'")
    
    print(f"DEBUG: Using BASE_URL: {BASE_URL}")
    dirname = "data/parts"
    
    print(f"DEBUG: Checking directory: {dirname}")
    if not os.path.exists(dirname):
        print(f"DEBUG: Directory '{dirname}' does not exist")
        raise FileNotFoundError(f"Directory '{dirname}' not found. Please ensure you're running the script from the correct location.")
    
    if not os.access(dirname, os.R_OK):
        print(f"DEBUG: Cannot read {dirname}")
        raise PermissionError(f"Insufficient permissions to read {dirname}")
    
    # Get glob patterns from command-line arguments
    print(f"DEBUG: Raw command-line arguments: {sys.argv[1:]}")
    glob_patterns = args.patterns
    print(f"DEBUG: Glob patterns provided: {glob_patterns}")
    if not glob_patterns:
        print("DEBUG: No glob patterns provided")
        raise Exception("Usage: python3 rm-inv-parts.py [glob_pattern...] [--remove-json]")
    
    try:
        part_files = []
        for pattern in glob_patterns:
            pattern_path = os.path.join(dirname, pattern)
            print(f"DEBUG: Expanding glob pattern: {pattern_path}")
            matched_files = glob.glob(pattern_path, recursive=True)
            print(f"DEBUG: Matched {len(matched_files)} files for pattern '{pattern}': {matched_files}")
            part_files.extend(matched_files)
        
        # Handle case where pattern is passed literally (e.g., no shell expansion)
        if not part_files:
            print(f"DEBUG: No files matched, attempting to interpret patterns as filenames")
            for pattern in glob_patterns:
                pattern_path = os.path.join(dirname, pattern)
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
            process_part_file(part_file, args.remove_json)
            
    except Exception as e:
        print(f"DEBUG: Error in main loop: {str(e)}")
        raise

if __name__ == "__main__":
    main()