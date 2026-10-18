"""Snowflake execution boundary for the approved demo dataset."""
import os


class SnowflakeExecutionError(RuntimeError):
    """Safe execution error that retains Snowflake's query ID when known."""

    def __init__(self, query_id=None):
        super().__init__("Snowflake statement failed.")
        self.query_id = query_id


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
            query_id = cur.sfqid
            columns = [item[0] for item in cur.description]
            rows = cur.fetchmany(101)
            if len(rows) > 100:
                raise SnowflakeExecutionError(query_id)
            return columns, rows, query_id
    except SnowflakeExecutionError:
        raise
    except Exception as exc:
        # Do not expose connector exception text: it can contain account or
        # statement details. Keep the server query ID when execution reached it.
        raise SnowflakeExecutionError(locals().get("query_id")) from exc
    finally:
        conn.close()
