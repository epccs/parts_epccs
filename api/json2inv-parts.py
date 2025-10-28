#!/usr/bin/env python3
# file name: json2inv-parts.py
# version: 2025-10-27-v3
# --------------------------------------------------------------
# Import parts from data/parts → InvenTree.
# * Folder structure → category hierarchy (ignores JSON “category” field).
# * --force-ipn   → generate IPN from name when missing.
# * --force       → delete existing part (with optional --clean-dependencies).
# * --clean-dependencies → delete stock/BOM/test/etc. after two confirmations.
# --------------------------------------------------------------
# Example usage:
#   python3 ./api/json2inv-parts.py "Electronics/Passives/Capacitors/C_*.json" --force-ipn --force --clean-dependencies
#   python3 ./api/json2inv-parts.py "Paint/Yellow_Paint.json" --force-ipn
#   python3 ./api/json2inv-parts.py  # Imports all parts
#   python3 ./api/json2inv-parts.py "**/*.json" --force-ipn --force
# --------------------------------------------------------------

import requests
import json
import os
import glob
import sys
import argparse

# ----------------------------------------------------------------------
# API endpoints (all built from INVENTREE_URL)
# ----------------------------------------------------------------------
if os.getenv("INVENTREE_URL"):
    BASE_URL = os.getenv("INVENTREE_URL")
    BASE_URL_PARTS       = BASE_URL + "api/part/"
    BASE_URL_CATEGORIES  = BASE_URL + "api/part/category/"
    BASE_URL_BOM         = BASE_URL + "api/bom/"
    BASE_URL_TEST        = BASE_URL + "api/part/test-template/"
    BASE_URL_STOCK       = BASE_URL + "api/stock/"
    BASE_URL_BUILD       = BASE_URL + "api/build/"
    BASE_URL_SALES       = BASE_URL + "api/sales/order/"
    BASE_URL_ATTACHMENTS = BASE_URL + "api/part/attachment/"
    BASE_URL_PARAMETERS  = BASE_URL + "api/part/parameter/"
    BASE_URL_RELATED     = BASE_URL + "api/part/related/"
else:
    BASE_URL = None
    BASE_URL_PARTS = BASE_URL_CATEGORIES = BASE_URL_BOM = BASE_URL_TEST = None
    BASE_URL_STOCK = BASE_URL_BUILD = BASE_URL_SALES = BASE_URL_ATTACHMENTS = None
    BASE_URL_PARAMETERS = BASE_URL_RELATED = None

TOKEN = os.getenv("INVENTREE_TOKEN")
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ----------------------------------------------------------------------
# Helper: category existence
# ----------------------------------------------------------------------
def check_category_exists(name, parent_pk=None):
    """Check if a category with given name and parent already exists."""
    print(f"DEBUG: Checking if category '{name}' exists (parent={parent_pk})")
    params = {"name": name}
    if parent_pk is not None:
        params["parent"] = parent_pk
    try:
        resp = requests.get(BASE_URL_CATEGORIES, headers=HEADERS, params=params)
        print(f"DEBUG: Category check status {resp.status_code}")
        if resp.status_code != 200:
            raise Exception(f"Category check failed: {resp.status_code} – {resp.text}")
        data = resp.json()

        # Handle both paginated dict and plain list
        if isinstance(data, dict) and "results" in data:
            results = data["results"]
        elif isinstance(data, list):
            results = data
        else:
            results = []

        print(f"DEBUG: Found {len(results)} matching categories")
        return results

    except requests.RequestException as e:
        raise Exception(f"Network error checking category: {e}")

# ----------------------------------------------------------------------
# Helper: part existence (name + optional IPN + category)
# ----------------------------------------------------------------------
def check_part_exists(name, ipn):
    """Search globally for part by name + IPN (ignore category)."""
    print(f"DEBUG: Global search for part '{name}' (IPN={ipn})")
    params = {"name": name}
    if ipn:
        params["IPN"] = ipn
    try:
        resp = requests.get(BASE_URL_PARTS, headers=HEADERS, params=params)
        print(f"DEBUG: Global part check status {resp.status_code}")
        if resp.status_code != 200:
            raise Exception(f"Global check failed: {resp.status_code} – {resp.text}")
        data = resp.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        if results:
            print(f"DEBUG: Found {len(results)} existing parts globally: {[p.get('pk') for p in results]}")
        return results
    except requests.RequestException as e:
        raise Exception(f"Network error in global part check: {e}")

