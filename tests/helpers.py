"""Shared test helpers — import from any test file in this package."""
import copy
import os
import tempfile
import textwrap

from arch_guard.parsers.dlt_python import parse_dlt_file
from arch_guard.rules._base import FileContext

BASE_CONTRACT = {
    "version": 1,
    "sanctioned_catalogs": [
        {"name": "dev_analytics",  "env": "dev"},
        {"name": "prod_analytics", "env": "prod"},
    ],
    "schemas": {
        "required": ["bronze", "silver", "gold"],
        "tier_map": {"bronze": "bronze", "silver": "silver", "gold": "gold"},
    },
    "tiering": {
        "bronze": {"may_read_from": ["external"], "may_write_to": ["bronze"]},
        "silver": {"may_read_from": ["bronze"],   "may_write_to": ["silver"]},
        "gold":   {"may_read_from": ["silver"],   "may_write_to": ["gold"]},
    },
    "naming": {
        "tables":              {"pattern": "^[a-z][a-z0-9_]+$", "severity": "error"},
        "bronze_table_prefix": {"pattern": "^raw_",             "severity": "warning"},
    },
    "required_tags": {
        "tables": ["owner", "cost_center"],
    },
}


def contract_with(**overrides):
    """Return a deep copy of BASE_CONTRACT with top-level keys replaced."""
    c = copy.deepcopy(BASE_CONTRACT)
    c.update(overrides)
    return c


def parse(src):
    """Write src to a temp file, parse DLT tables, return (path, tables)."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(textwrap.dedent(src))
        path = f.name
    return path, parse_dlt_file(path)


def make_ctx(path, tables=None, raw_config=None, contract=None):
    """Build a FileContext for use in rule.check() calls in tests."""
    return FileContext(
        file=path,
        contract=contract if contract is not None else BASE_CONTRACT,
        tables=tables if tables is not None else [],
        raw_config=raw_config if raw_config is not None else {},
    )


def fixture_path(name):
    """Return the absolute path to a file in tests/fixtures/."""
    return os.path.join(os.path.dirname(__file__), "fixtures", name)
