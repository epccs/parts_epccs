# Copilot Instructions for parts_epccs

This repository contains JSON data and documentation for an Inventory Management System designed for use with InvenTree.

## Guidelines for Copilot Usage

- **JSON Structure:** Follow the examples in [Parts_JSON.md](../Parts_JSON.md) for creating and updating part, category, manufacturer, and stock location JSON files.
- **File Organization:** 
  - Place part files in `data/parts/Electronics/Resistors/` or `data/parts/Electronics/Capacitors/` as appropriate.
  - Categories are stored in `data/parts/category.json` and `data/parts/Electronics/category.json`.
  - Manufacturer data is in `data/manufacturer.json`.
  - Stock locations are in `data/stocklocation.json`.
- **Naming Conventions:** Use the IPN format described in [Parts_JSON.md](../Parts_JSON.md) for new parts.
- **Documentation:** Update [README.md](../README.md) and [Docker.md](../Docker.md) when making changes that affect setup or usage.
- **Validation:** Ensure all JSON files are valid before committing (e.g., use `jq . filename.json`).
- **No Source Code:** This repository is for data and documentation only; do not add application source code.

## Copilot Prompts

- When asked for part data, suggest the correct JSON structure and file location.
- When asked about setup, reference [Docker.md](../Docker.md).
- When asked about categories, manufacturers, or locations, reference the appropriate JSON files.
- Always provide file paths and symbol links for referenced content.

## Contribution

- Follow the structure and conventions in existing files.
- Validate all changes before submitting pull requests.
- Use clear commit messages describing the data or