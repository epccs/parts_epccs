#!/usr/bin/env python3
# file name: json2inv-template.py
# version: 2025-11-03-v1
# --------------------------------------------------------------
# Import **template** parts + recursive BOM from data/templates/ → InvenTree
#
# * Folder structure → category hierarchy (ignores JSON “category” field)
# * *.json      → part metadata (template flag forced true)
# * *.bom.json  → recursive BOM tree (imported after part exists)
# * --force-ipn → generate IPN from name when missing
# * --force     → delete existing template (with optional --clean-dependencies)
# * --clean-dependencies → delete stock/BOM/etc. after two confirmations
#
# Example usage:
#   python3 ./api/json2inv-template.py "Furniture/Tables/*_Table.json" --force-ipn
#   python3 ./api/json2inv-template.py "**/*.json" --force --clean-dependencies
# --------------------------------------------------------------
# WIP: https://grok.com/share/c2hhcmQtMw%3D%3D_754fb50b-a674-4d58-a206-e510b64792f5

import requests
import json
import os
import glob
import sys
import argparse
from pathlib import Path

# ----------------------------------------------------------------------
# API endpoints (built from INVENTREE_URL)
# ----------------------------------------------------------------------
BASE_URL = os.getenv("INVENTREE_URL")
if BASE_URL:
    BASE_URL = BASE_URL.rstrip("/")
    BASE_URL_PARTS      = f"{BASE_URL}/api/part/"
    BASE_URL_CATEGORIES = f"{BASE_URL}/api/part/category/"
    BASE_URL_BOM        = f"{BASE_URL}/api/bom/"
    # (dependency endpoints – same as parts script)
    BASE_URL_STOCK      = f"{BASE_URL}/api/stock/"
    BASE_URL_TEST       = f"{BASE_URL}/api/part/test-template/"
    BASE_URL_BUILD      = f"{BASE_URL}/api/build/"
    BASE_URL_SALES      = f"{BASE_URL}/api/sales/order/"
    BASE_URL_ATTACH     = f"{BASE_URL}/api/part/attachment/"
    BASE_URL_PARAM      = f"{BASE_URL}/api/part/parameter/"
    BASE_URL_RELATED    = f"{BASE_URL}/api/part/related/"
else:
    raise RuntimeError("INVENTREE_URL not set")

TOKEN = os.getenv("INVENTREE_TOKEN")
if not TOKEN:
    raise RuntimeError("INVENTREE_TOKEN not set")

HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ----------------------------------------------------------------------
# Helper: category existence
# ----------------------------------------------------------------------
def category_exists(name: str, parent_pk: int | None = None):
    params = {"name": name}
    if parent_pk is not None:
        params["parent"] = parent_pk
    r = requests.get(BASE_URL_CATEGORIES, headers=HEADERS, params=params)
    if r.status_code != 200:
        raise RuntimeError(f"Category check failed: {r.text}")
    data = r.json()
    results = data.get("results", data) if isinstance(data, dict) else data
    return results[0] if results else None


def create_category(name: str, parent_pk: int | None = None):
    payload = {"name": name}
    if parent_pk is not None:
        payload["parent"] = parent_pk
    r = requests.post(BASE_URL_CATEGORIES, headers=HEADERS, json=payload)
    if r.status_code != 201:
        raise RuntimeError(f"Create category failed: {r.text}")
    return r.json()["pk"]


def build_category_from_path(folder_path: str) -> int:
    """Return leaf category PK for a folder relative to data/templates/"""
    rel = os.path.relpath(folder_path, "data/templates")
    parts = [p for p in rel.split(os.sep) if p and p != "."]
    cur_pk = None
    for name in parts:
        existing = category_exists(name, cur_pk)
        cur_pk = existing["pk"] if existing else create_category(name, cur_pk)
    return cur_pk


# ----------------------------------------------------------------------
# Helper: part existence (global name+IPN)
# ----------------------------------------------------------------------
def part_exists(name: str, ipn: str | None = None):
    params = {"name": name}
    if ipn:
        params["IPN"] = ipn
    r = requests.get(BASE_URL_PARTS, headers=HEADERS, params=params)
    if r.status_code != 200:
        raise RuntimeError(f"Part check failed: {r.text}")
    data = r.json()
    results = data.get("results", data) if isinstance(data, dict) else data
    return results  # list of matching parts


