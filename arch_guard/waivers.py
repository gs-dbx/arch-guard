"""Waiver system — loads .arch-waivers.yaml and partitions findings into
active (must be fixed or will block) vs waived (acknowledged, suppressed).

A waiver must be its own reviewed PR. The waiver file is the audit trail.
"""
import sys
from datetime import date
from pathlib import Path

import yaml


def load_waivers(waiver_path=".arch-waivers.yaml"):
    """Load waiver entries from the repo. Returns [] if the file doesn't exist."""
    p = Path(waiver_path)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text()) or {}
    return data.get("waivers", [])


def _waiver_is_expired(waiver):
    expires = waiver.get("expires")
    if not expires:
        return False
    try:
        exp = date.fromisoformat(str(expires))
        return date.today() > exp
    except ValueError:
        return False


def apply_waivers(findings, waivers):
    """Split findings into (active, waived).

    A finding is waived when a waiver entry matches on both rule_id and file,
    and the waiver has not expired. Line is optional in the waiver — if absent,
    the waiver covers all instances of that rule in the file.

    Returns:
        active  list[Finding]             — findings that still require action
        waived  list[(Finding, waiver)]   — suppressed findings with their waiver
    """
    active = []
    waived = []
    for f in findings:
        match = None
        for w in waivers:
            if w.get("rule_id") != f.rule_id:
                continue
            if w.get("file") != f.file:
                continue
            if "line" in w and w["line"] != f.line:
                continue
            if _waiver_is_expired(w):
                print(
                    "arch-guard: waiver for {}/{} expired on {} — treating as active.".format(
                        f.rule_id, f.file, w.get("expires")),
                    file=sys.stderr,
                )
                continue
            match = w
            break
        if match:
            waived.append((f, match))
        else:
            active.append(f)
    return active, waived
