"""Contract loading and validation against the JSON Schema."""
import json
from pathlib import Path

import jsonschema
import yaml


def load_and_validate(contract_path, schema_path=None):
    contract = yaml.safe_load(open(contract_path).read())

    if schema_path is None:
        schema_path = str(Path(contract_path).parent / "arch-contract.schema.json")

    if Path(schema_path).exists():
        schema = json.loads(open(schema_path).read())
        jsonschema.validate(contract, schema)

    return contract


def sanctioned_catalog_names(contract):
    return {c["name"] for c in contract.get("sanctioned_catalogs", [])}


def tier_read_allowed(tier, source_tier, contract):
    rule = contract.get("tiering", {}).get(tier, {})
    return source_tier in rule.get("may_read_from", [])


def tier_write_allowed(tier, target_tier, contract):
    rule = contract.get("tiering", {}).get(tier, {})
    return target_tier in rule.get("may_write_to", [])
