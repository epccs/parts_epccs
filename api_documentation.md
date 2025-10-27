# InvenTree API Scripts Documentation

This file documents the CLI usage of scripts in the `api` folder for managing companies, parts,
and categories in an InvenTree instance via its API. The scripts support exporting, importing,
and deleting data using JSON files in `data/companies` and `data/parts`.

## Prerequisites

- Python 3: Ensure Python 3 is installed.
- Dependencies: Install required packages:

  ```bash
  pip install requests
  ```

- Environment Variables:

  ```bash
  export INVENTREE_URL='http://inventree.local/'  # Your InvenTree instance URL
  export INVENTREE_TOKEN='your-token'             # Your API token
  ```

## Scripts Overview

### 1. inv-companies2json.py

Exports companies from InvenTree to JSON files in `data/companies`.

Usage:

```bash
python3 ./api/inv-companies2json.py
```

- Output: Creates JSON files (e.g., `data/companies/Customer_A.json`) with sanitized names
  (spaces to `_`, dots removed, `image` set to `""`).
- Example:

  ```bash
  python3 ./api/inv-companies2json.py
  # Creates data/companies/Bourns_Inc.json with "name": "Bourns_Inc"
  ```

### 2. json2inv-companies.py

Imports companies from JSON files in `data/companies` to InvenTree.

Usage:

```bash
python3 ./api/json2inv-companies.py [glob_pattern...] [--force]
```

- Arguments:
  - `glob_pattern`: Optional glob patterns (e.g., `Customer_?.json`, `Bourns_Inc.json`).
    Defaults to `*.json`.
  - `--force`: (Not implemented) Could overwrite existing companies.
- Examples:

  ```bash
  python3 ./api/json2inv-companies.py "Customer_?.json"  # Imports Customer_A, Customer_B, etc.
  python3 ./api/json2inv-companies.py "Bourns_Inc.json"  # Imports single company
  python3 ./api/json2inv-companies.py                    # Imports all companies
  ```

### 3. rm-inv-companies.py

Deletes companies from InvenTree based on JSON files in `data/companies`.

Usage:

```bash
python3 ./api/rm-inv-companies.py [glob_pattern...] [--remove-json]
```

- Arguments:
  - `glob_pattern`: Glob patterns (e.g., `Customer_?.json`, `*.json`).
  - `--remove-json`: Deletes JSON files after successful deletion from InvenTree.
- Examples:

  ```bash
  python3 ./api/rm-inv-companies.py "Customer_?.json" --remove-json  # Deletes Customer_A, Customer_B, etc., and their JSON files
  python3 ./api/rm-inv-companies.py "*.json"                        # Deletes all companies
  ```

### 4. inv-parts2json.py

Exports parts and categories from InvenTree to a hierarchical structure in `data/parts`.

Usage:

```bash
python3 ./api/inv-parts2json.py
```

- Output: Creates `data/parts` with category folders (e.g., `Electronics/Passives/Capacitors`),
  `category.json` files, and part JSON files (e.g., `C_100nF_0402.json`). Sanitizes names
  (spaces to `_`, dots to `,`, `image` and `thumbnail` set to `""`).
- Example:

  ```bash
  python3 ./api/inv-parts2json.py
  # Creates data/parts/Electronics/Passives/Capacitors/C_100nF_0402.json
  ```

### 5. json2inv-parts.py

Imports parts from JSON files in `data/parts` to InvenTree, creating categories as needed.

Usage:

```bash
python3 ./api/json2inv-parts.py [glob_pattern...] [--force-ipn]
```

- Arguments:
  - `glob_pattern`: Optional glob patterns (e.g., `Electronics/Passives/Capacitors/C_*.json`).
    Defaults to `**/*.json` (recursive).
  - `--force-ipn`: Generates default IPN from part name if null or missing.
- Examples:

  ```bash
  python3 ./api/json2inv-parts.py "Electronics/Passives/Capacitors/C_*.json" --force-ipn  # Imports capacitors
  python3 ./api/json2inv-parts.py "Paint/Yellow_Paint.json" --force-ipn                   # Imports single part
  python3 ./api/json2inv-parts.py                                                         # Imports all parts
  ```

### 6. rm-inv-parts.py

Deletes parts from InvenTree based on JSON files in `data/parts`.

Usage:

```bash
python3 ./api/rm-inv-parts.py [glob_pattern...] [--remove-json]
```

- Arguments:
  - `glob_pattern`: Glob patterns (e.g., `Paint/Yellow_Paint.json`, `Electronics/Passives/Capacitors/C_*.json`).
  - `--remove-json`: Deletes JSON files after successful deletion from InvenTree.
- Examples:

  ```bash
  python3 ./api/rm-inv-parts.py "Paint/Yellow_Paint.json" --remove-json                   # Deletes single part and JSON
  python3 ./api/rm-inv-parts.py "Electronics/Passives/Capacitors/C_*.json"               # Deletes capacitors
  ```

### 7. rm-inv-categories.py

Deletes empty categories from InvenTree based on folders in `data/parts`.

Usage:

```bash
python3 ./api/rm-inv-categories.py [glob_pattern...] [--remove-json]
```

- Arguments:
  - `glob_pattern`: Glob patterns for category folders (e.g., `Electronics/Passives/Capacitors`, `*`).
  - `--remove-json`: Deletes `category.json` files after successful deletion.
- Examples:

  ```bash
  python3 ./api/rm-inv-categories.py "Category_0/Category_1/Category_2/Category_3/Category_4" --remove-json  # Deletes Category_4 if empty
  python3 ./api/rm-inv-parts.py "Electronics/Passives/Capacitors/C_*.json" && \
  python3 ./api/rm-inv-categories.py "Electronics/Passives/Capacitors" --remove-json  # Deletes parts then category
  ```

## Notes

- Sanitization: Company and part names have spaces replaced with `_`, dots removed (companies) or replaced with `,` (parts). Categories use `_` for spaces.
- Safety: Test on a non-production instance, as deletions are irreversible. Use `--remove-json` cautiously.
- Verification: After running scripts, verify results in the InvenTree web interface or via API:

  ```bash
  curl -H "Authorization: Token $INVENTREE_TOKEN" "http://inventree.local/api/company/"
  curl -H "Authorization: Token $INVENTREE_TOKEN" "http://inventree.local/api/part/?category=3"
  ```

- Troubleshooting: Check debug output for errors. Ensure `INVENTREE_URL` and `INVENTREE_TOKEN` are set correctly.
- Folder Naming: The `api` folder name is appropriate, as these scripts interact with the InvenTree API.
