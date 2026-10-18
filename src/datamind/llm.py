"""Local Ollama interpretation into a typed query-plan proposal."""
import json
import os
import urllib.request

from .semantic_query import QueryPlan

MODEL = os.getenv("DATAMIND_MODEL", "gemma3:4b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")


def generate_plan(question):
    """Ask Gemma for declarative intent; the model is never asked for SQL."""
    plan_schema = QueryPlan.model_json_schema()
    payload = {
        # Ollama's structured output mode constrains decoding to the same
        # versioned schema the backend validates. Semantic checks still run
        # in validate_query_plan before any compilation or execution.
        "model": MODEL, "stream": False, "format": plan_schema,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": (
                "Interpret the question as a declarative DataMind query plan. Never return SQL, "
                "identifiers outside this catalog, expressions, or executable code. Return exactly "
                "one JSON object matching the supplied response schema, with version=1 and "
                "status=query|clarification|unsupported. dimensions is a list of selected CUSTOMER "
                "fields; metrics is a list of aggregate objects; filters is a list of typed comparisons; "
                "sort is a list of objects with exactly the applicable field/operation and direction; "
                "limit is an integer or null; message is for clarification/unsupported; assumptions is a string array. "
                "The only fields are C_CUSTKEY (integer), C_NAME (string), C_ACCTBAL (number), "
                "C_MKTSEGMENT (string). SUM and AVG only support C_ACCTBAL; MIN/MAX only numeric "
                "fields. String filters only use eq or ne. Set status=clarification when intent "
                "or ranking metric is unclear; use status=unsupported when the request needs "
                "data or operations outside this catalog. Do not guess missing metrics. For a request "
                "for the top N individual customers by account balance, return customer dimensions, "
                "no aggregate metric, sort by field C_ACCTBAL with direction DESC, and limit N. "
                "Do not represent ranking individual customers as MAX(C_ACCTBAL) or another grouped metric. "
                "Example: for 'top 5 customers by account balance', use dimensions "
                "[C_CUSTKEY, C_NAME, C_ACCTBAL], metrics [], filters [], sort "
                "[{field:C_ACCTBAL,direction:DESC}], limit 5, and assumptions []. "
                "The required JSON schema is: "
                + json.dumps(plan_schema, separators=(",", ":"), ensure_ascii=True)
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
