import requests
import json
import os

# API endpoint and authentication (for Parts and Part Categories)
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
# Use each category and any subcategories to create a file system structure under a 'data/parts' folder
# Save the category (and subcategories) as a category.json file in the parent folder.
# populate the parts in the proper category file structure as a separate JSON file named after the part
BASE_URL_PARTS = "http://localhost:8000/api/part/"
BASE_URL_CATEGORIES = "http://localhost:8000/api/part/category/"
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def check_category_exists(name, parent_pk=None):
    """Check if a category with given name and parent already exists."""
    params = {'name': name}
    if parent_pk is not None:
        params['parent'] = parent_pk
    
    response = requests.get(BASE_URL_CATEGORIES, headers=HEADERS, params=params)
    if response.status_code != 200:
        raise Exception(f"Failed to check existing category: {response.status_code} - {response.text}")
    
    results = response.json()
    return results['results'] if isinstance(results, dict) else results

def check_part_exists(name, category_pk):
    """Check if a part with given name and category already exists."""
    params = {'name': name, 'category': category_pk}
    
    response = requests.get(BASE_URL_PARTS, headers=HEADERS, params=params)
    if response.status_code != 200:
        raise Exception(f"Failed to check existing part: {response.status_code} - {response.text}")
    
    results = response.json()
    return results['results'] if isinstance(results, dict) else results

def import_category(folder_path, parent_pk=None):
    """Recursively import a category from folder, create it, import parts, then subcategories."""
    cat_file = os.path.join(folder_path, 'category.json')
    if not os.path.exists(cat_file):
        raise FileNotFoundError(f"No category.json in {folder_path}")
    
    try:
        with open(cat_file, 'r', encoding='utf-8') as f:
            cat_data = json.load(f)
    except json.JSONDecodeError as e:
        raise Exception(f"Invalid JSON in {cat_file}: {str(e)}")
    except Exception as e:
        raise Exception(f"Error reading {cat_file}: {str(e)}")

    # Handle both single object and list formats
    if isinstance(cat_data, list):
        cat_data = cat_data[0]  # Take the first category if it's a list

    # Prepare POST data
    post_data = {}
    # Only copy fields we want to send
    for field in ['name', 'description', 'default_location', 'default_keywords']:
        if field in cat_data:
            post_data[field] = cat_data[field]
    post_data['parent'] = parent_pk
    
    # Check if category already exists
    existing_cats = check_category_exists(post_data['name'], parent_pk)
    if existing_cats:
        print(f"Category '{post_data['name']}' already exists, skipping creation")
        return existing_cats[0]['pk']
    
    try:
        resp = requests.post(BASE_URL_CATEGORIES, headers=HEADERS, json=post_data)
        if resp.status_code != 201:
            raise Exception(f"Failed to create category from {cat_file}: {resp.status_code} - {resp.text}")
        new_cat = resp.json()
        new_pk = new_cat['pk']
    except requests.exceptions.RequestException as e:
        raise Exception(f"Network error creating category from {cat_file}: {str(e)}")
    except json.JSONDecodeError as e:
        raise Exception(f"Invalid JSON response creating category from {cat_file}: {str(e)}")
    except Exception as e:
        raise Exception(f"Error creating category from {cat_file}: {str(e)}")
    print(f"Created category '{new_cat['name']}' with PK {new_pk} (parent: {parent_pk})")
    
    # Import parts in this folder
    for filename in os.listdir(folder_path):
        if filename == 'category.json' or not filename.endswith('.json'):
            continue
        part_path = os.path.join(folder_path, filename)
        try:
            with open(part_path, 'r', encoding='utf-8') as f:
                part_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in {part_path}: {str(e)}")
            continue
        except Exception as e:
            print(f"Error reading {part_path}: {str(e)}")
            continue

        # Handle both single object and list formats
        if isinstance(part_data, list):
            part_data = part_data[0]  # Take the first part if it's a list

        # Prepare POST data with only the fields we want to send
        post_part = {}
        allowed_fields = ['name', 'description', 'IPN', 'revision', 'keywords',
                         'barcode', 'minimum_stock', 'units', 'assembly', 'component',
                         'trackable', 'purchaseable', 'salable', 'virtual']

        for field in allowed_fields:
            if field in part_data:
                post_part[field] = part_data[field]

        post_part['category'] = new_pk
        
        # Check if part already exists
        existing_parts = check_part_exists(post_part['name'], new_pk)
        if existing_parts:
            print(f"Part '{post_part['name']}' already exists in category {new_pk}, skipping creation")
            continue
        
        try:
            resp_part = requests.post(BASE_URL_PARTS, headers=HEADERS, json=post_part)
            if resp_part.status_code != 201:
                print(f"Failed to create part from {filename}: {resp_part.status_code} - {resp_part.text}")
                continue
        except Exception as e:
            print(f"Error creating part from {filename}: {str(e)}")
            continue
        
        new_part = resp_part.json()
        print(f"Created part '{new_part['name']}' with PK {new_part['pk']} in category {new_pk}")
    
    # Recurse into subfolders for subcategories
    for subdir in os.listdir(folder_path):
        sub_path = os.path.join(folder_path, subdir)
        if os.path.isdir(sub_path):
            import_category(sub_path, new_pk)

def main():
    if not TOKEN:
        raise Exception("INVENTREE_TOKEN environment variable not set. Set it with: export INVENTREE_TOKEN='your-token'")
    
    if not os.path.exists('data'):
        raise FileNotFoundError("'data' directory not found. Please ensure you're running the script from the correct location.")

    root_dir = 'data/parts'  # Top-level category folders are directly under 'data/parts'
    try:
        for top_dir in os.listdir(root_dir):
            top_path = os.path.join(root_dir, top_dir)
            if os.path.isdir(top_path) and top_dir != 'companies':  # Skip companies dir
                import_category(top_path, None)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()