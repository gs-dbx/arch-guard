"""Tests for rules/catalog.py"""
import unittest

from arch_guard.rules.catalog import SanctionedCatalogDltRule, SanctionedCatalogLiteralsRule
from tests.helpers import BASE_CONTRACT, contract_with, fixture_path, make_ctx, parse


class TestSanctionedCatalogDlt(unittest.TestCase):

    def _check(self, src, contract=None):
        path, tables = parse(src)
        ctx = make_ctx(path, tables=tables, contract=contract)
        return SanctionedCatalogDltRule().check(ctx)

    def test_sanctioned_catalog_passes(self):
        findings = self._check("""
            import dlt
            @dlt.table(catalog="dev_analytics", schema="bronze", name="raw_orders")
            def raw_orders():
                return dlt.read_stream("source")
        """)
        self.assertEqual(findings, [])

    def test_unsanctioned_catalog_fires(self):
        findings = self._check("""
            import dlt
            @dlt.table(catalog="rogue_catalog", schema="bronze", name="raw_orders")
            def raw_orders():
                return dlt.read_stream("source")
        """)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "catalog.unsanctioned")
        self.assertEqual(findings[0].severity, "error")
        self.assertIn("rogue_catalog", findings[0].message)

    def test_no_catalog_kwarg_skipped(self):
        # Catalog set at bundle level in databricks.yml — should not fire.
        findings = self._check("""
            import dlt
            @dlt.table(schema="bronze", name="raw_orders")
            def raw_orders():
                return dlt.read_stream("source")
        """)
        self.assertEqual(findings, [])

    def test_multiple_tables_only_bad_one_fires(self):
        findings = self._check("""
            import dlt
            @dlt.table(catalog="dev_analytics", schema="bronze", name="raw_a")
            def raw_a():
                pass

            @dlt.table(catalog="rogue_catalog", schema="bronze", name="raw_b")
            def raw_b():
                pass
        """)
        self.assertEqual(len(findings), 1)
        self.assertIn("raw_b", findings[0].message)

    def test_new_catalog_in_contract_passes(self):
        contract = contract_with(sanctioned_catalogs=[
            {"name": "dev_analytics",    "env": "dev"},
            {"name": "prod_analytics",   "env": "prod"},
            {"name": "new_team_catalog", "env": "dev"},
        ])
        findings = self._check("""
            import dlt
            @dlt.table(catalog="new_team_catalog", schema="bronze", name="raw_orders")
            def raw_orders():
                pass
        """, contract=contract)
        self.assertEqual(findings, [])


class TestSanctionedCatalogLiterals(unittest.TestCase):

    def _check(self, src):
        path, _ = parse(src)
        ctx = make_ctx(path)
        return SanctionedCatalogLiteralsRule().check(ctx)

    def test_unsanctioned_literal_fires(self):
        findings = self._check("""
            df = spark.table("rogue_catalog.bronze.orders")
        """)
        self.assertEqual(len(findings), 1)
        self.assertIn("rogue_catalog", findings[0].message)

    def test_sanctioned_literal_passes(self):
        findings = self._check("""
            df = spark.table("dev_analytics.bronze.orders")
        """)
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
