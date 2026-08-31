"""arch-guard: contract-conformance checker for Databricks pipelines.

Pipeline:
  1. Validate arch-contract.yaml against JSON Schema (hard failure if broken).
  2. Collect changed files from the git diff.
  3. If arch-contract.yaml changed, re-scan ALL tracked pipeline files.
  4. Run deterministic rules for each file via the registry.
  5. Run FM API reviewer if FM_ENDPOINT is set (v2, advisory only).
  6. Apply waivers from .arch-waivers.yaml.
  7. Emit SARIF + job summary. Advisory mode always exits 0.

To add a new rule: see docs/writing-rules.md. This file does not need to change.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

from arch_guard.contract import load_and_validate
from arch_guard.findings import Finding, to_sarif, write_summary
from arch_guard.fm_review import fm_review
from arch_guard.parsers.dlt_python import parse_dlt_file
from arch_guard.waivers import apply_waivers, load_waivers
import arch_guard.rules  # noqa: F401 — triggers all @register decorators
from arch_guard.rules._base import FileContext, rules_for

_TRACKED_EXTENSIONS = (".py", ".sql", ".yml", ".yaml")
_CONTRACT_FILE = "arch-contract.yaml"


def changed_files(base, head):
    result = subprocess.run(
        ["git", "diff", "--name-only", "{}..{}".format(base, head)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return [f for f in result.stdout.decode().splitlines()
            if f.endswith(_TRACKED_EXTENSIONS)]


def all_tracked_files():
    result = subprocess.run(
        ["git", "ls-files"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return [f for f in result.stdout.decode().splitlines()
            if f.endswith(_TRACKED_EXTENSIONS)]


def get_diff_text(base, head):
    """Get the full unified diff for FM review context."""
    result = subprocess.run(
        ["git", "diff", "{}..{}".format(base, head)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.stdout.decode() if result.returncode == 0 else ""


def check_file(file, contract):
    # type: (str, dict) -> list
    p = Path(file)
    if not p.exists():
        return []

    if p.suffix == ".py":
        try:
            tables = parse_dlt_file(file)
        except SyntaxError as e:
            return [Finding("parse.syntax_error",
                            "Python syntax error: {}".format(e),
                            file, e.lineno or 1, "error")]
        file_type = "dlt_python" if tables else "raw_python"
        ctx = FileContext(file=file, contract=contract, tables=tables)
        findings = []
        for rule in rules_for(file_type):
            findings += rule.check(ctx)
        return findings

    if p.name in ("databricks.yml", "databricks.yaml"):
        try:
            config = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError as e:
            return [Finding("dab.parse_error",
                            "YAML parse error: {}".format(e),
                            file, 1, "error")]
        ctx = FileContext(file=file, contract=contract, raw_config=config)
        findings = []
        for rule in rules_for("dab_yaml"):
            findings += rule.check(ctx)
        return findings

    return []


def main():
    parser = argparse.ArgumentParser(description="arch-guard contract conformance checker")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--schema")
    parser.add_argument("--diff-base", required=True)
    parser.add_argument("--diff-head", required=True)
    parser.add_argument("--sarif-out", required=True)
    parser.add_argument("--summary-out")
    parser.add_argument("--waivers", default=".arch-waivers.yaml")
    parser.add_argument("--advisory", action="store_true")
    args = parser.parse_args()

    try:
        contract = load_and_validate(args.contract, args.schema)
    except Exception as e:
        print("arch-guard: FATAL — contract validation failed: {}".format(e),
              file=sys.stderr)
        sys.exit(2)

    files = changed_files(args.diff_base, args.diff_head)

    if _CONTRACT_FILE in files:
        print("arch-guard: {} changed — re-evaluating all tracked files.".format(
            _CONTRACT_FILE))
        files = all_tracked_files()
    else:
        files = [f for f in files if f != _CONTRACT_FILE]

    # Deterministic rules
    det_findings = []
    for f in files:
        det_findings += check_file(f, contract)

    # FM reviewer (v2) — only runs when FM_ENDPOINT is set
    diff_text = get_diff_text(args.diff_base, args.diff_head)
    fm_findings = fm_review(diff_text, contract, det_findings)

    all_findings = det_findings + fm_findings

    # Waiver pass — split into active vs acknowledged
    waivers = load_waivers(args.waivers)
    active_findings, waived = apply_waivers(all_findings, waivers)

    # Output
    Path(args.sarif_out).write_text(
        json.dumps(to_sarif(active_findings), indent=2))
    if args.summary_out:
        with open(args.summary_out, "a") as fh:
            write_summary(active_findings, fh,
                          advisory=args.advisory, waived=waived)

    errors = [f for f in active_findings if f.severity == "error"]
    print("arch-guard: {} active finding(s) ({} errors) · {} waived.".format(
        len(active_findings), len(errors), len(waived)))
    for f in active_findings:
        print("  {}".format(f))
    for f, w in waived:
        print("  [waived] {} — {}".format(f, w.get("reason", "")))

    sys.exit(0 if args.advisory else (1 if errors else 0))


if __name__ == "__main__":
    main()
