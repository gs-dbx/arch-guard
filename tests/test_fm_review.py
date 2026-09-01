import unittest

from arch_guard.fm_review import (
    _build_system_prompt,
    _build_user_message,
    _is_reviewable,
    _parse_and_validate,
)


class TestFmReview(unittest.TestCase):

    def test_prompt_covers_jobs_without_prescribing_customer_topology(self):
        prompt = _build_system_prompt({
            "sanctioned_catalogs": [{"name": "approved", "env": "dev"}],
            "catalog_convention": {"prefix": "csb"},
            "datasets": {
                "allowed": [{"name": "orders", "domain": "sales"}],
                "required_tags": ["dataset_name"],
            },
            "tiering": {},
        }, [])
        self.assertIn("ordinary jobs as complementary", prompt)
        self.assertIn("Never prescribe catalogs per environment", prompt)
        self.assertIn("approved", prompt)
        self.assertIn("Environments represented by sanctioned catalogs: ['dev']", prompt)
        self.assertIn("orders (domain sales)", prompt)
        self.assertIn("Required dataset tags: ['dataset_name']", prompt)

    def test_user_message_uses_file_language(self):
        self.assertIn("```sql\nSELECT 1", _build_user_message("query.sql", "SELECT 1"))
        self.assertIn("```yaml\nresources:", _build_user_message(
            "databricks.yml", "resources:"))

    def test_reviewable_assets_exclude_unrelated_yaml(self):
        self.assertTrue(_is_reviewable("jobs/load.py"))
        self.assertTrue(_is_reviewable("sql/load.sql"))
        self.assertTrue(_is_reviewable("databricks.yml"))
        self.assertFalse(_is_reviewable("arch-contract.yaml"))
        self.assertFalse(_is_reviewable(".github/workflows/ci.yml"))

    def test_general_rule_id_validates(self):
        raw = ('{"findings":[{"rule_id":"de.reliability.non_idempotent_write",'
               '"severity":"warning","file":"job.py","line":3,'
               '"message":"[LLM] Write is not safe to retry."}]}')
        self.assertEqual(len(_parse_and_validate(raw)), 1)

    def test_legacy_dlt_rule_id_is_rejected(self):
        raw = ('{"findings":[{"rule_id":"dlt.quality.no_expect",'
               '"severity":"warning","file":"pipeline.py","line":3,'
               '"message":"[LLM] Missing an expectation."}]}')
        self.assertEqual(_parse_and_validate(raw), [])


if __name__ == "__main__":
    unittest.main()
