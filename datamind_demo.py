
import json
import os
import re
import urllib.request
from decimal import Decimal

import snowflake.connector
import sqlglot
from sqlglot import exp
from dotenv import load_dotenv

load_dotenv()

MODEL = "gemma3:4b"
OLLAMA_URL = "http://localhost:11434/api/chat"

TABLE = "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER"
ALLOWED_COLUMNS = {
    "C_CUSTKEY", "C_NAME", "C_ACCTBAL", "C_MKTSEGMENT"
}


def generate_sql(question):
    payload = {
        "model": MODEL,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {
                "role": "system",
                "content": (
                    f"Generate one Snowflake SELECT query for {TABLE}. "
                    "Allowed columns: C_CUSTKEY, C_NAME, C_ACCTBAL, "
                    "C_MKTSEGMENT. Return JSON with keys sql and "
                    "assumptions. Use only this table and these columns. "
                    "Never generate INSERT, UPDATE, DELETE, DDL, or "
                    "multiple statements. Do not invent results."
                ),
            },
            {"role": "user", "content": question},
        ],
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode())

    return json.loads(result["message"]["content"])


def validate_sql(sql):
    # Permit a single trailing semicolon, but no multiple statements.
    sql = sql.strip()
    sql = re.sub(r";\s*$", "", sql)

    if not sql:
        raise ValueError("Gemma returned empty SQL.")

    statements = sqlglot.parse(sql, read="snowflake")
    if len(statements) != 1 or statements[0] is None:
        raise ValueError("Only one SQL statement is permitted.")

    tree = statements[0]

    if not isinstance(tree, exp.Select):
        raise ValueError("Only SELECT queries are allowed.")

    tables = list(tree.find_all(exp.Table))
    if not tables:
        raise ValueError("Query must reference the approved table.")

    for table in tables:
        if (
            table.name.upper() != "CUSTOMER"
            or (table.db and table.db.upper() != "TPCH_SF1")
            or (
                table.catalog
                and table.catalog.upper() != "SNOWFLAKE_SAMPLE_DATA"
            )
        ):
            raise ValueError("Query references an unapproved table.")

    for column in tree.find_all(exp.Column):
        if column.name != "*" and column.name.upper() not in ALLOWED_COLUMNS:
            raise ValueError(f"Unapproved column: {column.name}")

    if any(
            next(tree.find_all(kind), None) is not None
            for kind in (exp.Subquery, exp.Union)
        ):
            raise ValueError(
                "Nested queries and UNION are not supported yet."
            )

    # Apply a maximum row limit.
    limit = tree.args.get("limit")
    if limit is None:
        tree = tree.limit(100)
    else:
        value = limit.expression
        if not isinstance(value, exp.Literal) or not value.is_int:
            raise ValueError("LIMIT must be a positive integer literal.")
        count = int(value.this)
        if count < 1:
            raise ValueError("LIMIT must be positive.")
        if count > 100:
            tree = tree.limit(100)

    return tree.sql(dialect="snowflake")


def execute_sql(sql):
    required = [
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_WAREHOUSE",
    ]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(
            "Missing environment variables: " + ", ".join(missing)
        )

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database="SNOWFLAKE_SAMPLE_DATA",
        schema="TPCH_SF1",
        login_timeout=20,
        network_timeout=30,
    )

    try:
        with conn.cursor() as cur:
            cur.execute("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 30")
            cur.execute("ALTER SESSION SET QUERY_TAG = 'datamind_hackathon'")
            cur.execute(sql)

            columns = [item[0] for item in cur.description]
            rows = cur.fetchmany(101)
            query_id = cur.sfqid

            if len(rows) > 100:
                raise ValueError("Unexpected row limit overflow.")

            return columns, rows, query_id
    finally:
        conn.close()


def main():
    print("\nDataMind | Talk to Your Data")
    print("Dataset: Snowflake TPC-H CUSTOMER")
    print("Type 'exit' to quit.\n")

    while True:
        question = input("Ask your data > ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue

        try:
            result = generate_sql(question)
            sql = validate_sql(result["sql"])

            print("\nValidated SQL:")
            print(sql)

            columns, rows, query_id = execute_sql(sql)

            print("\nActual Snowflake results:")
            print(" | ".join(columns))
            for row in rows:
                print(" | ".join(
                    str(value) if value is not None else "NULL"
                    for value in row
                ))

            print(f"\nRows returned: {len(rows)}")
            print(f"Snowflake query ID: {query_id}")
            print(f"Model assumptions: {result.get('assumptions', [])}")

        except Exception as exc:
            print(f"\nRequest could not be completed: {exc}")

        print()

if __name__ == "__main__":
    main()