# ----------------------------------------------------------------------
# Dependency handling
# ----------------------------------------------------------------------
def check_dependencies(part_pk):
    deps = {
        "stock": [], "bom": [], "test": [], "build": [], "sales": [],
        "attachments": [], "parameters": [], "related": []
    }
    for endpoint, key in [
        (BASE_URL_STOCK,       "stock"),
        (BASE_URL_BOM,         "bom"),
        (BASE_URL_TEST,        "test"),
        (BASE_URL_BUILD,       "build"),
        (BASE_URL_SALES,       "sales"),
        (BASE_URL_ATTACHMENTS, "attachments"),
        (BASE_URL_PARAMETERS,  "parameters"),
        (BASE_URL_RELATED,     "related"),
    ]:
        try:
            r = requests.get(f"{endpoint}?part={part_pk}", headers=HEADERS)
            print(f"DEBUG: Dep-check {key} → {r.status_code}")
            if r.status_code == 200:
                js = r.json()
                cnt = js.get("count", len(js)) if isinstance(js, dict) else len(js)
                if cnt:
                    deps[key] = js.get("results", js)
                    print(f"DEBUG:   → {cnt} {key}")
        except requests.RequestException as e:
            print(f"DEBUG: Dep-check {key} network error: {e}")
    return deps

def delete_dependencies(part_name, part_pk, clean):
    if not clean:
        return False
    deps = check_dependencies(part_pk)
    total = sum(len(v) for v in deps.values())
    if total == 0:
        print(f"DEBUG: No dependencies for {part_name} (PK {part_pk})")
        return True

    print(f"WARNING: {total} dependencies for '{part_name}' (PK {part_pk})")
    for k, items in deps.items():
        if items:
            print(f"  • {len(items)} {k}: {[i.get('pk') for i in items]}")

    if input(f"Type 'YES' to delete {total} deps for '{part_name}': ") != "YES":
        print("DEBUG: Cancelled (first prompt)")
        return False
    if input(f"Type 'CONFIRM' to PERMANENTLY delete: ") != "CONFIRM":
        print("DEBUG: Cancelled (second prompt)")
        return False

    for key, items in deps.items():
        for it in items:
            pk = it.get("pk")
            url = {
                "stock":       f"{BASE_URL_STOCK}{pk}/",
                "bom":         f"{BASE_URL_BOM}{pk}/",
                "test":        f"{BASE_URL_TEST}{pk}/",
                "build":       f"{BASE_URL_BUILD}{pk}/",
                "sales":       f"{BASE_URL_SALES}{pk}/",
                "attachments": f"{BASE_URL_ATTACHMENTS}{pk}/",
                "parameters":  f"{BASE_URL_PARAMETERS}{pk}/",
                "related":     f"{BASE_URL_RELATED}{pk}/",
            }[key]
            try:
                r = requests.delete(url, headers=HEADERS)
                print(f"DEBUG: Delete {key} {pk} → {r.status_code}")
                if r.status_code != 204:
                    raise Exception(f"Delete failed: {r.text}")
            except requests.RequestException as e:
                raise Exception(f"Network error deleting {key} {pk}: {e}")
    return True

def delete_part(part_name, part_pk, clean_deps):
    print(f"DEBUG: Deleting part '{part_name}' (PK {part_pk})")
    if not delete_dependencies(part_name, part_pk, clean_deps):
        raise Exception("Dependencies block deletion")

    # InvenTree refuses to delete active parts → set inactive first
    try:
        r = requests.patch(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS,
                           json={"active": False})
        print(f"DEBUG: Patch active=False → {r.status_code}")
        if r.status_code not in (200, 201):
            raise Exception(f"Patch failed: {r.text}")
    except requests.RequestException as e:
        raise Exception(f"Network error patching active: {e}")

    try:
        r = requests.delete(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS)
        print(f"DEBUG: DELETE part → {r.status_code}")
        if r.status_code != 204:
            raise Exception(f"Delete failed: {r.text}")
        print(f"DEBUG: Part {part_name} (PK {part_pk}) deleted")
    except requests.RequestException as e:
        raise Exception(f"Network error deleting part: {e}")

