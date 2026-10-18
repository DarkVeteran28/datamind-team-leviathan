
import os
import snowflake.connector
from dotenv import load_dotenv

load_dotenv()

required = [
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_WAREHOUSE",
]

missing = [key for key in required if not os.getenv(key)]
if missing:
    raise SystemExit(
        f"Missing environment variables: {', '.join(missing)}"
    )

conn = None

try:
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

    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                CURRENT_ACCOUNT(),
                CURRENT_USER(),
                CURRENT_ROLE(),
                CURRENT_WAREHOUSE()
        """)
        print("Connection verified:", cur.fetchone())

        cur.execute("""
            SELECT C_CUSTKEY, C_NAME, C_ACCTBAL
            FROM CUSTOMER
            ORDER BY C_CUSTKEY
            LIMIT 5
        """)

        print("Query ID:", cur.sfqid)
        print("Columns:", [column[0] for column in cur.description])

        for row in cur.fetchall():
            print(row)

except Exception as exc:
    print(f"Snowflake connection failed: {exc}")

finally:
    if conn is not None:
        conn.close()
