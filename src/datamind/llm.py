"""Local Ollama SQL generation for DataMind."""
import json
import os
import urllib.request

MODEL = os.getenv("DATAMIND_MODEL", "gemma3:4b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
TABLE = "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER"
ALLOWED_COLUMNS = {"C_CUSTKEY", "C_NAME", "C_ACCTBAL", "C_MKTSEGMENT"}


def generate_sql(question):
    columns = ", ".join(sorted(ALLOWED_COLUMNS))
    payload = {
        "model": MODEL, "stream": False, "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": (
                f"Generate one Snowflake SELECT query for {TABLE}. Allowed columns: {columns}. "
                "Return JSON with keys sql and assumptions. Use only this table and these columns. "
                "Never generate mutations, DDL, multiple statements, or invent results."
            )},
            {"role": "user", "content": question},
        ],
    }
    request = urllib.request.Request(
        OLLAMA_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode())
    parsed = json.loads(result["message"]["content"])
    if not isinstance(parsed, dict) or not isinstance(parsed.get("sql"), str):
        raise ValueError("Ollama response did not contain SQL.")
    assumptions = parsed.get("assumptions", [])
    if isinstance(assumptions, str):
        assumptions = [assumptions]
    if not isinstance(assumptions, list):
        assumptions = []
    return {"sql": parsed["sql"], "assumptions": [str(x) for x in assumptions]}
