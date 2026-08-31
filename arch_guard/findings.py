"""Finding class and output formatters (SARIF, job summary)."""
import json
from typing import List


class Finding(object):
    def __init__(self, rule_id, message, file, line=1, severity="warning"):
        self.rule_id = rule_id      # type: str
        self.message = message      # type: str
        self.file = file            # type: str
        self.line = line            # type: int
        self.severity = severity    # type: str  error|warning|note

    def __eq__(self, other):
        return isinstance(other, Finding) and self.__dict__ == other.__dict__

    def __repr__(self):
        return "[{}] {}: {} ({}:{})".format(
            self.severity, self.rule_id, self.message, self.file, self.line)


# ---------------------------------------------------------------------------
# SARIF
# ---------------------------------------------------------------------------

def to_sarif(findings):
    # type: (List[Finding]) -> dict
    _lvl = {"error": "error", "warning": "warning", "note": "note"}
    rule_ids = sorted({f.rule_id for f in findings})
    rules = [{"id": rid, "name": rid} for rid in rule_ids]
    results = [
        {
            "ruleId": f.rule_id,
            "level": _lvl.get(f.severity, "warning"),
            "message": {"text": f.message},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": f.file, "uriBaseId": "%SRCROOT%"},
                "region": {"startLine": f.line},
            }}],
        }
        for f in findings
    ]
    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{
            "tool": {"driver": {
                "name": "arch-guard",
                "informationUri": "https://github.com/your-org/arch-guard",
                "rules": rules,
            }},
            "results": results,
        }],
    }


# ---------------------------------------------------------------------------
# GitHub Actions job summary (Markdown)
# ---------------------------------------------------------------------------

_SEV_ICON = {"error": ":red_circle:", "warning": ":yellow_circle:", "note": ":white_circle:"}


def write_summary(findings, fh, advisory=True, waived=None):
    # type: (list, object, bool, list) -> None
    waived = waived or []
    posture = "advisory (non-blocking)" if advisory else "enforcing (blocking on errors)"
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")

    fh.write("## arch-guard — {} finding(s)\n\n".format(len(findings)))
    fh.write("**Posture:** {}  \n".format(posture))
    fh.write("**Errors:** {} &nbsp; **Warnings:** {} &nbsp; **Waived:** {}\n\n".format(
        errors, warnings, len(waived)))

    if not findings and not waived:
        fh.write(":white_check_mark: No findings — all checked files conform to the contract.\n")
        return

    if findings:
        fh.write("| | Severity | Rule | File:Line | Message |\n")
        fh.write("|---|---|---|---|---|\n")
        for f in sorted(findings, key=lambda x: (x.severity != "error", x.file, x.line)):
            icon = _SEV_ICON.get(f.severity, "")
            fh.write("| {} | {} | `{}` | `{}:{}` | {} |\n".format(
                icon, f.severity, f.rule_id, f.file, f.line, f.message))
        fh.write("\n")

    if waived:
        fh.write("<details><summary>:white_check_mark: {} waived finding(s)</summary>\n\n".format(
            len(waived)))
        fh.write("| Rule | File:Line | Reason |\n|---|---|---|\n")
        for f, w in waived:
            reason = w.get("reason", "no reason given")
            expires = " (expires {})".format(w["expires"]) if w.get("expires") else ""
            fh.write("| `{}` | `{}:{}` | {}{} |\n".format(
                f.rule_id, f.file, f.line, reason, expires))
        fh.write("\n</details>\n\n")

    if advisory:
        fh.write("> **Advisory mode:** findings are informational only.\n")
