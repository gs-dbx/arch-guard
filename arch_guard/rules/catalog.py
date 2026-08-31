"""Rules: catalog references must be in the sanctioned set."""
import re

from arch_guard.contract import sanctioned_catalog_names
from arch_guard.findings import Finding
from arch_guard.rules._base import FileContext, Rule, register


@register
class SanctionedCatalogDltRule(Rule):
    """DLT tables must target a sanctioned catalog (decorator catalog= kwarg)."""
    rule_id = "catalog.unsanctioned"
    applies_to = ["dlt_python"]

    def check(self, ctx):
        # type: (FileContext) -> list
        allowed = sanctioned_catalog_names(ctx.contract)
        findings = []
        for t in ctx.tables:
            if t.decorator_catalog and t.decorator_catalog not in allowed:
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message=(
                        "Table '{}' targets catalog '{}', which is not in the "
                        "sanctioned set {}.".format(
                            t.logical_name, t.decorator_catalog, sorted(allowed))
                    ),
                    file=ctx.file,
                    line=t.line,
                    severity="error",
                ))
        return findings


# Three-part dotted references in non-DLT Python (spark.table, saveAsTable, etc.)
_THREE_PART_RE = re.compile(
    r"""["']([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)["']"""
)


@register
class SanctionedCatalogLiteralsRule(Rule):
    """Flag three-part catalog.schema.table string literals with unsanctioned catalogs.

    Backstop for non-DLT Python. Only fires on quoted string literals —
    parameterized names are not caught and require a targeted rule or manual review.
    """
    rule_id = "catalog.unsanctioned"
    applies_to = ["raw_python"]

    def check(self, ctx):
        # type: (FileContext) -> list
        allowed = sanctioned_catalog_names(ctx.contract)
        findings = []
        with open(ctx.file) as fh:
            src = fh.read()
        for m in _THREE_PART_RE.finditer(src):
            catalog = m.group(1)
            if catalog not in allowed:
                line = src[:m.start()].count("\n") + 1
                ref = "{}.{}.{}".format(m.group(1), m.group(2), m.group(3))
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message=(
                        "Catalog '{}' (in '{}') is not in the sanctioned set {}.".format(
                            catalog, ref, sorted(allowed))
                    ),
                    file=ctx.file,
                    line=line,
                    severity="error",
                ))
        return findings
