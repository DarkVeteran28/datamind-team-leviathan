"""Fail-closed validation for the narrowly scoped CUSTOMER query surface."""
import sqlglot
from sqlglot import exp

TABLE = "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER"
ALLOWED_COLUMNS = {"C_CUSTKEY", "C_NAME", "C_ACCTBAL", "C_MKTSEGMENT"}
MAX_ROWS = 100


def validate_sql(sql):
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL is empty.")
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    if not sql or ";" in sql:
        raise ValueError("Only one SQL statement is permitted.")
    try:
        statements = sqlglot.parse(sql, read="snowflake")
    except sqlglot.errors.ParseError as exc:
        raise ValueError("SQL could not be parsed safely.") from exc
    if len(statements) != 1 or statements[0] is None:
        raise ValueError("Only one SQL statement is permitted.")
    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise ValueError("Only SELECT queries are allowed.")
    forbidden = (exp.Subquery, exp.Union, exp.Intersect, exp.Except, exp.Join,
                 exp.With, exp.Window, exp.Lateral, exp.Pivot, exp.Unnest)
    for kind in forbidden:
        if next(tree.find_all(kind), None) is not None:
            raise ValueError(f"Unsupported SQL structure: {kind.__name__}.")
    tables = list(tree.find_all(exp.Table))
    if len(tables) != 1:
        raise ValueError("Query must reference only the approved CUSTOMER table.")
    table = tables[0]
    if (table.name.upper() != "CUSTOMER" or (table.db and table.db.upper() != "TPCH_SF1")
            or (table.catalog and table.catalog.upper() != "SNOWFLAKE_SAMPLE_DATA")):
        raise ValueError("Query references an unapproved table.")
    allowed_args = {"expressions", "from_", "where", "group", "having", "order", "limit", "offset", "distinct"}
    for key, value in tree.args.items():
        if value is not None and key not in allowed_args:
            raise ValueError(f"Unsupported SELECT clause: {key}.")
    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise ValueError("Wildcard selection is not allowed.")
    for column in tree.find_all(exp.Column):
        if column.name == "*":
            continue
        if column.name.upper() not in ALLOWED_COLUMNS:
            raise ValueError(f"Unapproved column: {column.name}.")
        if column.table and column.table.upper() not in {table.alias_or_name.upper(), "CUSTOMER"}:
            raise ValueError(f"Unapproved column qualifier: {column.table}.")
    aggregates = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
    for func in tree.find_all(exp.Func):
        if func.sql_name().upper() not in aggregates:
            raise ValueError(f"Unsupported SQL function: {func.sql_name()}.")
    limit = tree.args.get("limit")
    if limit is None:
        tree = tree.limit(MAX_ROWS)
    else:
        value = limit.expression
        if not isinstance(value, exp.Literal) or not value.is_int or int(value.this) < 1:
            raise ValueError("LIMIT must be a positive integer literal.")
        if int(value.this) > MAX_ROWS:
            tree = tree.limit(MAX_ROWS)
    return tree.sql(dialect="snowflake")