# ----------------------------------------------------------------------
# Category hierarchy – **folder-based**
# ----------------------------------------------------------------------
def create_category_hierarchy(folder_path, parent_pk=None):
    """Build categories from folder_path, return leaf PK."""
    print(f"DEBUG: Building hierarchy for {folder_path}")
    parts = os.path.relpath(folder_path, "data/parts").split(os.sep)
    cur = parent_pk
    for name in parts:
        if name == ".":
            continue
        existing = check_category_exists(name, cur)
        if existing:
            cur = existing[0]["pk"]
            print(f"DEBUG:   → {name} (PK {cur}) already exists")
            continue

        payload = {"name": name, "parent": cur}
        try:
            r = requests.post(BASE_URL_CATEGORIES, headers=HEADERS, json=payload)
            print(f"DEBUG: POST category → {r.status_code}")
            if r.status_code != 201:
                raise Exception(f"Create category failed: {r.text}")
            new = r.json()
            cur = new["pk"]
            print(f"DEBUG:   → created {name} (PK {cur})")
        except requests.RequestException as e:
            raise Exception(f"Network error creating category {name}: {e}")
    return cur

# ----------------------------------------------------------------------
# Core import routine
# ----------------------------------------------------------------------
def import_part(part_path, force_ipn=False, force=False, clean=False):
    print(f"DEBUG: Importing {part_path}")
    try:
        with open(part_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"DEBUG: JSON error: {e}")
        return

    if isinstance(data, list):
        data = data[0]

    # ----- build POST payload -----
    allowed = [
        "name", "description", "IPN", "revision", "keywords",
        "barcode", "minimum_stock", "units", "assembly", "component",
        "trackable", "purchaseable", "salable", "virtual", "active"
    ]
    payload = {k: data.get(k) for k in allowed if k in data}
    if not payload.get("name"):
        print("DEBUG: No name – skipping")
        return
    payload["active"] = True

    ipn = payload.get("IPN")
    if force_ipn and (ipn is None or not ipn):
        ipn = payload["name"][:50]
        payload["IPN"] = ipn
        print(f"DEBUG: Generated IPN → {ipn}")

    # ----- folder-based category -----
    folder = os.path.dirname(part_path)
    cat_pk = create_category_hierarchy(folder)
    payload["category"] = cat_pk
    print(f"DEBUG: Payload → {payload}")

    # ----- global existence check (name + IPN) -----
    existing = check_part_exists(payload["name"], ipn)
    if existing and force:
        for p in existing:
            print(f"DEBUG: --force: deleting existing part PK {p['pk']} (cat {p.get('category')})")
            delete_part(p["name"], p["pk"], clean)
    elif existing:
        print(f"DEBUG: Part '{payload['name']}' (IPN={ipn}) already exists globally - skipping")
        return

    # ----- create -----
    try:
        r = requests.post(BASE_URL_PARTS, headers=HEADERS, json=payload)
        print(f"DEBUG: POST part → {r.status_code}")
        if r.status_code != 201:
            raise Exception(f"Create failed: {r.text}")
        new = r.json()
        print(f"DEBUG: Created {new['name']} (PK {new['pk']}) in cat {cat_pk}")
    except requests.RequestException as e:
        print(f"DEBUG: Network error creating part: {e}")

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Import parts from data/parts → InvenTree (folder-based categories)."
    )
    parser.add_argument(
        "patterns", nargs="*", default=["**/*.json"],
        help="Glob patterns (default: all *.json under data/parts)"
    )
    parser.add_argument("--force-ipn", action="store_true",
                        help="Generate IPN from name when missing")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing part before re-creating")
    parser.add_argument("--clean-dependencies", action="store_true",
                        help="Delete dependencies (requires two confirmations)")
    args = parser.parse_args()

    if not TOKEN:
        raise Exception("INVENTREE_TOKEN not set")
    if not BASE_URL:
        raise Exception("INVENTREE_URL not set")

    root = "data/parts"
    if not os.path.isdir(root):
        raise FileNotFoundError(f"{root} missing")

    # ---- collect files ----
    files = []
    for pat in args.patterns:
        full = os.path.join(root, pat)
        matches = glob.glob(full, recursive=True)
        files.extend(matches)

    if not files:
        for pat in args.patterns:
            fp = os.path.join(root, pat)
            if os.path.isfile(fp) and fp.endswith(".json"):
                files.append(fp)

    files = sorted(set(f for f in files if f.endswith(".json") and os.path.basename(f) != "category.json"))
    print(f"DEBUG: {len(files)} part files to process")

    for f in files:
        import_part(f, args.force_ipn, args.force, args.clean_dependencies)

if __name__ == "__main__":
    main()