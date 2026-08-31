"""Rules: DLT table names must conform to the naming contract."""
import re

from arch_guard.findings import Finding
from arch_guard.rules._base import FileContext, Rule, register


@register
class NamingTablesRule(Rule):
    """DLT table/view logical names must match the tables naming pattern."""
    rule_id = "naming.table"
    applies_to = ["dlt_python"]

    def check(self, ctx):
        # type: (FileContext) -> list
        rule_cfg = ctx.contract.get("naming", {}).get("tables")
        if not rule_cfg:
            return []
        pat = re.compile(rule_cfg["pattern"])
        sev = rule_cfg.get("severity", "warning")
        findings = []
        for t in ctx.tables:
            name = t.logical_name
            if not pat.match(name):
                kind = "View" if t.is_view else "Table"
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message="{} name '{}' does not match required pattern `{}`.".format(
                        kind, name, pat.pattern),
                    file=ctx.file,
                    line=t.line,
                    severity=sev,
                ))
        return findings


@register
class NamingBronzePrefixRule(Rule):
    """Bronze-tier tables should carry the required name prefix (e.g. 'raw_')."""
    rule_id = "naming.bronze_prefix"
    applies_to = ["dlt_python"]

    def check(self, ctx):
        # type: (FileContext) -> list
        rule_cfg = ctx.contract.get("naming", {}).get("bronze_table_prefix")
        if not rule_cfg:
            return []
        pat = re.compile(rule_cfg["pattern"])
        sev = rule_cfg.get("severity", "warning")
        findings = []
        for t in ctx.tables:
            if t.inferred_tier == "bronze" and not pat.match(t.logical_name):
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message="Bronze table '{}' should start with prefix matching `{}`.".format(
                        t.logical_name, pat.pattern),
                    file=ctx.file,
                    line=t.line,
                    severity=sev,
                ))
        return findings
