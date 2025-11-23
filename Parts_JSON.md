# Inventory System Parts JSON Repository

The Inventory Management System Data is saved in a Git Repository. The data shown in this public repository is from an InvenTree developer install instance (it is fictitious).

## Companies JSON Structure

```JSON
{
    "name": "DigiKey",
    "description": "DigiKey Electronics",
    "website": "https://www.digikey.com/",
    "phone": "",
    "address": "04964 Cox View Suite 815, 94832, Wesleyport, Delaware, Bolivia",
    "email": null,
    "currency": "USD",
    "contact": "",
    "link": "",
    "image": "",
    "active": true,
    "is_customer": false,
    "is_manufacturer": false,
    "is_supplier": true,
    "tax_id": "",
    "addresses": [
        {
            "title": "Primary Address",
            "primary": false,
            "line1": "2038 Carla Tunnel",
            "line2": "",
            "postal_code": "59870",
            "postal_city": "West Robert",
            "province": "Rhode Island",
            "country": "United Kingdom",
            "shipping_notes": "",
            "internal_shipping_notes": "",
            "link": ""
        },
        {
            "title": "Secondary Address",
            "primary": true,
            "line1": "04964 Cox View Suite 815",
            "line2": "",
            "postal_code": "94832",
            "postal_city": "Wesleyport",
            "province": "Delaware",
            "country": "Bolivia",
            "shipping_notes": "",
            "internal_shipping_notes": "",
            "link": ""
        }
    ]
}
```

## Parts JSON Structure

Part names are sanitized so they can be used as file names. The companies DigiKey and Samsung_Electro-Mechanics must be loaded in the system before this part.

```JSON
{
    "name": "C_100nF_0603",
    "revision": "",
    "IPN": null,
    "description": "Ceramic capacitor, 100nF in 0603 SMD package",
    "keywords": "cap smd ceramic",
    "units": "",
    "minimum_stock": 0.0,
    "assembly": false,
    "component": true,
    "trackable": false,
    "purchaseable": true,
    "salable": false,
    "virtual": false,
    "is_template": false,
    "variant_of": null,
    "validated_bom": false,
    "image": "",
    "thumbnail": "",
    "suppliers": [
        {
            "supplier_name": "DigiKey",
            "SKU": "1276-CL10B104KB8NNNLTR-ND",
            "description": "CAP CER 0.1UF 50V X7R 0603",
            "link": "https://www.digikey.com/product-detail/en/samsung-electro-mechanics/CL10B104KB8NNNL/1276-CL10B104KB8NNNLTR-ND/3894274",
            "note": null,
            "packaging": null,
            "price_breaks": [
                {
                    "quantity": 20.0,
                    "price": 2.35,
                    "price_currency": "USD"
                },
                {
                    "quantity": 1000.0,
                    "price": 0.184,
                    "price_currency": "USD"
                }
            ],
            "manufacturer_name": "Samsung_Electro-Mechanics",
            "MPN": "CL10B104KB8NNNL",
            "mp_description": null,
            "mp_link": null
        }
    ]
}
```

## Assembly JSON Structures

Part assembly names are sanitized so they can be used as file names. The parts (Leg, Round_Top, and Wood_Screw) must be loaded in the system before this part.

Part

```JSON
{
    "name": "Round_Table",
    "revision": "",
    "IPN": "",
    "description": "A round table - comes in a variety of colors",
    "keywords": "",
    "units": "",
    "minimum_stock": 0.0,
    "assembly": true,
    "component": false,
    "trackable": false,
    "purchaseable": false,
    "salable": true,
    "virtual": true,
    "is_template": true,
    "variant_of": null,
    "validated_bom": false,
    "image": "",
    "thumbnail": "",
    "suppliers": []
}
```

BOM

```JSON
[
    {
        "quantity": 4.0,
        "note": "",
        "validated": true,
        "active": true,
        "sub_part": {
            "name": "Leg",
            "IPN": "",
            "description": "Leg for a chair or a table"
        }
    },
    {
        "quantity": 1.0,
        "note": "",
        "validated": true,
        "active": true,
        "sub_part": {
            "name": "Round_Top",
            "IPN": "",
            "description": "Table top - round"
        }
    },
    {
        "quantity": 12.0,
        "note": "",
        "validated": true,
        "active": true,
        "sub_part": {
            "name": "Wood_Screw",
            "IPN": "",
            "description": "Screw for fixing wood to other wood"
        }
    }
]
```

## File system structure

Parts with no dependencies must be loaded before those with dependencies, and lower-level dependencies must be loaded before higher-level ones.

```text
data/
├── companies/                 # Companies (Suppliers and Manufacturers) from inv-companies2json.py
│   └── DigiKey.json
│
├── parts/                     # all parts (templates, assemblies, real parts)
│   ├── 0/Electronics
│   ├── 0/category.json
│   │ 
│   │                          # Level one parts have no dependencies (no variant_of, no BOM sub-parts)
│   ├── 1/Electronics/C_100nF_0402[.ver].json                   # parts can have version
│   │  
│   │                          # Level based on max dependency level + 1
│   ├── <level>/Electronics/PCBA/Widget_Board[.ver].json        # Dependencies include variant_of and 
│   └── [<level>/Electronics/PCBA/Widget_Board[.ver].bom.json]  # BOM sub-parts
│
```
