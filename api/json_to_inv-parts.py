#!/usr/bin/env python3
# file name: json_to_inv-parts.py
# version: 2025-12-04-v2
# --------------------------------------------------------------
# Push all parts (templates, assemblies, real) from data/parts/<level>/ to InvenTree, level by level.
#
# * Folder structure under each level -> category hierarchy
# * Supports Part_Name[.revision].json + [Part_Name[.revision].bom.json]
# * Supports variant_of format: "BaseName[.revision]" : Note that Inventree requires variant_of to be the part PK so a lookup is performed
# * Pushes categories on demand from folder paths
# * Pushes parts level by level to respect dependencies
# * --force-ipn -> generate IPN from name when missing
# * --force -> delete existing part (name + revision)
# * --clean-dependencies -> delete BOM/stock/etc. (with confirmation)
# * --force-price -> delete existing price breaks before pushing new ones
# * --api-print -> prints every API call (URL + payload) + short GET response preview
# * --dry-run (no API changes, just simulation)
# * .bom.json pushed only if exists
# * pushes suppliers/manufacturers/price breaks if purchaseable, fetched globally + local filter
# * Uses a cache for part lookups to improve performance
# --------------------------------------------------------------
#
# example usage:
# python3 ./api/json_to_inv-parts.py "1/Mechanical/Fasteners/Wood_Screw"
# python3 ./api/json_to_inv-parts.py "1/Furniture/Leg"
# python3 ./api/json_to_inv-parts.py "1/Furniture/*_Top"
# python3 ./api/json_to_inv-parts.py "2/Furniture/Tables/*_Table" --api-print
# python3 ./api/json_to_inv-parts.py "2/Electronics/PCBA/Widget_Board_(assembled).REV-A" --api-print
# python3 ./api/json_to_inv-parts.py "**/*"
# --------------------------------------------------------------
# Changelog:
#   - update the BOM resolver to use revision field
# --------------------------------------------------------------

import requests
import json
import os
import glob
import argparse
import sys
import re
from collections import defaultdict

# ----------------------------------------------------------------------
# API & Auth
# ----------------------------------------------------------------------
BASE_URL = os.getenv("INVENTREE_URL")
if not BASE_URL:
    print("Error: INVENTREE_URL not set")
    sys.exit(1)
BASE_URL = BASE_URL.rstrip("/")
BASE_URL_PARTS = f"{BASE_URL}/api/part/"
BASE_URL_CATEGORIES = f"{BASE_URL}/api/part/category/"
BASE_URL_BOM = f"{BASE_URL}/api/bom/"
BASE_URL_COMPANY = f"{BASE_URL}/api/company/"
BASE_URL_SUPPLIER_PARTS = f"{BASE_URL}/api/company/part/"
BASE_URL_MANUFACTURER_PART = f"{BASE_URL}/api/company/part/manufacturer/"
BASE_URL_PRICE_BREAK = f"{BASE_URL}/api/company/price-break/"

TOKEN = os.getenv("INVENTREE_TOKEN")
if not TOKEN:
    print("Error: INVENTREE_TOKEN not set")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ----------------------------------------------------------------------
# API helpers
# ----------------------------------------------------------------------
def fetch_all(url, api_print=False, dry_run=False):
    if dry_run and api_print:
        print(f"[DRY-RUN] Would GET: {url}")
        return []
    items = []
    while url:
        if api_print:
            print(f"API GET: {url}")
        r = requests.get(url, headers=HEADERS)
        if r.status_code != 200:
            raise Exception(f"API error {r.status_code}: {r.text}")
        data = r.json()
        if api_print and data:
            preview = json.dumps(data if isinstance(data, list) else data.get("results", [])[:2], default=str)[:200]
            print(f" -> {r.status_code} [{len(items)} fetched] sample: {preview}...")
        if isinstance(data, dict) and "results" in data:
            items.extend(data["results"])
            url = data.get("next")
        else:
            items.extend(data if isinstance(data, list) else [data])
            url = None
    return items

def api_post(url, payload, api_print=False, dry_run=False):
    if dry_run:
        if api_print:
            print(f"[DRY-RUN] Would POST: {url}")
            print(f"Payload: {json.dumps(payload, indent=4)}")
        return {"pk": "DRY-RUN"}
    if api_print:
        print(f"API POST: {url}")
        print(f"Payload: {json.dumps(payload, indent=4)}")
    r = requests.post(url, headers=HEADERS, json=payload)
    if r.status_code not in (200, 201):
        print(f"ERROR {r.status_code}: {r.text}")
        sys.exit(1)
    return r.json()

