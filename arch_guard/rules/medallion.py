"""Rule: DLT pipelines must follow the permitted medallion-tier data flow."""
from arch_guard.contract import tier_read_allowed
from arch_guard.findings import Finding
from arch_guard.rules._base import FileContext, Rule, register


def _infer_source_tier(source_ref, all_tables):
    for t in all_tables:
        if t.logical_name == source_ref.table_ref:
            return t.inferred_tier
    for tier in ("bronze_", "silver_", "gold_"):
        if source_ref.table_ref.startswith(tier):
            return tier.rstrip("_")
    return None


@register
class MedallionFlowRule(Rule):
    """Each DLT table may only read from tiers permitted by the tiering graph."""
    rule_id = "medallion.illegal_read"
    applies_to = ["dlt_python"]

    def check(self, ctx):
        # type: (FileContext) -> list
        findings = []
        for t in ctx.tables:
            output_tier = t.inferred_tier
            if output_tier is None:
                continue
            for src in t.sources:
                src_tier = _infer_source_tier(src, ctx.tables)
                if src_tier is None:
                    continue
                if not tier_read_allowed(output_tier, src_tier, ctx.contract):
                    allowed = (ctx.contract.get("tiering", {})
                               .get(output_tier, {})
                               .get("may_read_from", []))
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        message=(
                            "'{}' (tier={}) reads from '{}' (tier={}), but {} "
                            "pipelines may only read from: {}.".format(
                                t.logical_name, output_tier,
                                src.table_ref, src_tier,
                                output_tier, allowed)
                        ),
                        file=ctx.file,
                        line=src.call_line,
                        severity="error",
                    ))
        return findings
