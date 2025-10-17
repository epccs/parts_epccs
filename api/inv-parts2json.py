import requests
import json
import os

# API endpoint and authentication (for Parts and Part Categories)
# https://docs.inventree.org/en/latest/api/schema/#api-schema-documentation
# Save each category and subcategories as a file structure as well as a category.json file
# populate the parts in the proper category file structure as a separate JSON file named after the part
BASE_URL_PARTS = "http://localhost:8000/api/part/"
BASE_URL_CATEGORIES = "http://localhost:8000/api/part/category/"
TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def import_category(folder_path, parent_pk=None):
    """Recursively import a category from folder, create it, import parts, then subcategories."""
    cat_file = os.path.join(folder_path, 'category.json')
    if not os.path.exists(cat_file):
        raise Exception(f"No category.json in {folder_path}")
    
    with open(cat_file, 'r', encoding='utf-8') as f:
        cat_data = json.load(f)
    
    # Prepare POST data, pop read-only fields
    post_data = cat_data.copy()
    for field in ['pk', 'url', 'pathstring', 'part_count', 'item_count', 'category_part_count']:
        post_data.pop(field, None)
    post_data['parent'] = parent_pk
    
    resp = requests.post(BASE_URL_CATEGORIES, headers=HEADERS, json=post_data)
    if resp.status_code != 201:
        raise Exception(f"Failed to create category from {cat_file}: {resp.status_code} - {resp.text}")
    
    new_cat = resp.json()
    new_pk = new_cat['pk']
    print(f"Created category '{new_cat['name']}' with PK {new_pk} (parent: {parent_pk})")
    
    # Import parts in this folder
    for filename in os.listdir(folder_path):
        if filename == 'category.json' or not filename.endswith('.json'):
            continue
        part_path = os.path.join(folder_path, filename)
        with open(part_path, 'r', encoding='utf-8') as f:
            part_data = json.load(f)
        
        # Prepare POST data, pop read-only fields
        post_part = part_data.copy()
        for field in ['pk', 'url', 'creation_date', 'total_in_stock', 'allocation_count', 'available_stock', 'in_production', 'stock_item_count', 'used_in_count', 'supplier_count']:
            post_part.pop(field, None)
        post_part['category'] = new_pk
        
        resp_part = requests.post(BASE_URL_PARTS, headers=HEADERS, json=post_part)
        if resp_part.status_code != 201:
            print(f"Failed to create part from {filename}: {resp_part.status_code} - {resp_part.text}")
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
    
    root_dir = 'data'  # Top-level category folders are directly under 'data'
    try:
        for top_dir in os.listdir(root_dir):
            top_path = os.path.join(root_dir, top_dir)
            if os.path.isdir(top_path) and top_dir != 'companies':  # Skip companies dir
                import_category(top_path, None)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()