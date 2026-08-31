"""Rules for non-DLT Python files — regular Spark jobs and notebooks.

These rules consume SparkOperation objects from parsers/spark_python.py.
They apply to any .py file that does NOT contain @dlt.table decorators.
"""
import re

from arch_guard.contract import sanctioned_catalog_names
from arch_guard.findings import Finding
from arch_guard.rules._base import FileContext, Rule, register


@register
class SparkSanctionedCatalogRule(Rule):
    """Spark table reads and writes must reference a sanctioned catalog."""
    rule_id = "catalog.unsanctioned"
    applies_to = ["raw_python", "sql"]

    def check(self, ctx):
        # type: (FileContext) -> list
        allowed = sanctioned_catalog_names(ctx.contract)
        findings = []
        for op in ctx.spark_ops:
            if op.catalog and op.catalog not in allowed:
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message=(
                        "Spark {} references catalog '{}' which is not in the "
                        "sanctioned set {}. Full reference: '{}'.".format(
                            op.op_type, op.catalog, sorted(allowed), op.table_ref)
                    ),
                    file=ctx.file,
                    line=op.line,
                    severity="error",
                ))
        return findings


@register
class SparkTableNamingRule(Rule):
    """Tables written via saveAsTable / writeTo must follow the naming convention."""
    rule_id = "naming.table"
    applies_to = ["raw_python"]

    def check(self, ctx):
        # type: (FileContext) -> list
        rule_cfg = ctx.contract.get("naming", {}).get("tables")
        if not rule_cfg:
            return []
        pat = re.compile(rule_cfg["pattern"])
        sev = rule_cfg.get("severity", "warning")
        findings = []
        for op in ctx.spark_ops:
            if op.op_type == "write" and not pat.match(op.table_name):
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message=(
                        "Table name '{}' does not match required pattern `{}`. "
                        "Full reference: '{}'.".format(
                            op.table_name, pat.pattern, op.table_ref)
                    ),
                    file=ctx.file,
                    line=op.line,
                    severity=sev,
                ))
        return findings
