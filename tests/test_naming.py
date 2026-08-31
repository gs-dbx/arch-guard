"""Tests for rules/naming.py"""
import unittest

from arch_guard.rules.naming import NamingTablesRule, NamingBronzePrefixRule
from tests.helpers import BASE_CONTRACT, contract_with, make_ctx, parse


class TestNamingTables(unittest.TestCase):

    def _check(self, src, contract=None):
        path, tables = parse(src)
        ctx = make_ctx(path, tables=tables, contract=contract)
        return NamingTablesRule().check(ctx)

    def test_valid_name_passes(self):
        self.assertEqual(self._check("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass
        """), [])

    def test_camelcase_fires(self):
        findings = self._check("""
            import dlt
            @dlt.table(name="RawOrders", schema="bronze")
            def RawOrders():
                pass
        """)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "naming.table")
        self.assertEqual(findings[0].severity, "error")

    def test_function_name_fallback_when_no_name_kwarg(self):
        findings = self._check("""
            import dlt
            @dlt.table(schema="silver")
            def Silver_Orders():
                pass
        """)
        self.assertTrue(any("Silver_Orders" in f.message for f in findings))

    def test_missing_naming_section_skipped(self):
        self.assertEqual(self._check("""
            import dlt
            @dlt.table(name="RawOrders", schema="bronze")
            def RawOrders():
                pass
        """, contract=contract_with(naming={})), [])

    def test_custom_pattern_enforced(self):
        contract = contract_with(naming={
            "tables": {"pattern": "^tbl_[a-z0-9_]+$", "severity": "error"},
        })
        findings = self._check("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass
        """, contract=contract)
        self.assertEqual(len(findings), 1)

    def test_severity_driven_by_contract(self):
        contract = contract_with(naming={
            "tables": {"pattern": "^[a-z][a-z0-9_]+$", "severity": "warning"},
        })
        findings = self._check("""
            import dlt
            @dlt.table(name="RawOrders", schema="bronze")
            def RawOrders():
                pass
        """, contract=contract)
        self.assertEqual(findings[0].severity, "warning")


class TestNamingBronzePrefix(unittest.TestCase):

    def _check(self, src, contract=None):
        path, tables = parse(src)
        ctx = make_ctx(path, tables=tables, contract=contract)
        return NamingBronzePrefixRule().check(ctx)

    def test_prefix_passes(self):
        self.assertEqual(self._check("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass
        """), [])

    def test_missing_prefix_fires(self):
        findings = self._check("""
            import dlt
            @dlt.table(name="orders_bronze", schema="bronze")
            def orders_bronze():
                pass
        """)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "naming.bronze_prefix")
        self.assertEqual(findings[0].severity, "warning")

    def test_silver_table_not_checked(self):
        self.assertEqual(self._check("""
            import dlt
            @dlt.table(name="orders_silver", schema="silver")
            def orders_silver():
                pass
        """), [])

    def test_prefix_promoted_to_error_via_contract(self):
        contract = contract_with(naming={
            "tables":              BASE_CONTRACT["naming"]["tables"],
            "bronze_table_prefix": {"pattern": "^raw_", "severity": "error"},
        })
        findings = self._check("""
            import dlt
            @dlt.table(name="orders_bronze", schema="bronze")
            def orders_bronze():
                pass
        """, contract=contract)
        self.assertEqual(findings[0].severity, "error")


if __name__ == "__main__":
    unittest.main()
