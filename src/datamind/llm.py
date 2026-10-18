"""Local Ollama interpretation into a typed query-plan proposal."""
import json
import os
import urllib.request

MODEL = os.getenv("DATAMIND_MODEL", "gemma3:4b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
def generate_plan(question):
    """Ask Gemma for declarative intent; the model is never asked for SQL."""
    payload = {
        "model": MODEL, "stream": False, "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": (
                "Interpret the question as a declarative DataMind query plan. Never return SQL, "
                "identifiers outside this catalog, expressions, or executable code. Return exactly "
                "one JSON object with version=1, status=query|clarification|unsupported, "
                "dimensions (approved CUSTOMER fields), metrics (objects with operation=count|sum|avg|min|max "
                "and optional field), filters (field, operator=eq|ne|gt|gte|lt|lte, typed value), "
                "sort (field and/or operation with direction=ASC|DESC), limit (integer or null), "
                "message (for clarification/unsupported), and assumptions (string array). "
                "The only fields are C_CUSTKEY (integer), C_NAME (string), C_ACCTBAL (number), "
                "C_MKTSEGMENT (string). SUM and AVG only support C_ACCTBAL; MIN/MAX only numeric "
                "fields. String filters only use eq or ne. Set status=clarification when intent "
                "or ranking metric is unclear; use status=unsupported when the request needs "
                "data or operations outside this catalog. Do not guess missing metrics."
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
    if not isinstance(parsed, dict):
        raise ValueError("Ollama response did not contain a query plan.")
    return parsed