# ----------------------------------------------------------------------
# Dependency handling (identical to parts script)
# ----------------------------------------------------------------------
def check_dependencies(part_pk: int):
    deps = {
        "stock": [], "bom": [], "test": [], "build": [], "sales": [],
        "attachments": [], "parameters": [], "related": []
    }
    for endpoint, key in [
        (BASE_URL_STOCK, "stock"),
        (BASE_URL_BOM, "bom"),
        (BASE_URL_TEST, "test"),
        (BASE_URL_BUILD, "build"),
        (BASE_URL_SALES, "sales"),
        (BASE_URL_ATTACH, "attachments"),
        (BASE_URL_PARAM, "parameters"),
        (BASE_URL_RELATED, "related"),
    ]:
        try:
            r = requests.get(f"{endpoint}?part={part_pk}", headers=HEADERS)
            if r.status_code == 200:
                js = r.json()
                cnt = js.get("count", len(js)) if isinstance(js, dict) else len(js)
                if cnt:
                    deps[key] = js.get("results", js)
        except Exception:
            pass
    return deps


def delete_dependencies(part_name: str, part_pk: int, clean: bool):
    if not clean:
        return False
    deps = check_dependencies(part_pk)
    total = sum(len(v) for v in deps.values())
    if total == 0:
        return True
    print(f"WARNING: {total} dependencies for '{part_name}' (PK {part_pk})")
    for k, items in deps.items():
        if items:
            print(f" • {len(items)} {k}")
    if input(f"Type 'YES' to delete {total} deps for '{part_name}': ") != "YES":
        return False
    if input(f"Type 'CONFIRM' to PERMANENTLY delete: ") != "CONFIRM":
        return False
    for key, items in deps.items():
        for it in items:
            pk = it.get("pk")
            url = {
                "stock": f"{BASE_URL_STOCK}{pk}/",
                "bom": f"{BASE_URL_BOM}{pk}/",
                "test": f"{BASE_URL_TEST}{pk}/",
                "build": f"{BASE_URL_BUILD}{pk}/",
                "sales": f"{BASE_URL_SALES}{pk}/",
                "attachments": f"{BASE_URL_ATTACH}{pk}/",
                "parameters": f"{BASE_URL_PARAM}{pk}/",
                "related": f"{BASE_URL_RELATED}{pk}/",
            }[key]
            try:
                r = requests.delete(url, headers=HEADERS)
                if r.status_code != 204:
                    raise RuntimeError(f"Delete {key} {pk} failed: {r.text}")
            except Exception as e:
                raise RuntimeError(f"Network error deleting {key} {pk}: {e}")
    return True


def delete_part(part_name: str, part_pk: int, clean_deps: bool):
    if not delete_dependencies(part_name, part_pk, clean_deps):
        raise RuntimeError("Dependencies block deletion")
    # deactivate first
    r = requests.patch(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS,
                       json={"active": False})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Patch active=False failed: {r.text}")
    r = requests.delete(f"{BASE_URL_PARTS}{part_pk}/", headers=HEADERS)
    if r.status_code != 204:
        raise RuntimeError(f"DELETE part failed: {r.text}")