def api_patch(url, payload, api_print=False, dry_run=False):
    if dry_run:
        if api_print:
            print(f"[DRY-RUN] Would PATCH: {url}")
            print(f"Payload: {json.dumps(payload, indent=4)}")
        return
    if api_print:
        print(f"API PATCH: {url}")
        print(f"Payload: {json.dumps(payload, indent=4)}")
    r = requests.patch(url, headers=HEADERS, json=payload)
    if r.status_code not in (200, 201):
        print(f"ERROR {r.status_code}: {r.text}")
        sys.exit(1)

def api_delete(url, api_print=False, dry_run=False):
    if dry_run:
        if api_print:
            print(f"[DRY-RUN] Would DELETE: {url}")
        return
    if api_print:
        print(f"API DELETE: {url}")
    r = requests.delete(url, headers=HEADERS)
    if r.status_code not in (200, 201, 204):
        print(f"ERROR {r.status_code}: {r.text}")

# ----------------------------------------------------------------------
# Category & variant helpers
# ----------------------------------------------------------------------
def check_category_exists(name, parent_pk=None):
    params = {"name": name}
    if parent_pk is not None:
        params["parent"] = parent_pk
    r = requests.get(BASE_URL_CATEGORIES, headers=HEADERS, params=params)
    if r.status_code != 200:
        return []
    data = r.json()
    return data.get("results", []) if isinstance(data, dict) else data

def create_category_hierarchy(folder_path, root_dir, parent_pk=None):
    rel_path = os.path.relpath(folder_path, root_dir)
    parts = [p for p in rel_path.split(os.sep) if p and not p.isdigit()]
    cur = parent_pk
    for name in parts:
        existing = check_category_exists(name, cur)
        if existing:
            cur = existing[0]["pk"]
            continue
        payload = {"name": name, "parent": cur}
        cur = api_post(BASE_URL_CATEGORIES, payload)["pk"]
    return cur

def parse_filename(filepath):
    basename = os.path.basename(filepath)
    if not basename.endswith(".json"):
        return None, None
    name_part = basename[:-5]
    if "." in name_part:
        name, rev = name_part.rsplit(".", 1)
        return name, rev
    return name_part, None

def resolve_variant_target(variant_str, cache):
    if not variant_str:
        return None
    if "." in variant_str:
        name, rev = variant_str.rsplit(".", 1)
    else:
        name, rev = variant_str, ""
    candidates = cache.get(name, [])
    for c in candidates:
        if c.get("revision", "") == rev:
            return c["pk"]
    return None

# ----------------------------------------------------------------------
# BOM push - per revision, with correct validation
# ----------------------------------------------------------------------
def push_bom(part_pk, bom_path, cache=None, api_print=False, dry_run=False):
    if not os.path.exists(bom_path):
        return

    print(f"Pushing BOM from {bom_path} -> Part PK {part_pk}")
    with open(bom_path, "r", encoding="utf-8") as f:
        tree = json.load(f)

    existing_boms = fetch_all(f"{BASE_URL_BOM}?part={part_pk}", api_print=api_print, dry_run=dry_run)
    all_validated = True
    all_found = True

    for node in tree:
        qty = node.get("quantity", 1)
        note = node.get("note", "")
        validated = node.get("validated", False)
        active = node.get("active", True)
        sub_name = node["sub_part"]["name"]
        sub_ipn = node["sub_part"].get("IPN", "")
        sub_revision = node["sub_part"].get("revision", "")

        sub_parts = [
            p for p in cache.get(sub_name, [])
            if (p.get("IPN", "") == sub_ipn or not sub_ipn)
            and (p.get("revision", "") == sub_revision or not sub_revision)
        ]
        if not sub_parts:
            print(f"  WARNING: Sub-part '{sub_name}' (IPN: {sub_ipn}, Revision: {sub_revision}) not found -> skipping")
            all_found = False
            all_validated = False
            continue

        sub_pk = sub_parts[0]["pk"]
        existing = [b for b in existing_boms if b.get("sub_part") == sub_pk]

        payload = {
            "part": part_pk,
            "sub_part": sub_pk,
            "quantity": qty,
            "note": note,
            "validated": validated,
            "active": active
        }

        if existing:
            api_patch(f"{BASE_URL_BOM}{existing[0]['pk']}/", payload, api_print, dry_run)
            action = "UPDATED"
        else:
            api_post(BASE_URL_BOM, payload, api_print, dry_run)
            action = "CREATED"

        status = " (VALIDATED)" if validated else ""
        print(f"  {action} BOM: {qty} × {sub_name}{status}")

        if not validated:
            all_validated = False

    if tree and all_found and all_validated:
        print(f"  All BOM items validated -> setting validated_bom = True on PK {part_pk}")
        api_patch(f"{BASE_URL_PARTS}{part_pk}/", {"validated_bom": True}, api_print, dry_run)
    elif tree:
        print(f"  BOM has issues -> leaving validated_bom = False")

