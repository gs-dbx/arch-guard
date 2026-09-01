"""FM API reviewer — calls a Databricks Foundation Model endpoint and returns
structured Finding objects for anti-patterns the deterministic rules cannot catch.

Activated only when FM_ENDPOINT is set in the environment. Degrades silently
(logs, returns []) on any failure — FM findings are advisory, never the reason
a check crashes or hard-blocks.

Auth is handled entirely by the Databricks SDK via DATABRICKS_AUTH_TYPE:
  - github-oidc        : GitHub OIDC WIF — no stored secrets (recommended)
  - client-credentials : M2M OAuth with DATABRICKS_CLIENT_ID + CLIENT_SECRET
  - pat                : personal access token via DATABRICKS_TOKEN

FM findings are capped at severity "warning". The LLM never owns error-level
findings; deterministic rules do.
"""
import json
import os
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


def _build_system_prompt(contract, existing_findings):
    template = _PROMPT_PATH.read_text()

    tiering = contract.get("tiering", {})
    tiers_summary = "; ".join(
        "{} reads from {}".format(k, v.get("may_read_from", []))
        for k, v in tiering.items()
    )
    catalogs = [c["name"] for c in contract.get("sanctioned_catalogs", [])]
    contract_summary = "Sanctioned catalogs: {}. Medallion flow: {}.".format(
        catalogs, tiers_summary)

    if existing_findings:
        linter_lines = "\n".join(
            "- [LINTER][{}] {} — {}:{}  {}".format(
                f.severity.upper(), f.rule_id, f.file, f.line, f.message)
            for f in existing_findings
        )
    else:
        linter_lines = "No linter findings for this diff."

    return (template
            .replace("{contract_summary}", contract_summary)
            .replace("{linter_findings}", linter_lines))


def _build_user_message(diff_text):
    return (
        "## Changed files (git diff)\n\n"
        "```diff\n{}\n```\n\n"
        "Review the diff and return your findings as JSON."
    ).format(diff_text)


def _call_fm_api(system_prompt, user_message):
    """Call the FM endpoint via the Databricks SDK serving_endpoints.query().

    Uses the SDK directly — no databricks-openai package needed.
    Auth is fully delegated to the SDK via DATABRICKS_AUTH_TYPE + credentials.
    """
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
        return {"choices": [{"message": {"content": content}}]}
    except Exception as e:
        print("arch-guard [fm]: API call failed — {}".format(e))
        return None


def _extract_json_from_response(api_response):
    try:
        content = api_response["choices"][0]["message"]["content"]
        # SDK may return content as a list of blocks (Claude format) or a plain string
        if isinstance(content, list):
            return "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return content
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
    system_prompt = _build_system_prompt(contract, existing_findings)
    user_message = _build_user_message(diff_text)

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
