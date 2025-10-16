#!/bin/bash
# Manufacturer API - Retrieve a list of manufacturers
# export INVENTREE_TOKEN="not-a-real-token"
curl -X GET "http://localhost:8000/api/company/?limit=5" -H "Authorization: Token ${INVENTREE_TOKEN}" -H "Accept: application/json"