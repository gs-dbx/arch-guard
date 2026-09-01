import unittest

from arch_guard.rules.datasets import DatasetPolicyRule
from tests.helpers import contract_with, make_ctx, parse


DATASETS = {
    "severity": "warning",
    "required_tags": ["dataset_name"],
    "allowed": [{"name": "orders", "domain": "sales"}],
}
CONVENTION = {
    "prefix": "csb",
    "environments": ["dev", "test", "preprod", "prod"],
    "domain_layers": {"bronze_suffix": "stage", "silver_suffix": "cleansed"},
    "gold_catalogs": ["analytics", "apps"],
}


class TestDatasetPolicy(unittest.TestCase):

    def _check(self, schema="orders", catalog="csb_dev_sales_stage", props=None,
               datasets=DATASETS):
        props = props or {}
        source = '''
import dlt
@dlt.table(name="raw_orders", schema="{}", catalog="{}", table_properties={})
def raw_orders():
    pass
'''.format(schema, catalog, repr(props))
        path, tables = parse(source)
        contract = contract_with(datasets=datasets, catalog_convention=CONVENTION)
        return DatasetPolicyRule().check(make_ctx(path, tables=tables, contract=contract))

    def test_compliant_dataset_passes(self):
        self.assertEqual(self._check(props={"dataset_name": "orders"}), [])

    def test_unapproved_dataset_fires(self):
        message = self._check(schema="unknown")[0].message
        self.assertIn("not approved", message)
        self.assertIn("ask the platform admin", message)

    def test_missing_schema_fires_with_admin_guidance(self):
        self.assertIn("ask the platform admin", self._check(schema="")[0].message)

    def test_missing_tag_fires(self):
        message = self._check()[0].message
        self.assertIn("missing", message)
        self.assertIn("table_properties", message)

    def test_mismatched_tag_fires(self):
        self.assertIn("schema='orders'", self._check(
            props={"dataset_name": "customers"})[0].message)

    def test_wrong_domain_catalog_fires(self):
        findings = self._check(catalog="csb_dev_finance_stage",
                               props={"dataset_name": "orders"})
        self.assertIn("registered to domain 'sales'", findings[0].message)

    def test_absent_config_skips(self):
        self.assertEqual(self._check(datasets={}), [])