# ----------------------------------------------------------------------
# Push one revision (with optional BOM)
# ----------------------------------------------------------------------
def push_revision(part_pk, data, file_path, force, api_print, dry_run, cache):
    bom_path = file_path[:-5] + ".bom.json"
    if os.path.exists(bom_path):
        push_bom(part_pk, bom_path, cache=cache, api_print=api_print, dry_run=dry_run)

# ----------------------------------------------------------------------
# Main push logic
# ----------------------------------------------------------------------
def push_part_group(name, files, force, force_ipn, api_print, dry_run, root_dir, cache):
    print(f"\nPushing part group: '{name}' ({len(files)} revision(s))")

    for file_path, revision in files:
        print(f"Processing: {os.path.basename(file_path)} (revision: {revision or 'default'})")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                data = data[0]

        # Build payload
        payload = {k: data.get(k, "") for k in [
            "description", "IPN", "keywords", "units", "minimum_stock",
            "assembly", "component", "trackable", "purchaseable",
            "salable", "virtual", "is_template"
        ]}
        payload["name"] = name
        payload["revision"] = revision or ""
        payload["active"] = True

        if force_ipn and (not payload.get("IPN")):
            payload["IPN"] = name[:50]

        payload["category"] = create_category_hierarchy(os.path.dirname(file_path), root_dir)

        if data.get("variant_of"):
            variant_pk = resolve_variant_target(data["variant_of"], cache)
            if variant_pk:
                payload["variant_of"] = variant_pk

        # Check if exists
        key = (name, payload.get("IPN", ""), revision or "")
        existing = [p for p in cache.get(name, []) if
                    p.get("IPN", "") == payload.get("IPN", "") and
                    p.get("revision", "") == (revision or "")]

        if existing and force:
            for p in existing:
                api_delete(f"{BASE_URL_PARTS}{p['pk']}/", api_print, dry_run)
            existing = []

        if existing:
            part_pk = existing[0]["pk"]
            print(f"  Reusing existing part PK {part_pk}")
            api_patch(f"{BASE_URL_PARTS}{part_pk}/", payload, api_print, dry_run)
        else:
            result = api_post(BASE_URL_PARTS, payload, api_print, dry_run)
            part_pk = result["pk"] if not dry_run else "DRY-RUN"
            print(f"  Created new part PK {part_pk}")

        if not dry_run:
            cache[name].append(result if 'result' in locals() else existing[0])

        # Push BOM if exists for this revision
        bom_path = file_path[:-5] + ".bom.json"
        if os.path.exists(bom_path):
            push_bom(part_pk, bom_path, cache=cache, api_print=api_print, dry_run=dry_run)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("patterns", nargs="*", default=["**/*"])
    parser.add_argument("--force", action="store_true", help="Delete and recreate parts")
    parser.add_argument("--force-ipn", action="store_true")
    parser.add_argument("--api-print", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Building part cache...")
    all_parts = fetch_all(BASE_URL_PARTS, api_print=args.api_print, dry_run=args.dry_run)
    cache = defaultdict(list)
    for p in all_parts:
        cache[p["name"]].append(p)

    root = "data/parts"
    files = []
    for pat in args.patterns:
        files.extend(glob.glob(os.path.join(root, pat), recursive=True))
        files.extend(glob.glob(os.path.join(root, pat + ".*json"), recursive=True))

    files = sorted({
        f for f in files
        if f.endswith(".json") and not f.endswith(".bom.json") and "category.json" not in f
    })

    grouped = defaultdict(list)
    for f in files:
        name, rev = parse_filename(f)
        if name:
            grouped[name].append((f, rev))

    for name, group in grouped.items():
        push_part_group(name, group, args.force, args.force_ipn,
                        args.api_print, args.dry_run, root, cache)

    print("\nPush complete!")

if __name__ == "__main__":
    main()