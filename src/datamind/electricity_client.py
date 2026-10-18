"""Read-only SQLite execution over the bundled OWID electricity CSV."""
import csv
import re
import sqlite3
from pathlib import Path

from .validator import MAX_ROWS, validate_sql_with_evidence

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "electricity_mix.csv"


def _number(value, integer=False):
    if value == "":
        return None
    return int(value) if integer else float(value)


def entity_mentions(question):
    """Find exact, case-insensitive entity names explicitly present in a question."""
    if not DATA_PATH.is_file():
        return []
    with DATA_PATH.open(newline="", encoding="utf-8") as source:
        names = sorted({row["entity"] for row in csv.DictReader(source)}, key=len, reverse=True)
    text = question.casefold()
    return [name for name in names if re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", text)]


def execute_sql(sql, parameters=None):
    """Run validated, parameterized SELECT SQL against an ephemeral local DB."""
    normalized, _ = validate_sql_with_evidence(sql, "electricity_mix")
    parameters = list(parameters or [])
    if normalized.count("?") != len(parameters):
        raise ValueError("SQL placeholder count does not match bound values.")
    if not DATA_PATH.is_file():
        raise FileNotFoundError("Bundled electricity data is unavailable.")

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE electricity_mix ("
            "ENTITY TEXT NOT NULL, CODE TEXT NOT NULL, YEAR INTEGER NOT NULL, "
            "RENEWABLES_TWH REAL)"
        )
        with DATA_PATH.open(newline="", encoding="utf-8") as source:
            rows = csv.DictReader(source)
            connection.executemany(
                "INSERT INTO electricity_mix (ENTITY, CODE, YEAR, RENEWABLES_TWH) "
                "VALUES (?, ?, ?, ?)",
                ((row["entity"], row["code"], int(row["year"]),
                  _number(row["renewables_twh"])) for row in rows),
            )
        connection.execute("PRAGMA query_only=ON")

        permitted_actions = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}

        def authorize(action, arg1, arg2, _database, _trigger):
            if action not in permitted_actions:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_READ and arg1.lower() != "electricity_mix":
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or arg1 or "").lower() not in {
                "count", "sum", "avg", "min", "max",
            }:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        cursor = connection.execute(normalized, parameters)
        result_rows = cursor.fetchmany(MAX_ROWS + 1)
        if len(result_rows) > MAX_ROWS:
            raise RuntimeError("Local result exceeded the configured row maximum.")
        return [item[0] for item in cursor.description], result_rows, None
    finally:
        connection.close()
