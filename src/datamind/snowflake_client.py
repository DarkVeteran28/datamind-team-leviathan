"""Snowflake execution boundary for the approved demo dataset."""
import os


def execute_sql(sql):
    # Import only when connecting so mocked/unit-only use does not need the
    # Snowflake connector installed in the interpreter.
    import snowflake.connector
    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_WAREHOUSE"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))
    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"], warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database="SNOWFLAKE_SAMPLE_DATA", schema="TPCH_SF1", login_timeout=20, network_timeout=30,
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
