"""AST-based parser for Python DLT (Lakeflow Declarative Pipelines).

Extracts the logical data model from DLT-decorated Python files:
  - Each @dlt.table / @dlt.view function -> a TableDef (output asset)
  - dlt.read() / dlt.read_stream() calls inside those functions -> SourceRef

Rules never read source text directly; they consume TableDef objects.
"""
import ast
from typing import Dict, List, Optional


class SourceRef(object):
    """A single dlt.read / dlt.read_stream call."""
    def __init__(self, table_ref, call_line, streaming=False):
        self.table_ref = table_ref      # type: str
        self.call_line = call_line      # type: int
        self.streaming = streaming      # type: bool

    def __repr__(self):
        return "SourceRef({!r}, line={})".format(self.table_ref, self.call_line)


class TableDef(object):
    """One @dlt.table or @dlt.view decorated function."""
    def __init__(self, func_name, line, is_view=False,
                 decorator_name=None, decorator_schema=None,
                 decorator_catalog=None, table_properties=None):
        self.func_name = func_name                          # type: str
        self.line = line                                     # type: int
        self.is_view = is_view                              # type: bool
        self.decorator_name = decorator_name                # type: Optional[str]
        self.decorator_schema = decorator_schema            # type: Optional[str]
        self.decorator_catalog = decorator_catalog          # type: Optional[str]
        self.table_properties = table_properties or {}      # type: Dict
        self.sources = []                                   # type: List[SourceRef]

    @property
    def logical_name(self):
        return self.decorator_name or self.func_name

    @property
    def inferred_tier(self):
        """Infer medallion tier from the schema kwarg or table properties."""
        schema = self.decorator_schema or self.table_properties.get("schema")
        if schema in ("bronze", "silver", "gold"):
            return schema
        for tier in ("bronze_", "silver_", "gold_"):
            if self.logical_name.startswith(tier):
                return tier.rstrip("_")
        return None

    def __repr__(self):
        return "TableDef({!r}, tier={})".format(self.logical_name, self.inferred_tier)


class _DltVisitor(ast.NodeVisitor):
    def __init__(self):
        self.tables = []           # type: List[TableDef]
        self._current_table = None # type: Optional[TableDef]

    def _is_dlt_decorator(self, node):
        """Return (is_dlt_decorator, is_view). Handles @dlt.table, @dlt.view, and calls."""
        target = node.func if isinstance(node, ast.Call) else node
        if not isinstance(target, ast.Attribute):
            return False, False
        if not isinstance(target.value, ast.Name):
            return False, False
        if target.value.id != "dlt":
            return False, False
        return True, target.attr == "view"

    def _extract_decorator_kwargs(self, decorator):
        if not isinstance(decorator, ast.Call):
            return {}
        result = {}
        for kw in decorator.keywords:
            if isinstance(kw.value, ast.Str):
                result[kw.arg] = kw.value.s
            elif isinstance(kw.value, ast.Num):
                result[kw.arg] = kw.value.n
            elif isinstance(kw.value, ast.Dict):
                props = {}
                for k, v in zip(kw.value.keys, kw.value.values):
                    if isinstance(k, ast.Str) and isinstance(v, ast.Str):
                        props[k.s] = v.s
                result[kw.arg] = props
        return result

    def visit_FunctionDef(self, node):
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_func(node)

    def _visit_func(self, node):
        dlt_decorator = None
        is_view = False
        for dec in node.decorator_list:
            is_dlt, iv = self._is_dlt_decorator(dec)
            if is_dlt:
                dlt_decorator = dec
                is_view = iv
                break

        if dlt_decorator is None:
            self.generic_visit(node)
            return

        kwargs = self._extract_decorator_kwargs(dlt_decorator)
        tdef = TableDef(
            func_name=node.name,
            line=node.lineno,
            is_view=is_view,
            decorator_name=kwargs.get("name"),
            decorator_schema=kwargs.get("schema"),
            decorator_catalog=kwargs.get("catalog"),
            table_properties=kwargs.get("table_properties", {}),
        )

        prev = self._current_table
        self._current_table = tdef
        self.generic_visit(node)
        self._current_table = prev
        self.tables.append(tdef)

    def visit_Call(self, node):
        if self._current_table is not None:
            func = node.func
            if (isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "dlt"
                    and func.attr in ("read", "read_stream")):
                table_ref = None
                if node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Str):
                        table_ref = arg.s
                if table_ref is None:
                    for kw in node.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Str):
                            table_ref = kw.value.s
                if table_ref:
                    self._current_table.sources.append(SourceRef(
                        table_ref=table_ref,
                        call_line=node.lineno,
                        streaming=func.attr == "read_stream",
                    ))
        self.generic_visit(node)


def parse_dlt_file(path):
    """Parse a Python DLT file and return its table/view definitions."""
    with open(str(path)) as fh:
        source = fh.read()
    tree = ast.parse(source, filename=str(path))
    visitor = _DltVisitor()
    visitor.visit(tree)
    return visitor.tables
