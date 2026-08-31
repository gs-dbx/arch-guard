"""FM API reviewer — calls a Databricks Foundation Model endpoint and returns
structured Finding objects for anti-patterns the deterministic rules cannot catch.

Activated only when FM_ENDPOINT is set in the environment. Degrades silently
(logs, returns []) on any failure — FM findings are advisory, never the reason
a check crashes or hard-blocks.

FM findings are capped at severity "warning". The LLM never owns error-level
findings; deterministic rules do.
"""
import json
import os
import subprocess
import urllib.request
from pathlib import Path

import jsonschema

from arch_guard.findings import Finding

# ---------------------------------------------------------------------------
# Output schema — every FM response is validated against this before use.
# A response that doesn't match is discarded, not passed as findings.
# ---------------------------------------------------------------------------

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


def _get_token():
    """Get a Databricks auth token from the CLI (already configured in the workflow)."""
    token = os.environ.get("DATABRICKS_TOKEN")
    if token:
        return token
    result = subprocess.run(
        ["databricks", "auth", "token"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode == 0:
        return result.stdout.decode().strip()
    return None


def _build_system_prompt(contract):
    template = _PROMPT_PATH.read_text()
    # Inline the relevant contract sections so the model knows the actual rules
    tiering = contract.get("tiering", {})
    tiers_summary = "; ".join(
        "{} reads from {}".format(k, v.get("may_read_from", []))
        for k, v in tiering.items()
    )
    catalogs = [c["name"] for c in contract.get("sanctioned_catalogs", [])]
    summary = "Sanctioned catalogs: {}. Medallion flow: {}.".format(
        catalogs, tiers_summary)
    return template.replace("{contract_summary}", summary)


def _build_user_message(diff_text, existing_findings):
    parts = ["## Changed files (git diff)\n\n```diff\n{}\n```".format(diff_text)]
    if existing_findings:
        parts.append("## Deterministic findings already raised (do not repeat these)\n")
        for f in existing_findings:
            parts.append("- [{}] {} — {}:{}".format(
                f.severity, f.rule_id, f.file, f.line))
    parts.append("\nReview the diff and return your findings as JSON.")
    return "\n\n".join(parts)


def _call_fm_api(system_prompt, user_message):
    host = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
    endpoint = os.environ.get("FM_ENDPOINT", "")
    if not host or not endpoint:
        return None

    token = _get_token()
    if not token:
        print("arch-guard [fm]: no auth token available — skipping FM review.")
        return None

    url = "{}/serving-endpoints/{}/invocations".format(host, endpoint)
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0,
        "max_tokens": 2048,
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": "Bearer {}".format(token),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print("arch-guard [fm]: API call failed — {}".format(e))
        return None


def _extract_json_from_response(api_response):
    """Pull the assistant message text out of the API response envelope."""
    try:
        return api_response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def _parse_and_validate(raw_text):
    """Parse JSON from the model response, validate schema, return findings list."""
    if not raw_text:
        return []
    # Strip markdown code fences if the model wrapped its output
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            l for l in lines
            if not l.startswith("```")
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


def fm_review(diff_text, contract, existing_findings=None):
    """Call the FM API and return Finding objects for anti-pattern findings.

    Returns an empty list on any error — FM findings are advisory only.
    """
    if not os.environ.get("FM_ENDPOINT"):
        return []

    existing_findings = existing_findings or []
    system_prompt = _build_system_prompt(contract)
    user_message = _build_user_message(diff_text, existing_findings)

    print("arch-guard [fm]: calling {} ...".format(os.environ.get("FM_ENDPOINT")))
    api_response = _call_fm_api(system_prompt, user_message)
    if not api_response:
        return []

    raw_text = _extract_json_from_response(api_response)
    raw_findings = _parse_and_validate(raw_text)

    findings = []
    for rf in raw_findings:
        # Enforce severity cap — FM findings are never errors
        sev = rf.get("severity", "warning")
        if sev not in ("warning", "note"):
            sev = "warning"
        msg = rf["message"]
        if rf.get("rationale"):
            msg = "{} ({})".format(msg, rf["rationale"])
        findings.append(Finding(
            rule_id=rf["rule_id"],
            message=msg,
            file=rf["file"],
            line=rf["line"],
            severity=sev,
        ))

    print("arch-guard [fm]: {} finding(s) from FM review.".format(len(findings)))
    return findings
