"""Unit tests for deterministic rules (stdlib unittest — no pytest required)."""
import textwrap
import tempfile
import unittest
from pathlib import Path

from arch_guard.parsers.dlt_python import parse_dlt_file
from arch_guard.rules.catalog import rule_sanctioned_catalog_dlt
from arch_guard.rules.naming import rule_naming_tables, rule_naming_bronze_prefix
from arch_guard.rules.medallion import rule_medallion_flow

CONTRACT = {
    "version": 1,
    "sanctioned_catalogs": [
        {"name": "dev_analytics", "env": "dev"},
        {"name": "prod_analytics", "env": "prod"},
    ],
    "schemas": {
        "required": ["bronze", "silver", "gold"],
        "tier_map": {"bronze": "bronze", "silver": "silver", "gold": "gold"},
    },
    "tiering": {
        "bronze": {"may_read_from": ["external"], "may_write_to": ["bronze"]},
        "silver": {"may_read_from": ["bronze"], "may_write_to": ["silver"]},
        "gold":   {"may_read_from": ["silver"],  "may_write_to": ["gold"]},
    },
    "naming": {
        "tables": {"pattern": "^[a-z][a-z0-9_]+$", "severity": "error"},
        "bronze_table_prefix": {"pattern": "^raw_", "severity": "warning"},
    },
}


def _parse(src: str):
    """Write src to a temp file, parse it, and return (path, tables)."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(textwrap.dedent(src))
        path = f.name
    return path, parse_dlt_file(path)


# ---------------------------------------------------------------------------
# Sanctioned catalog rule
# ---------------------------------------------------------------------------

class TestSanctionedCatalog(unittest.TestCase):
    def test_sanctioned_catalog_passes(self):
        path, tables = _parse("""
            import dlt
            @dlt.table(catalog="dev_analytics", schema="bronze", name="raw_orders")
            def raw_orders():
                return dlt.read_stream("source")
        """)
        self.assertEqual(rule_sanctioned_catalog_dlt(path, tables, CONTRACT), [])

    def test_unsanctioned_catalog_fires(self):
        path, tables = _parse("""
            import dlt
            @dlt.table(catalog="rogue_catalog", schema="bronze", name="raw_orders")
            def raw_orders():
                return dlt.read_stream("source")
        """)
        findings = rule_sanctioned_catalog_dlt(path, tables, CONTRACT)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "catalog.unsanctioned")
        self.assertEqual(findings[0].severity, "error")
        self.assertIn("rogue_catalog", findings[0].message)

    def test_no_catalog_kwarg_skipped(self):
        """When no catalog kwarg is set, the rule does not fire (catalog set by bundle)."""
        path, tables = _parse("""
            import dlt
            @dlt.table(schema="bronze", name="raw_orders")
            def raw_orders():
                return dlt.read_stream("source")
        """)
        self.assertEqual(rule_sanctioned_catalog_dlt(path, tables, CONTRACT), [])


# ---------------------------------------------------------------------------
# Naming rules
# ---------------------------------------------------------------------------

class TestNaming(unittest.TestCase):
    def test_valid_table_name_passes(self):
        path, tables = _parse("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass
        """)
        self.assertEqual(rule_naming_tables(path, tables, CONTRACT), [])

    def test_camelcase_fires(self):
        path, tables = _parse("""
            import dlt
            @dlt.table(name="RawOrders", schema="bronze")
            def RawOrders():
                pass
        """)
        findings = rule_naming_tables(path, tables, CONTRACT)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "naming.table")
        self.assertEqual(findings[0].severity, "error")

    def test_bronze_prefix_warning_fires(self):
        path, tables = _parse("""
            import dlt
            @dlt.table(name="orders_bronze", schema="bronze")
            def orders_bronze():
                pass
        """)
        findings = rule_naming_bronze_prefix(path, tables, CONTRACT)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "naming.bronze_prefix")
        self.assertEqual(findings[0].severity, "warning")

    def test_bronze_prefix_passes(self):
        path, tables = _parse("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass
        """)
        self.assertEqual(rule_naming_bronze_prefix(path, tables, CONTRACT), [])

    def test_function_name_used_when_no_name_kwarg(self):
        """Logical name falls back to the function name when name= is absent."""
        path, tables = _parse("""
            import dlt
            @dlt.table(schema="silver")
            def Silver_Orders():
                pass
        """)
        findings = rule_naming_tables(path, tables, CONTRACT)
        self.assertTrue(any("Silver_Orders" in f.message for f in findings))


# ---------------------------------------------------------------------------
# Medallion flow rule
# ---------------------------------------------------------------------------

class TestMedallionFlow(unittest.TestCase):
    def test_valid_silver_reads_bronze(self):
        path, tables = _parse("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass

            @dlt.table(name="clean_orders", schema="silver")
            def clean_orders():
                return dlt.read("raw_orders")
        """)
        self.assertEqual(rule_medallion_flow(path, tables, CONTRACT), [])

    def test_gold_skipping_silver_fires(self):
        """Gold reading directly from bronze skips silver — illegal."""
        path, tables = _parse("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass

            @dlt.table(name="orders_report", schema="gold")
            def orders_report():
                return dlt.read("raw_orders")
        """)
        findings = rule_medallion_flow(path, tables, CONTRACT)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "medallion.illegal_read")
        self.assertEqual(findings[0].severity, "error")
        self.assertIn("gold", findings[0].message)
        self.assertIn("bronze", findings[0].message)

    def test_silver_reading_gold_fires(self):
        """Silver reading from gold is a backwards flow — illegal."""
        path, tables = _parse("""
            import dlt
            @dlt.table(name="orders_report", schema="gold")
            def orders_report():
                pass

            @dlt.table(name="clean_orders", schema="silver")
            def clean_orders():
                return dlt.read("orders_report")
        """)
        findings = rule_medallion_flow(path, tables, CONTRACT)
        self.assertEqual(len(findings), 1)
        self.assertIn("silver", findings[0].message)

    def test_unknown_source_tier_skipped(self):
        """Can't infer source tier → skip rather than false-positive."""
        path, tables = _parse("""
            import dlt
            @dlt.table(name="clean_orders", schema="silver")
            def clean_orders():
                return dlt.read("some_external_feed")
        """)
        self.assertEqual(rule_medallion_flow(path, tables, CONTRACT), [])


if __name__ == "__main__":
    unittest.main()
