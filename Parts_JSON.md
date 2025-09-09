# Inventory System Parts JSON Repository

The Inventory Management System Parts Data is saved in a Git Repository.

## Recommended JSON Structure

To import parts data into InvenTree from JSON files the folloing structure is recomended.

Categories, locations, manufacturer/supplier must exist before importing the parts.

```JSON
[
  {
    "id": "",
    "name": "Resistor 10k Ohm 1% 0603",
    "description": "SMD Resistor, 10k Ohm, 1% tolerance, 0603 package",
    "category": "Electronics/Resistors",
    "IPN": "R-0603-10K-1",
    "revision": "A",
    "keywords": "resistor, SMD, 10k, 0603",
    "units": "pcs",
    "minimum_stock": 100,
    "active": true,
    "assembly": false,
    "component": true,
    "trackable": true,
    "purchaseable": true,
    "salable": false,
    "virtual": false,
    "notes": "package size disipates 100mW w/ 75V and 1A working voltage and current, as well as 5A peak pulse",
    "default_location": "Inverness/Reciving",
    "default_supplier": "Anyapproved",
    "parameters": {
      "Resistance": "10k Ohm",
      "Tolerance": "1%",
      "Package": "0603"
    },
    "manufacturer_parts": [
      {
        "manufacturer": "Stackpole",
        "MPN": "RMCF0603FT10K0",
        "description": "see IPN description",
        "link": "https://www.seielect.com/catalog/sei-rmcf_rmcp.pdf",
        "note": "cost $0.00233 ea on a 5k reel from Digikey 7/12/25"
      },
      {
        "manufacturer": "Bourns",
        "MPN": "CR0603-FX-1002ELF",
        "description": "see IPN description",
        "link": "https://bourns.com/docs/product-datasheets/cr.pdf?sfvrsn=574d41f6_14",
        "note": "cost $0.00233 ea on a 5k reel from Digikey 7/12/25"
      },
      {
        "manufacturer": "Royalohm",
        "MPN": "CQ03WAF1002T5E",
        "description": "see IPN description",
        "link": "https://www.mouser.com/datasheet/2/1365/10-3358738.pdf",
        "note": "cost $0.001 ea on a 5k reel from Mouser 7/12/25"
      }
    ]
  }
]
```

``` JSON
[
  {
    "id": "",
    "name": "Capacitor 100nF 100V X7R 0603",
    "description": "Ceramic Capacitor, 100nF, 100V, X7R, 0603 package",
    "category": "Electronics/Capacitors",
    "IPN": "C-0603-0u1-100V-X7R-1",
    "revision": "A",
    "keywords": "capacitor, ceramic, 100nF, 0603",
    "units": "pcs",
    "minimum_stock": 100,
    "active": true,
    "assembly": false,
    "component": true,
    "trackable": true,
    "purchaseable": true,
    "salable": false,
    "virtual": false,
    "notes": "focus is on core specs: capacitance (100 nF), voltage (100 V), type (X7R), and tolerance (Â±10%)",
    "default_location": "Inverness/Reciving",
    "default_supplier": "Anyapproved",
    "parameters": {
      "Capacitance": "100nF",
      "Voltage": "100V",
      "Type": "X7R",
      "Package": "0603"
    },
    "manufacturer_parts": [
       {
        "manufacturer": "Murata",
        "MPN": "GRM188R72A104KA35D",
        "description": "see IPN description",
        "link": "https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM188R72A104KA35-01.pdf",
        "note": "cost $0.02854 ea on a 4k reel from Digikey 7/16/25"
      },
      {
        "manufacturer": "Samsung",
        "MPN": "CL10B104KC8NNNC",
        "description": "see IPN description",
        "link": "https://product.samsungsem.com/mlcc/CL10B104KC8NNN.do",
        "note": "cost $0.00706 ea on a 4k reel from Digikey 7/16/25"
      },
      {
        "manufacturer": "KYOCERA AVX",
        "MPN": "06031C104KAT2A",
        "description": "see IPN description",
        "link": "https://datasheets.kyocera-avx.com/X7RDielectric.pdf",
        "note": "cost $0.02590 ea on a 4k reel from Digikey 7/16/25"
      },
      {
        "manufacturer": "Yageo",
        "MPN": "CC0603KRX7R0BB104",
        "description": "see IPN description",
        "link": "https://www.yageo.com/upload/media/product/app/datasheet/mlcc/upy-np0x7r_mv_100-to-630v.pdf",
        "note": "cost $0.02690 ea on a 4k reel from Digikey 7/16/25"
      }
    ]
  }
]
```

## Git Repository Workflow

JSON files are stored in a dedicated folders (e.g., /data/parts/). Keep one part per file, this aids in tracking on Git but also allows incremental updates, importing in smaller batches helps to avoid server timeouts. There are a few discussions about large imports stalling.

``` bash
git pull origin main
jq . data/parts/Electronics/Resistors/R-0603-10K-1.json  # Validate JSON
inventree-part-import --configure data/parts/Electronics/Resistors/R-0603-10K-1.json
```

## Location