# ----------------------------------------------------------------------
# Core import – part metadata
# ----------------------------------------------------------------------
def import_template_part(part_path: str, force_ipn: bool, force: bool, clean: bool):
    with open(part_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ------------------------------------------------------------------
    # 1. Build payload (whitelist + force template flag)
    # ------------------------------------------------------------------
    allowed = [
        "name", "description", "IPN", "revision", "keywords",
        "barcode", "minimum_stock", "units", "assembly", "component",
        "trackable", "purchaseable", "salable", "virtual", "active"
    ]
    payload = {k: data.get(k) for k in allowed if data.get(k) is not None}
    payload.setdefault("active", True)
    payload["is_template"] = True                     # <-- force template

    if not payload.get("name"):
        print(f"SKIP: no name in {part_path}")
        return

    # ------------------------------------------------------------------
    # 2. IPN handling
    # ------------------------------------------------------------------
    ipn = payload.get("IPN")
    if force_ipn and (ipn is None or ipn == ""):
        ipn = payload["name"][:50]
        payload["IPN"] = ipn
        print(f"Generated IPN → {ipn}")

    # ------------------------------------------------------------------
    # 3. Category from folder
    # ------------------------------------------------------------------
    folder = os.path.dirname(part_path)
    cat_pk = build_category_from_path(folder)
    payload["category"] = cat_pk

    # ------------------------------------------------------------------
    # 4. Global existence check
    # ------------------------------------------------------------------
    existing = part_exists(payload["name"], ipn)
    if existing and force:
        for p in existing:
            print(f"--force: deleting existing PK {p['pk']} ({p['name']})")
            delete_part(p["name"], p["pk"], clean)
    elif existing:
        print(f"SKIP: '{payload['name']}' (IPN={ipn}) already exists")
        # still import BOM if it changed
        part_pk = existing[0]["pk"]
    else:
        # ----------------------------------------------------------------
        # 5. CREATE
        # ----------------------------------------------------------------
        r = requests.post(BASE_URL_PARTS, headers=HEADERS, json=payload)
        if r.status_code != 201:
            raise RuntimeError(f"Create part failed: {r.text}")
        part_pk = r.json()["pk"]
        print(f"CREATED: {payload['name']} (PK {part_pk})")

    # ------------------------------------------------------------------
    # 6. Import recursive BOM (if .bom.json exists)
    # ------------------------------------------------------------------
    bom_path = Path(part_path).with_name(Path(part_path).stem + ".bom.json")
    if bom_path.is_file():
        import_recursive_bom(part_pk, bom_path)
    else:
        print(f"No .bom.json for {payload['name']}")


# ----------------------------------------------------------------------
# Recursive BOM import
# ----------------------------------------------------------------------
def import_recursive_bom(parent_pk: int, bom_path: Path, level: int = 0):
    """Import a full BOM tree – each node becomes a BOM line."""
    indent = "  " * level
    with open(bom_path, "r", encoding="utf-8") as f:
        tree = json.load(f)

    for node in tree:
        qty = node.get("quantity")
        note = node.get("note", "")
        sub = node["sub_part"]
        sub_name = sub["name"]
        sub_ipn = sub.get("IPN", "")

        # Resolve sub-part PK (must already exist because we import top-down)
        sub_parts = part_exists(sub_name, sub_ipn or None)
        if not sub_parts:
            raise RuntimeError(f"Sub-part '{sub_name}' not found – import order issue")
        sub_pk = sub_parts[0]["pk"]

        # Create / update BOM line
        payload = {
            "part": parent_pk,
            "sub_part": sub_pk,
            "quantity": qty,
            "note": note,
        }
        # Check if line already exists
        existing = requests.get(
            BASE_URL_BOM, headers=HEADERS,
            params={"part": parent_pk, "sub_part": sub_pk}
        ).json()
        existing = existing.get("results", existing) if isinstance(existing, dict) else existing

        if existing:
            # PATCH (update quantity/note)
            bom_pk = existing[0]["pk"]
            r = requests.patch(f"{BASE_URL_BOM}{bom_pk}/", headers=HEADERS, json=payload)
            action = "UPDATED"
        else:
            r = requests.post(BASE_URL_BOM, headers=HEADERS, json=payload)
            action = "CREATED"

        if r.status_code not in (200, 201):
            raise RuntimeError(f"BOM line failed: {r.text}")
        print(f"{indent}{action} BOM: {qty} × {sub_name}")

        # Recurse into children
        if node.get("children"):
            child_bom_path = bom_path.parent / f"{sub_name}.bom.json"
            if child_bom_path.is_file():
                import_recursive_bom(sub_pk, child_bom_path, level + 1)
            else:
                print(f"{indent}  No .bom.json for sub-assembly {sub_name}")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Import template parts + recursive BOM from data/templates/ → InvenTree"
    )
    parser.add_argument(
        "patterns", nargs="*", default=["**/*.json"],
        help="Glob patterns (default: all *.json under data/templates)"
    )
    parser.add_argument("--force-ipn", action="store_true",
                        help="Generate IPN from name when missing")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing template before re-creating")
    parser.add_argument("--clean-dependencies", action="store_true",
                        help="Delete dependencies (requires two confirmations)")
    args = parser.parse_args()

    root = "data/templates"
    if not os.path.isdir(root):
        raise FileNotFoundError(f"{root} missing")

    # ------------------------------------------------------------------
    # Collect part JSON files (exclude category.json and *.bom.json)
    # ------------------------------------------------------------------
    files = []
    for pat in args.patterns:
        full_pat = os.path.join(root, pat)
        matches = glob.glob(full_pat, recursive=True)
        files.extend(matches)

    files = sorted({
        f for f in files
        if f.endswith(".json") and not f.endswith(".bom.json") and os.path.basename(f) != "category.json"
    })

    print(f"Found {len(files)} template part files")
    for f in files:
        try:
            import_template_part(
                f,
                force_ipn=args.force_ipn,
                force=args.force,
                clean=args.clean_dependencies
            )
        except Exception as e:
            print(f"ERROR importing {f}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()