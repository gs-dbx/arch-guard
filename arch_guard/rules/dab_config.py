"""Rules for Databricks Asset Bundle config (databricks.yml)."""
from arch_guard.findings import Finding
from arch_guard.rules._base import FileContext, Rule, register


@register
class DabSanctionedCatalogRule(Rule):
    """Pipeline targets in databricks.yml must use a sanctioned catalog."""
    rule_id = "catalog.unsanctioned"
    applies_to = ["dab_yaml"]

    def check(self, ctx):
        # type: (FileContext) -> list
        allowed = {c["name"] for c in ctx.contract.get("sanctioned_catalogs", [])}
        findings = []
        resources = ctx.raw_config.get("resources", {})
        for pipeline_name, pipeline in resources.get("pipelines", {}).items():
            catalog = pipeline.get("catalog")
            if catalog and catalog not in allowed:
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message=(
                        "Pipeline '{}' in databricks.yml targets catalog '{}', "
                        "which is not in the sanctioned set {}.".format(
                            pipeline_name, catalog, sorted(allowed))
                    ),
                    file=ctx.file,
                    line=1,
                    severity="error",
                ))
        return findings