In InvenTree, the default_location field for a part specifies the default storage location where the part is typically stored. This field is part of the Part model and links to a StockLocation object in the database, which represents a physical or logical storage location (e.g., a warehouse, shelf, or bin). The default_location field in the Part model is a reference to a StockLocation object, which can be identified by its ID, name, or path in InvenTree’s hierarchical location structure. Locations in InvenTree are hierarchical, allowing you to define nested locations (e.g., Warehouse1 > ShelfA > Bin1). Each StockLocation has fields like: id, name, path, description, parent. The id is a Unique identifier (integer).The name is a Descriptive name (e.g., ShelfA). The path is teh Full path in the hierarchy (e.g., Warehouse1/ShelfA/Bin1). The description is an Optional description. The parent is a Reference to the parent location (if any).

Locations must exist in the database before they can be referenced by a part’s default_location. To import parts with default_location in these JSON files (stored in this Git repository), ensure the location references are valid and exist in InvenTree. Here’s how to structure the JSON that pre-creates locations.

``` JSON
[
  {
    "id": "",
    "name": "Warehouse1",
    "description": "Main warehouse",
    "parent": null
  },
  {
    "id": "",
    "name": "ShelfA",
    "description": "Shelf A in Warehouse1",
    "parent": "Warehouse1"
  },
  {
    "id": "",
    "name": "Bin1",
    "description": "Bin 1 on Shelf A",
    "parent": "Warehouse1/ShelfA"
  },
  {
    "id": "",
    "name": "ShelfB",
    "description": "Shelf B in Warehouse1",
    "parent": "Warehouse1"
  },
  {
    "id": "",
    "name": "Bin2",
    "description": "Bin 2 on Shelf B",
    "parent": "Warehouse1/ShelfB"
  }
]
```

## Internal Part Number associatetion with Manufacturer Part Number

In InvenTree, the IPN variable in the parts object refers to the Internal Part Number. It’s distinct from the Manufacturer Part Number (MPN). Using the MPN as the IPN can work but can also make it hard to manage parts when manufacturers change their numbering or a source equivalent is found. We generate our own IPN using the following formats: R-0603-100K-1, C-0603-0u1-100V-X7R-1, and TBD. The last number allows for none equivalent parts. Custom or in-house parts that don’t have an MPN will also have an IPN.

Associating multiple Manufacturer Part Number (MPN) with Your IPN for import into InvenTree.

```JSON
{
  "IPN": "R-0603-10K-1",
  "name": "Resistor 10k Ohm 1% 0603",
  "description": "SMD Resistor, 10k Ohm, 1% tolerance, 0603 package",
  "manufacturer_parts": [
    "manufacturer_parts": [
      {
        "manufacturer": "Stackpole",
        "MPN": "RMCF0603FT10K0",
        "description": "see IPN description",
        "link": "https://www.seielect.com/catalog/sei-rmcf_rmcp.pdf",
        "note": "cost $0.00233 ea on a 5k reel from Digikey 7/12/25"
      },
      {
        "manufacturer": "Bourns",
        "MPN": "CR0603-FX-1002ELF",
        "description": "see IPN description",
        "link": "https://bourns.com/docs/product-datasheets/cr.pdf?sfvrsn=574d41f6_14",
        "note": "cost $0.00233 ea on a 5k reel from Digikey 7/12/25"
      },
      {
        "manufacturer": "Royalohm",
        "MPN": "CQ03WAF1002T5E",
        "description": "see IPN description",
        "link": "https://www.mouser.com/datasheet/2/1365/10-3358738.pdf",
        "note": "cost $0.001 ea on a 5k reel from Mouser 7/12/25"
      }
    ]
  ]
}
```

## Manufacturers

In InvenTree, manufacturers are managed as part of the Company model, and can be imported using a JSON file to populate the database with manufacturer details before associating them with parts and Manufacturer Part Numbers (MPNs). Below is an example of a JSON structure for importing manufacturers into InvenTree. Manufacturers in InvenTree are stored as companies with a specific role (e.g., "manufacturer"). You can import them using the Company model. Here’s an example JSON file to import multiple manufacturers:

```JSON
[
  {
    "name": "Yageo",
    "description": "Global manufacturer of resistors and capacitors",
    "website": "https://www.yageo.com",
    "is_manufacturer": true,
    "is_supplier": false,
    "is_customer": false
  },
  {
    "name": "Vishay",
    "description": "Manufacturer of discrete semiconductors and passive components",
    "website": "https://www.vishay.com",
    "is_manufacturer": true,
    "is_supplier": false,
    "is_customer": false
  },
  {
    "name": "Texas Instruments",
    "description": "Leading semiconductor manufacturer",
    "website": "https://www.ti.com",
    "is_manufacturer": true,
    "is_supplier": false,
    "is_customer": false
  }
]
```

Once the manufacturers are imported, they can be referenced from the parts import JSON. In InvenTree, the manufacturer_parts list within a part’s JSON structure is used to associate a part with its manufacturer(s) and Manufacturer Part Number(s) (MPNs). By default, the manufacturer_parts list primarily includes fields for the manufacturer (referenced by name or ID) and the MPN. However, InvenTree’s ManufacturerPart model also supports additional fields, including a field for linking to datasheets. ...
