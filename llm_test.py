
import json
import urllib.request

url = "http://localhost:11434/api/chat"

payload = {
    "model": "gemma3:4b",
    "stream": False,
    "format": "json",
    "messages": [
        {
            "role": "system",
            "content": (
                "You generate Snowflake SQL for the table "
                "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER. "
                "Columns: C_CUSTKEY (integer), C_NAME (string), "
                "C_ACCTBAL (number), C_MKTSEGMENT (string). "
                "Return JSON with keys sql and assumptions. "
                "Generate exactly one read-only SELECT query. "
                "Use only the listed table and columns. "
                "Never invent query results."
            ),
        },
        {
            "role": "user",
            "content": (
                "Show the five customers with the highest "
                "account balances."
            ),
        },
    ],
    "options": {"temperature": 0},
}

request = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode("utf-8"))

    print("Gemma response:")
    print(result["message"]["content"])

except Exception as exc:
    print(f"Gemma test failed: {exc}")
