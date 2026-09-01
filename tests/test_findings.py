import io
import unittest

from arch_guard.findings import write_summary


class TestSummary(unittest.TestCase):

    def test_clean_summary_lists_reviewed_files(self):
        output = io.StringIO()
        write_summary([], output, advisory=False,
                      checked_files=["pipelines/serve.py", "databricks.yml"])
        rendered = output.getvalue()
        self.assertIn("Architecture review passed", rendered)
        self.assertIn("Reviewed 2 file(s)", rendered)
        self.assertIn("pipelines/serve.py", rendered)


if __name__ == "__main__":
    unittest.main()
