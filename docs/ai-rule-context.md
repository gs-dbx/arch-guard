# arch-guard: AI Rule-Writing Context

Paste this document at the start of a conversation with any AI assistant to give
it everything it needs to write a new arch-guard rule from scratch.

---

## What arch-guard is

A CI/CD tool that checks Databricks pipeline code against a machine-readable
architecture contract (`arch-contract.yaml`). It runs as a GitHub Actions workflow
on every PR and emits findings as SARIF inline annotations and a job summary.

Rules are Python classes. The checker discovers them automatically via a registry.
Your job is to write a rule class, register it, and write its tests.

---

## The interfaces you must implement

### Rule base class (from `arch_guard/rules/_base.py`)

```python
class Rule(object):
    rule_id = None      # str: dotted id, e.g. "governance.missing_tag"
    applies_to = []     # list: which file types trigger this rule

    def check(self, ctx):
        # type: (FileContext) -> list[Finding]
        raise NotImplementedError
```

### FileContext (what check() receives)

```python
class FileContext(object):
    file        # str: repo-relative path, e.g. "pipelines/ingest.py"
    contract    # dict: full arch-contract.yaml loaded as Python dict
    tables      # list[TableDef]: DLT tables in this file ([] for non-DLT files)
    raw_config  # dict: parsed YAML (populated for databricks.yml files only)
```

### Finding (what check() returns)

```python
class Finding(object):
    rule_id     # str: use self.rule_id
    message     # str: plain English, name the offending value
    file        # str: use ctx.file
    line        # int: line number in the file
    severity    # str: "error" | "warning" | "note"
```

**Always drive severity from the contract, not hardcoded:**
```python
sev = ctx.contract.get("naming", {}).get("tables", {}).get("severity", "warning")
```

---

## applies_to values

| Value | File type | ctx.tables | ctx.raw_config |
|---|---|---|---|
| `"dlt_python"` | .py with @dlt.table | populated | {} |
| `"raw_python"` | .py without @dlt.table | [] | {} |
| `"dab_yaml"` | databricks.yml | [] | populated |

---

## TableDef — one @dlt.table function

```python
t.func_name          # str: Python function name
t.logical_name       # str: name= kwarg if set, else func_name
t.line               # int: line of the decorator
t.is_view            # bool: True if @dlt.view
t.decorator_catalog  # str | None: catalog= kwarg value
t.decorator_schema   # str | None: schema= kwarg value
t.table_properties   # dict: from table_properties={...} kwarg
t.inferred_tier      # str | None: "bronze"|"silver"|"gold" from schema= or name prefix
t.sources            # list[SourceRef]: dlt.read() / dlt.read_stream() calls
```

## SourceRef — one dlt.read() call inside a table function

```python
src.table_ref    # str: argument passed to dlt.read()
src.call_line    # int: line number
src.streaming    # bool: True for dlt.read_stream()
```

---

## arch-contract.yaml structure

```python
contract = {
    "version": 1,

    "sanctioned_catalogs": [
        {"name": "dev_analytics",  "env": "dev"},
        {"name": "prod_analytics", "env": "prod"},
    ],

    "external_sources": [
        {"name": "kafka_events",     "type": "kafka"},
        {"name": "s3_landing_zone",  "type": "cloud_storage"},
    ],

    "schemas": {
        "required": ["bronze", "silver", "gold"],
        "tier_map": {"bronze": "bronze", "silver": "silver", "gold": "gold"},
    },

    "tiering": {
        "bronze": {"may_read_from": ["external"], "may_write_to": ["bronze"]},
        "silver": {"may_read_from": ["bronze"],   "may_write_to": ["silver"]},
        "gold":   {"may_read_from": ["silver"],   "may_write_to": ["gold"], "serving": True},
    },

    "naming": {
        "tables":              {"pattern": "^[a-z][a-z0-9_]+$", "severity": "error"},
        "bronze_table_prefix": {"pattern": "^raw_",             "severity": "warning"},
        "pipelines":           {"pattern": "^plp_(bronze|silver|gold)_[a-z0-9_]+$", "severity": "error"},
    },

    "required_tags": {
        "tables":    ["owner", "cost_center"],
        "pipelines": ["owner"],
    },

    "overrides": {
        "mechanism": "pr_label",
        "label": "arch-override-approved",
        "authorized_teams": ["data-platform-admins"],
        "require_reason": True,
    },
}
```

