# Import every rule module here so their @register decorators fire automatically.
# check.py never needs to change when a new rule is added — only this file does.
from arch_guard.rules import catalog, naming, medallion, dab_config  # noqa: F401
