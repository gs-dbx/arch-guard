"""Tests for rules/medallion.py"""
import unittest

from arch_guard.parsers.dlt_python import parse_dlt_file
from arch_guard.rules.medallion import MedallionFlowRule
from tests.helpers import BASE_CONTRACT, contract_with, fixture_path, make_ctx, parse


class TestMedallionFlow(unittest.TestCase):

    def _check(self, src, contract=None):
        path, tables = parse(src)
        ctx = make_ctx(path, tables=tables, contract=contract)
        return MedallionFlowRule().check(ctx)

    def test_silver_reads_bronze_passes(self):
        self.assertEqual(self._check("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass

            @dlt.table(name="clean_orders", schema="silver")
            def clean_orders():
                return dlt.read("raw_orders")
        """), [])

    def test_gold_reads_silver_passes(self):
        self.assertEqual(self._check("""
            import dlt
            @dlt.table(name="clean_orders", schema="silver")
            def clean_orders():
                pass

            @dlt.table(name="orders_report", schema="gold")
            def orders_report():
                return dlt.read("clean_orders")
        """), [])

    def test_gold_skipping_silver_fires(self):
        findings = self._check("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass

            @dlt.table(name="orders_report", schema="gold")
            def orders_report():
                return dlt.read("raw_orders")
        """)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "medallion.illegal_read")
        self.assertEqual(findings[0].severity, "error")
        self.assertIn("gold", findings[0].message)
        self.assertIn("bronze", findings[0].message)

    def test_silver_reading_gold_fires(self):
        findings = self._check("""
            import dlt
            @dlt.table(name="orders_report", schema="gold")
            def orders_report():
                pass

            @dlt.table(name="clean_orders", schema="silver")
            def clean_orders():
                return dlt.read("orders_report")
        """)
        self.assertEqual(len(findings), 1)
        self.assertIn("silver", findings[0].message)

    def test_unknown_source_tier_skipped(self):
        self.assertEqual(self._check("""
            import dlt
            @dlt.table(name="clean_orders", schema="silver")
            def clean_orders():
                return dlt.read("some_external_feed")
        """), [])

    def test_fixture_gold_illegal_read(self):
        path = fixture_path("gold_illegal_read.py")
        tables = parse_dlt_file(path)
        ctx = make_ctx(path, tables=tables)
        findings = MedallionFlowRule().check(ctx)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "medallion.illegal_read")

    def test_custom_tiering_in_contract(self):
        # Adding a staging tier to the graph — the rule enforces it without code changes
        contract = contract_with(tiering={
            "bronze":  {"may_read_from": ["external"], "may_write_to": ["bronze"]},
            "staging": {"may_read_from": ["bronze"],   "may_write_to": ["staging"]},
            "silver":  {"may_read_from": ["staging"],  "may_write_to": ["silver"]},
            "gold":    {"may_read_from": ["silver"],   "may_write_to": ["gold"]},
        })
        findings = self._check("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass

            @dlt.table(name="clean_orders", schema="silver")
            def clean_orders():
                return dlt.read("raw_orders")
        """, contract=contract)
        self.assertEqual(len(findings), 1)

    def test_catalog_suffix_infers_tier_for_dataset_schema(self):
        contract = contract_with(catalog_convention={
            "prefix": "csb",
            "environments": ["dev", "test", "preprod", "prod"],
            "domain_layers": {"bronze_suffix": "stage", "silver_suffix": "cleansed"},
            "gold_catalogs": ["analytics", "apps"],
        })
        findings = self._check('''
            import dlt
            @dlt.table(name="raw_orders", schema="orders", catalog="csb_dev_sales_stage")
            def raw_orders():
                pass

            @dlt.table(name="orders_report", schema="orders", catalog="csb_dev_analytics")
            def orders_report():
                return dlt.read("raw_orders")
        ''', contract=contract)
        self.assertEqual(len(findings), 1)
        self.assertIn("tier=gold", findings[0].message)


if __name__ == "__main__":
    unittest.main()