---

## Complete worked example

```python
# arch_guard/rules/required_tags.py
from arch_guard.findings import Finding
from arch_guard.rules._base import FileContext, Rule, register


@register
class RequiredTagsRule(Rule):
    """Every @dlt.table must declare required governance tags in table_properties."""

    rule_id = "governance.missing_tag"
    applies_to = ["dlt_python"]

    def check(self, ctx):
        # type: (FileContext) -> list
        required = ctx.contract.get("required_tags", {}).get("tables", [])
        if not required:
            return []

        findings = []
        for t in ctx.tables:
            for tag in required:
                if tag not in t.table_properties:
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        message="Table '{}' is missing required tag '{}'.".format(
                            t.logical_name, tag),
                        file=ctx.file,
                        line=t.line,
                        severity="warning",
                    ))
        return findings
```

Then add `required_tags` to the imports in `arch_guard/rules/__init__.py`:
```python
from arch_guard.rules import catalog, naming, medallion, dab_config, required_tags  # noqa
```

---

## Corresponding test

```python
# tests/test_required_tags.py
import unittest
from arch_guard.rules.required_tags import RequiredTagsRule
from tests.helpers import BASE_CONTRACT, contract_with, make_ctx, parse


class TestRequiredTags(unittest.TestCase):

    def _check(self, src, contract=None):
        path, tables = parse(src)
        ctx = make_ctx(path, tables=tables, contract=contract)
        return RequiredTagsRule().check(ctx)

    def test_table_with_all_tags_passes(self):
        self.assertEqual(self._check("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze",
                       table_properties={"owner": "team-a", "cost_center": "eng"})
            def raw_orders():
                pass
        """), [])

    def test_missing_owner_fires(self):
        findings = self._check("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze",
                       table_properties={"cost_center": "eng"})
            def raw_orders():
                pass
        """)
        self.assertEqual(len(findings), 1)
        self.assertIn("owner", findings[0].message)
        self.assertEqual(findings[0].rule_id, "governance.missing_tag")

    def test_no_required_tags_section_skipped(self):
        self.assertEqual(self._check("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass
        """, contract=contract_with(required_tags={})), [])
```

---

## Rules to follow when writing a new rule

1. **Never open files yourself** — use `ctx.tables`, `ctx.raw_config`, or `ctx.file`
   only for passing to a Finding. The file is already parsed before check() runs.

2. **Return an empty list, never None** — `check()` must always return a list.

3. **One Finding per specific violation** — if two tables have the same problem,
   emit two Findings, not one combined message.

4. **Drive severity from the contract** — read it from `ctx.contract`, default to
   `"warning"` if the key is absent. Never hardcode `"error"`.

5. **Skip gracefully when config is absent** — if your rule reads a contract section
   that doesn't exist, return `[]`. Don't raise an exception.

6. **Test the config-absent case** — always write a test where the contract section
   your rule reads is empty or missing. This is the most common source of bugs.

7. **Use `self.rule_id` in Finding, not a string literal** — so renaming the class
   attribute propagates automatically.

8. **Line numbers matter** — use `t.line` for table-level findings, `src.call_line`
   for read-call findings. Avoid `line=1` except for file-level issues (DAB YAML).

---

## Prompt template for asking an AI to write a rule

```
I'm adding a new rule to arch-guard. Use the context in docs/ai-rule-context.md.

Rule to implement:
  Name: <rule name>
  rule_id: <domain.violation>
  applies_to: <dlt_python | dab_yaml | raw_python>
  What it checks: <plain English description>
  Contract field it reads: contract["<section>"]["<key>"]
  Severity: driven from contract, default warning

Produce:
  1. arch_guard/rules/<filename>.py  — the Rule class with @register
  2. The one-line addition to arch_guard/rules/__init__.py
  3. tests/test_<filename>.py  — happy path, violation, config-absent, severity tests
```
