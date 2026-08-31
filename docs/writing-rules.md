# Writing a New arch-guard Rule

Rules are the unit of work in arch-guard. Each rule is a Python class that
receives a parsed representation of one file and returns a list of findings.
`check.py` never needs to change when you add a rule.

---

## 1. Create the rule file

Put it in `arch_guard/rules/`. Name it after what it checks.

```
arch_guard/rules/required_tags.py
```

One file per logical concern. If you have two related checks (e.g. checking
tags on tables AND on pipelines), put them in the same file.

---

## 2. Write the rule class

```python
from arch_guard.findings import Finding
from arch_guard.rules._base import FileContext, Rule, register


@register
class RequiredTagsRule(Rule):
    """Every @dlt.table must declare owner and cost_center in table_properties."""

    rule_id = "governance.missing_tag"   # dotted, lowercase, noun phrase
    applies_to = ["dlt_python"]          # see applies_to values below

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

### `applies_to` values

| Value | When it runs | What's in ctx |
|---|---|---|
| `"dlt_python"` | `.py` files containing `@dlt.table` or `@dlt.view` | `ctx.tables` populated |
| `"raw_python"` | `.py` files with no DLT decorators | `ctx.tables` is `[]` |
| `"dab_yaml"` | `databricks.yml` / `databricks.yaml` | `ctx.raw_config` populated |

A rule can declare multiple values: `applies_to = ["dlt_python", "raw_python"]`.

### `rule_id` convention

`<domain>.<specific_violation>` — lowercase, dots as separators.

Good: `catalog.unsanctioned`, `naming.table`, `governance.missing_tag`  
Bad: `CatalogRule`, `check-naming`, `violation`

### `Finding` fields

| Field | Type | Notes |
|---|---|---|
| `rule_id` | str | Use `self.rule_id` |
| `message` | str | Plain English. Name the offending value. |
| `file` | str | Use `ctx.file` |
| `line` | int | `t.line` for table-level, `src.call_line` for read calls |
| `severity` | str | `"error"` or `"warning"` — drive from the contract, not hardcoded |

Always drive `severity` from the contract:
```python
sev = ctx.contract.get("naming", {}).get("tables", {}).get("severity", "warning")
```

This lets ops teams change severity without touching rule code.

---

## 3. Register it

Add an import to `arch_guard/rules/__init__.py`:

```python
from arch_guard.rules import catalog, naming, medallion, dab_config, required_tags  # noqa
```

That is the only change outside your new file. `check.py` picks it up automatically.

---

## 4. Write the tests

Create `tests/test_required_tags.py`:

```python
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

    def test_no_required_tags_in_contract_skipped(self):
        # Rule is configured by the contract — absent section = silent
        self.assertEqual(self._check("""
            import dlt
            @dlt.table(name="raw_orders", schema="bronze")
            def raw_orders():
                pass
        """, contract=contract_with(required_tags={})), [])

    def test_severity_driven_by_contract(self):
        # Test that changing severity in contract changes Finding.severity
        ...
```

### Minimum test cases for every rule

1. **Happy path** — compliant input produces zero findings
2. **Violation fires** — the specific bad input produces exactly the expected finding
3. **Contract section absent** — rule doesn't crash when its config key is missing
4. **Severity is contract-driven** — changing severity in the contract changes the finding

---

## 5. Run the suite

```bash
cd arch-guard
PYTHONPATH=. python3 -m unittest tests.test_required_tags -v
PYTHONPATH=. python3 -m unittest tests.test_catalog tests.test_naming tests.test_medallion tests.test_required_tags -v
```

---

## What `ctx` contains — quick reference

```python
ctx.file           # "pipelines/ingest.py"
ctx.contract       # full arch-contract.yaml as a dict
ctx.tables         # [TableDef, ...]  (dlt_python only)
ctx.raw_config     # {"bundle": ..., "resources": ...}  (dab_yaml only)
```

### `TableDef` fields (in `ctx.tables`)

```python
t.func_name          # Python function name
t.logical_name       # name= kwarg if set, else func_name
t.line               # line number of the @dlt.table decorator
t.is_view            # True if @dlt.view
t.decorator_catalog  # catalog= kwarg value, or None
t.decorator_schema   # schema= kwarg value, or None
t.table_properties   # dict from table_properties= kwarg
t.inferred_tier      # "bronze" | "silver" | "gold" | None
t.sources            # [SourceRef, ...]
```

### `SourceRef` fields (in `t.sources`)

```python
src.table_ref    # the string passed to dlt.read() / dlt.read_stream()
src.call_line    # line number of the read call
src.streaming    # True if dlt.read_stream()
```
