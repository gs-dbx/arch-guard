"""Rule base class, FileContext, and auto-registration registry.

To add a new rule:
  1. Create arch_guard/rules/<your_rule>.py
  2. Subclass Rule, set rule_id and applies_to, implement check()
  3. Decorate with @register
  4. Import the module in arch_guard/rules/__init__.py

That is all. check.py never needs to change.

See docs/writing-rules.md for the full guide.
"""

_REGISTRY = []


class FileContext(object):
    """Everything a rule needs to check one file.

    Populated by check.py before calling rule.check(ctx).
    Rules must not open or parse files themselves.

    Attributes:
        file        Repo-relative path to the file being checked.
        contract    Loaded arch-contract.yaml as a Python dict.
        tables      List of TableDef objects (dlt_python files only; [] otherwise).
        raw_config  Parsed YAML dict (dab_yaml files only; {} otherwise).
    """
    def __init__(self, file, contract, tables=None, raw_config=None):
        self.file = file
        self.contract = contract
        self.tables = tables or []
        self.raw_config = raw_config or {}


class Rule(object):
    """Base class for all arch-guard rules.

    Subclass this, set rule_id and applies_to, implement check(ctx).
    Decorate with @register so the rule is discovered automatically.

    applies_to values:
        "dlt_python"  — .py files that contain @dlt.table / @dlt.view decorators.
                        ctx.tables is populated with parsed TableDef objects.
        "raw_python"  — .py files with no DLT decorators (Spark jobs, notebooks).
                        ctx.tables is empty; operate on ctx.file directly if needed.
        "dab_yaml"    — databricks.yml / databricks.yaml files.
                        ctx.raw_config is the parsed YAML dict.
    """
    rule_id = None      # type: str  dotted id, e.g. "catalog.unsanctioned"
    applies_to = []     # type: list[str]

    def check(self, ctx):
        # type: (FileContext) -> list
        raise NotImplementedError


def register(cls):
    """Class decorator: instantiates the rule and adds it to the registry.

    Usage:
        @register
        class MyRule(Rule):
            ...
    """
    _REGISTRY.append(cls())
    return cls


def rules_for(file_type):
    # type: (str) -> list
    """Return all registered rules that apply to the given file type."""
    return [r for r in _REGISTRY if file_type in r.applies_to]
