"""FM API reviewer — holistic per-file review via Databricks Foundation Model API.

Reviews the COMPLETE CURRENT CONTENT of each changed pipeline file rather than
the diff. This gives the LLM full context — surrounding functions, imports,
decorator arguments — that a fragment-based diff review misses.

One API call per file. Findings are tagged [LLM] in the message so they are
visually distinct from linter findings in the job summary.

Activated only when FM_ENDPOINT is set. Degrades silently on any failure —
FM findings are advisory (warning/note only), never the reason a check blocks.
"""
import json
import os
from pathlib import Path

import jsonschema

from arch_guard.findings import Finding

_FM_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["rule_id", "severity", "file", "line", "message"],
                "additionalProperties": False,
                "properties": {
                    "rule_id":   {"type": "string", "pattern": "^dlt\\.[a-z_]+\\.[a-z_]+$"},
                    "severity":  {"type": "string", "enum": ["warning", "note"]},
                    "file":      {"type": "string"},
                    "line":      {"type": "integer", "minimum": 1},
                    "message":   {"type": "string", "minLength": 10},
                    "rationale": {"type": "string"},
                },
            },
        }
    },
}

_PROMPT_PATH = Path(__file__).parent / "prompts" / "review_system.txt"

_REVIEWABLE_EXTENSIONS = (".py",)


def _build_system_prompt(contract, file_findings):
    """Build the system prompt for one file review."""
    template = _PROMPT_PATH.read_text()

    tiering = contract.get("tiering", {})
    tiers_summary = "; ".join(
        "{} reads from {}".format(k, v.get("may_read_from", []))
        for k, v in tiering.items()
    )
    catalogs = [c["name"] for c in contract.get("sanctioned_catalogs", [])]
    contract_summary = "Sanctioned catalogs: {}. Medallion flow: {}.".format(
        catalogs, tiers_summary)

    if file_findings:
        linter_lines = "\n".join(
            "  [LINTER][{}] {} line {}: {}".format(
                f.severity.upper(), f.rule_id, f.line, f.message)
            for f in file_findings
        )
    else:
        linter_lines = "  None."

    return (template
            .replace("{contract_summary}", contract_summary)
            .replace("{linter_findings}", linter_lines))


def _build_user_message(file_path, file_content):
    return (
        "## File: {}\n\n"
        "```python\n{}\n```\n\n"
        "Review this file and return your findings as JSON."
    ).format(file_path, file_content)


def _call_fm_api(system_prompt, user_message):
    model = os.environ.get("FM_ENDPOINT", "")
    if not model:
        return None
    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

        w = WorkspaceClient()
        response = w.serving_endpoints.query(
            name=model,
            messages=[
                ChatMessage(role=ChatMessageRole.SYSTEM, content=system_prompt),
                ChatMessage(role=ChatMessageRole.USER,   content=user_message),
            ],
            max_tokens=2048,
        )
        content = response.choices[0].message.content
        if isinstance(content, list):
            return {"choices": [{"message": {"content": "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )}}]}
        return {"choices": [{"message": {"content": content}}]}
    except Exception as e:
        print("arch-guard [fm]: API call failed — {}".format(e))
        return None


def _extract_text(api_response):
    try:
        return api_response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def _parse_and_validate(raw_text):
    if not raw_text:
        return []
    text = raw_text.strip()
    if text.startswith("```"):
        text = "\n".join(
            l for l in text.splitlines() if not l.startswith("```")
        ).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print("arch-guard [fm]: response is not valid JSON — {}".format(e))
        return []
    try:
        jsonschema.validate(data, _FM_OUTPUT_SCHEMA)
    except jsonschema.ValidationError as e:
        print("arch-guard [fm]: response failed schema validation — {}".format(e.message))
        return []
    return data.get("findings", [])


def fm_review(files, contract, det_findings=None):
    """Holistic per-file FM review.

    Args:
        files:        list of repo-relative file paths that changed
        contract:     loaded arch-contract.yaml dict
        det_findings: Finding objects from the deterministic pass (context only)

    Returns a list of Finding objects, severity capped at warning.
    """
    if not os.environ.get("FM_ENDPOINT"):
        return []

    det_findings = det_findings or []

    # Index linter findings by file so we can pass per-file context
    findings_by_file = {}
    for f in det_findings:
        findings_by_file.setdefault(f.file, []).append(f)

    all_fm_findings = []
    reviewable = [f for f in files
                  if Path(f).suffix in _REVIEWABLE_EXTENSIONS and Path(f).exists()]

    print("arch-guard [fm]: reviewing {} file(s) holistically...".format(len(reviewable)))

    for file_path in reviewable:
        try:
            content = Path(file_path).read_text()
        except Exception as e:
            print("arch-guard [fm]: could not read {} — {}".format(file_path, e))
            continue

        file_linter = findings_by_file.get(file_path, [])
        system_prompt = _build_system_prompt(contract, file_linter)
        user_message = _build_user_message(file_path, content)

        print("arch-guard [fm]: reviewing {} ({} linter findings as context)...".format(
            file_path, len(file_linter)))

        api_response = _call_fm_api(system_prompt, user_message)
        if not api_response:
            continue

        raw_findings = _parse_and_validate(_extract_text(api_response))

        for rf in raw_findings:
            sev = rf.get("severity", "warning")
            if sev not in ("warning", "note"):
                sev = "warning"
            msg = rf["message"]
            if rf.get("rationale"):
                msg = "{} ({})".format(msg, rf["rationale"])
            all_fm_findings.append(Finding(
                rule_id=rf["rule_id"],
                message=msg,
                file=rf.get("file", file_path),
                line=rf["line"],
                severity=sev,
            ))

    print("arch-guard [fm]: {} finding(s) from FM review.".format(len(all_fm_findings)))
    return all_fm_findings
