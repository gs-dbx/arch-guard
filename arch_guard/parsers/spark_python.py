"""AST-based parser for non-DLT Python files (regular Spark jobs and notebooks).

Detects Spark read and write operations that reference catalog tables:
  - spark.table("cat.schema.tbl")
  - spark.read.table("cat.schema.tbl")
  - df.write.saveAsTable("cat.schema.tbl")
  - df.writeTo("cat.schema.tbl")
  - spark.sql("SELECT ... FROM cat.schema.tbl")  (best-effort SQL extraction)

Rules consume SparkOperation objects from this parser, not raw source text.
"""
import ast
import re


class SparkOperation(object):
    """One Spark table read or write in a non-DLT Python file."""
    def __init__(self, op_type, table_ref, line):
        self.op_type = op_type      # "read" | "write"
        self.table_ref = table_ref  # the string passed to the call
        self.line = line

    def __repr__(self):
        return "SparkOp({}, {!r}, line={})".format(self.op_type, self.table_ref, self.line)

    @property
    def catalog(self):
        """Return catalog portion of a three-part reference, or None."""
        parts = self.table_ref.split(".")
        return parts[0] if len(parts) == 3 else None

    @property
    def table_name(self):
        """Return the bare table name (last part of the reference)."""
        return self.table_ref.split(".")[-1]


# Methods that indicate a read operation
_READ_METHODS  = {"table"}           # spark.table() / spark.read.table()
# Methods that indicate a write operation
_WRITE_METHODS = {"saveAsTable", "writeTo"}

# Simple regex to pull three-part references out of SQL strings
_SQL_TABLE_RE = re.compile(
    r'\b([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\b',
    re.IGNORECASE,
)


class _SparkVisitor(ast.NodeVisitor):
    def __init__(self):
        self.operations = []

    def _str_value(self, node):
        """Extract a string constant from an AST node (Str or Constant)."""
        if isinstance(node, ast.Str):
            return node.s
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    def visit_Call(self, node):
        func = node.func
        if not isinstance(func, ast.Attribute):
            self.generic_visit(node)
            return

        method = func.attr

        # spark.table("x") or spark.read.table("x")
        if method in _READ_METHODS and node.args:
            ref = self._str_value(node.args[0])
            if ref:
                self.operations.append(SparkOperation("read", ref, node.lineno))

        # df.write.saveAsTable("x") or df.writeTo("x")
        elif method in _WRITE_METHODS and node.args:
            ref = self._str_value(node.args[0])
            if ref:
                self.operations.append(SparkOperation("write", ref, node.lineno))

        # spark.sql("SELECT ... FROM cat.schema.tbl ...")
        elif method == "sql" and node.args:
            sql_text = self._str_value(node.args[0])
            if sql_text:
                for m in _SQL_TABLE_RE.finditer(sql_text):
                    ref = "{}.{}.{}".format(m.group(1), m.group(2), m.group(3))
                    # Heuristic: if the reference is after FROM or JOIN it's a read;
                    # if after INSERT INTO / CREATE TABLE it's a write.
                    preceding = sql_text[:m.start()].upper().rstrip()
                    op = "write" if preceding.endswith(("INTO", "TABLE")) else "read"
                    self.operations.append(SparkOperation(op, ref, node.lineno))

        self.generic_visit(node)


def parse_spark_file(path):
    """Parse a non-DLT Python file and return SparkOperation objects."""
    with open(str(path)) as fh:
        source = fh.read()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    visitor = _SparkVisitor()
    visitor.visit(tree)
    return visitor.operations
