"""Rules for Databricks Asset Bundle config (databricks.yml).

Covers both pipeline resources and job resources.
"""
from arch_guard.findings import Finding
from arch_guard.rules._base import FileContext, Rule, register


@register
class DabSanctionedCatalogRule(Rule):
    """Pipeline and job targets in databricks.yml must use a sanctioned catalog."""
    rule_id = "catalog.unsanctioned"
    applies_to = ["dab_yaml"]

    def check(self, ctx):
        # type: (FileContext) -> list
        allowed = {c["name"] for c in ctx.contract.get("sanctioned_catalogs", [])}
        findings = []
        resources = ctx.raw_config.get("resources", {})

        # Check pipelines
        for name, pipeline in resources.get("pipelines", {}).items():
            catalog = pipeline.get("catalog")
            if catalog and catalog not in allowed:
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message=(
                        "Pipeline '{}' targets catalog '{}', "
                        "which is not in the sanctioned set {}.".format(
                            name, catalog, sorted(allowed))
                    ),
                    file=ctx.file,
                    line=1,
                    severity="error",
                ))

        # Check jobs — look for catalog in cluster spark_conf and task configs
        for job_name, job in resources.get("jobs", {}).items():
            for task in job.get("tasks", []):
                # spark_python_task and python_wheel_task can set catalog via
                # spark_conf or environment variables; check named_parameters too
                for param_key, param_val in task.get("named_parameters", {}).items():
                    if "catalog" in param_key.lower() and isinstance(param_val, str):
                        if param_val not in allowed:
                            findings.append(Finding(
                                rule_id=self.rule_id,
                                message=(
                                    "Job '{}' task '{}' passes catalog '{}' "
                                    "which is not in the sanctioned set {}.".format(
                                        job_name,
                                        task.get("task_key", "unknown"),
                                        param_val,
                                        sorted(allowed))
                                ),
                                file=ctx.file,
                                line=1,
                                severity="error",
                            ))

        return findings


@register
class DabPipelineNamingRule(Rule):
    """Pipeline resource names in databricks.yml must follow the naming convention."""
    rule_id = "naming.pipelines"
    applies_to = ["dab_yaml"]

    def check(self, ctx):
        # type: (FileContext) -> list
        import re
        rule_cfg = ctx.contract.get("naming", {}).get("pipelines")
        if not rule_cfg:
            return []
        pat = re.compile(rule_cfg["pattern"])
        sev = rule_cfg.get("severity", "warning")
        findings = []
        resources = ctx.raw_config.get("resources", {})
        for pipeline_name, pipeline in resources.get("pipelines", {}).items():
            # Check the display name if set, else the resource key
            name = pipeline.get("name", pipeline_name)
            if not pat.match(name):
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message=(
                        "Pipeline name '{}' does not match required pattern `{}`.".format(
                            name, pat.pattern)
                    ),
                    file=ctx.file,
                    line=1,
                    severity=sev,
                ))
        return findings


@register
class DabJobNamingRule(Rule):
    """Job resource names in databricks.yml must follow the naming convention."""
    rule_id = "naming.jobs"
    applies_to = ["dab_yaml"]

    def check(self, ctx):
        # type: (FileContext) -> list
        import re
        rule_cfg = ctx.contract.get("naming", {}).get("jobs")
        if not rule_cfg:
            return []
        pat = re.compile(rule_cfg["pattern"])
        sev = rule_cfg.get("severity", "warning")
        findings = []
        resources = ctx.raw_config.get("resources", {})
        for job_name, job in resources.get("jobs", {}).items():
            name = job.get("name", job_name)
            if not pat.match(name):
                findings.append(Finding(
                    rule_id=self.rule_id,
                    message=(
                        "Job name '{}' does not match required pattern `{}`.".format(
                            name, pat.pattern)
                    ),
                    file=ctx.file,
                    line=1,
                    severity=sev,
                ))
        return findings
