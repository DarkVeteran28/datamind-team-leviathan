"""Fail-closed validation for the narrowly scoped CUSTOMER query surface."""
import sqlglot
from sqlglot import exp

TABLE = "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER"
ALLOWED_COLUMNS = {"C_CUSTKEY", "C_NAME", "C_ACCTBAL", "C_MKTSEGMENT"}
MAX_ROWS = 100


class SQLValidationError(ValueError):
    """Validation rejection with evidence for checks actually attempted."""

    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = evidence


def _record_pass(checks, name, detail):
    checks.append({"name": name, "status": "passed", "detail": detail})


def _reject(checks, name, message):
    checks.append({"name": name, "status": "failed", "detail": message})
    raise SQLValidationError(message, {"status": "rejected", "checks": list(checks)})


def validate_sql_with_evidence(sql):
    """Return normalized SQL and evidence from the validator's actual checks."""
    checks = []
    if not isinstance(sql, str) or not sql.strip():
        _reject(checks, "sql_input", "SQL must be a non-empty string.")
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    if not sql or ";" in sql:
        _reject(checks, "single_statement", "Only one SQL statement is permitted.")
    try:
        statements = sqlglot.parse(sql, read="snowflake")
    except sqlglot.errors.ParseError as exc:
        _reject(checks, "sql_parse", "SQL could not be parsed safely.")
    if len(statements) != 1 or statements[0] is None:
        _reject(checks, "single_statement", "Only one SQL statement is permitted.")
    _record_pass(checks, "single_statement", "SQLGlot parsed exactly one statement.")

    tree = statements[0]
    if not isinstance(tree, exp.Select):
        _reject(checks, "read_only_select", "Only SELECT queries are allowed.")
    _record_pass(checks, "read_only_select", "Statement is a SELECT.")

    forbidden = (exp.Subquery, exp.Union, exp.Intersect, exp.Except, exp.Join,
                 exp.With, exp.Window, exp.Lateral, exp.Pivot, exp.Unnest)
    for kind in forbidden:
        if next(tree.find_all(kind), None) is not None:
            _reject(checks, "supported_constructs", f"Unsupported SQL structure: {kind.__name__}.")
    allowed_args = {"expressions", "from_", "where", "group", "having", "order", "limit", "offset", "distinct"}
    for arg_name, arg_value in tree.args.items():
        if arg_value is not None and arg_name not in allowed_args:
            _reject(checks, "supported_constructs", f"Unsupported SELECT clause: {arg_name}.")
    _record_pass(checks, "supported_constructs", "No unsupported structures or SELECT clauses were found.")

    tables = list(tree.find_all(exp.Table))
    if len(tables) != 1:
        _reject(checks, "approved_table", "Query must reference only the approved CUSTOMER table.")
    table = tables[0]
    if (table.name.upper() != "CUSTOMER" or (table.db and table.db.upper() != "TPCH_SF1")
            or (table.catalog and table.catalog.upper() != "SNOWFLAKE_SAMPLE_DATA")):
        _reject(checks, "approved_table", "Query references an unapproved table.")
    _record_pass(checks, "approved_table", f"Only {TABLE} is referenced.")

    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            _reject(checks, "approved_columns", "Wildcard selection is not allowed.")
    for column in tree.find_all(exp.Column):
        if column.name == "*":
            continue
        if column.name.upper() not in ALLOWED_COLUMNS:
            _reject(checks, "approved_columns", f"Unapproved column: {column.name}.")
        if column.table and column.table.upper() not in {table.alias_or_name.upper(), "CUSTOMER"}:
            _reject(checks, "approved_columns", f"Unapproved column qualifier: {column.table}.")
    _record_pass(checks, "approved_columns", "Referenced columns are within the configured allowlist.")

    aggregates = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
    for func in tree.find_all(exp.Func):
        if func.sql_name().upper() not in aggregates:
            _reject(checks, "approved_functions", f"Unsupported SQL function: {func.sql_name()}.")
    _record_pass(checks, "approved_functions", "Function calls are limited to approved aggregates.")

    placeholders = list(tree.find_all(exp.Placeholder))
    for placeholder in placeholders:
        parent = placeholder.parent
        if not (isinstance(parent, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE))
                and parent.expression is placeholder):
            _reject(checks, "parameter_binding", "Parameters are allowed only as scalar comparison values.")
    if placeholders:
        _record_pass(checks, "parameter_binding", "Scalar comparison values are represented by bind placeholders.")

    limit = tree.args.get("limit")
    requested_limit = None
    if limit is None:
        tree = tree.limit(MAX_ROWS)
    else:
        value = limit.expression
        if not isinstance(value, exp.Literal) or not value.is_int:
            _reject(checks, "row_limit", "LIMIT must be a positive integer literal.")
        requested_limit = int(value.this)
        if requested_limit < 1:
            _reject(checks, "row_limit", "LIMIT must be a positive integer literal.")
        if requested_limit > MAX_ROWS:
            tree = tree.limit(MAX_ROWS)
    if requested_limit is None:
        limit_detail = f"LIMIT {MAX_ROWS} was added."
    elif requested_limit > MAX_ROWS:
        limit_detail = f"Requested LIMIT {requested_limit} was capped at {MAX_ROWS}."
    else:
        limit_detail = f"LIMIT {requested_limit} is within the {MAX_ROWS}-row maximum."
    _record_pass(checks, "row_limit", limit_detail)

    return tree.sql(dialect="snowflake"), {"status": "passed", "checks": checks}


def validate_sql(sql):
    """Validate SQL and return its normalized form (legacy public interface)."""
    normalized, _ = validate_sql_with_evidence(sql)
    return normalized
