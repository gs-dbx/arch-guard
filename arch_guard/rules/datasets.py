"""Rules for customer-approved dataset schemas and dataset identity tags."""
import re

from arch_guard.findings import Finding
from arch_guard.rules._base import Rule, register


def _catalog_domain(catalog, convention):
    prefix = convention.get("prefix")
    envs = convention.get("environments", [])
    layers = convention.get("domain_layers", {})
    suffixes = (layers.get("bronze_suffix"), layers.get("silver_suffix"))
    if not catalog or not prefix:
        return None
    for env in envs:
        for suffix in suffixes:
            if not suffix:
                continue
            match = re.match(r"^{}_{}_(.+)_{}$".format(
                re.escape(prefix), re.escape(env), re.escape(suffix)), catalog)
            if match:
                return match.group(1)
    return None


@register
class DatasetPolicyRule(Rule):
    rule_id = "governance.dataset"
    applies_to = ["dlt_python"]

    def check(self, ctx):
        config = ctx.contract.get("datasets")
        if not config:
            return []
        allowed = {item["name"]: item["domain"]
                   for item in config.get("allowed", [])}
        required_tags = config.get("required_tags", [])
        severity = config.get("severity", "warning")
        convention = ctx.contract.get("catalog_convention", {})
        findings = []

        for table in ctx.tables:
            dataset = table.decorator_schema
            if not dataset:
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message=(
                        "Table '{}' does not declare a dataset schema. Set schema='<approved_dataset>' "
                        "and table_properties.dataset_name to the same value. If this is a new dataset, "
                        "ask the platform admin to confirm its owning domain, add it under "
                        "datasets.allowed in arch-contract.yaml, and provision that schema in the "
                        "sanctioned stage/cleansed and required gold catalogs."
                    ).format(table.logical_name),
                    file=ctx.file, line=table.line, severity=severity,
                ))
                continue
            if dataset not in allowed:
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message=(
                        "Dataset schema '{}' is not approved. Correct schema= if it is a typo; otherwise "
                        "ask the platform admin to confirm the owning domain, add name='{}' and that "
                        "domain under datasets.allowed in arch-contract.yaml, sanction/provision the "
                        "corresponding csb_<env>_<domain>_stage and _cleansed catalogs and schema, then "
                        "set dataset_name='{}'."
                    ).format(dataset, dataset, dataset),
                    file=ctx.file, line=table.line, severity=severity,
                ))
                continue

            if "dataset_name" in required_tags:
                tag = table.table_properties.get("dataset_name")
                if tag is None:
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        message=(
                            "Table '{}' is missing required dataset tag 'dataset_name'. Add "
                            "table_properties={{'dataset_name': '{}'}}; if '{}' is not approved, ask "
                            "the platform admin to add it to datasets.allowed and provision its schema."
                        ).format(table.logical_name, dataset, dataset),
                        file=ctx.file, line=table.line, severity=severity,
                    ))
                elif tag != dataset:
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        message=(
                            "Table '{}' has dataset_name='{}', but schema='{}'. Make both values match. "
                            "If '{}' is the intended new dataset, ask the platform admin to approve it "
                            "under datasets.allowed before changing the schema."
                        ).format(table.logical_name, tag, dataset, tag),
                        file=ctx.file, line=table.line, severity=severity,
                    ))

            catalog_domain = _catalog_domain(table.decorator_catalog, convention)
            if catalog_domain is not None and catalog_domain != allowed[dataset]:
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message=(
                        "Dataset '{}' is registered to domain '{}' but catalog '{}' encodes domain '{}'. "
                        "Move it to the sanctioned '{}' domain catalog, or ask the platform admin to "
                        "review and change the dataset's datasets.allowed domain before provisioning "
                        "and sanctioning a different catalog."
                    ).format(dataset, allowed[dataset], table.decorator_catalog,
                             catalog_domain, allowed[dataset]),
                    file=ctx.file, line=table.line, severity=severity,
                ))
        return findings
