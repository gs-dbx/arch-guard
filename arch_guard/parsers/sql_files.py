"""Best-effort parser for SQL files.

Extracts three-part catalog.schema.table references using regex.
Returns SparkOperation objects so SQL rules share the same interface as
Spark Python rules.
"""
import re

from arch_guard.parsers.spark_python import SparkOperation

# Matches three-part identifiers (catalog.schema.table), case-insensitive.
_THREE_PART_RE = re.compile(
    r'\b([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\b',
    re.IGNORECASE,
)

# Keywords that signal a write target immediately before the reference
_WRITE_KEYWORDS = re.compile(
    r'\b(INSERT\s+INTO|CREATE\s+(OR\s+REPLACE\s+)?(STREAMING\s+)?'
    r'(LIVE\s+)?(TABLE|VIEW)|MERGE\s+INTO)\s*$',
    re.IGNORECASE,
)


def parse_sql_file(path):
    """Extract SparkOperation objects from a SQL file."""
    with open(str(path)) as fh:
        source = fh.read()

    lines = source.splitlines()
    ops = []
    for lineno, line in enumerate(lines, 1):
        for m in _THREE_PART_RE.finditer(line):
            ref = "{}.{}.{}".format(m.group(1), m.group(2), m.group(3))
            preceding = line[:m.start()]
            op_type = "write" if _WRITE_KEYWORDS.search(preceding) else "read"
            ops.append(SparkOperation(op_type, ref.lower(), lineno))

    return ops
