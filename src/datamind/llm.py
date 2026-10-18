"""Local Ollama interpretation into a typed query-plan proposal."""
import json
import os
import urllib.request

from .semantic_query import QueryPlan
from .dataset_registry import DATASETS, DEFAULT_DATASET_ID

MODEL = os.getenv("DATAMIND_MODEL", "gemma3:4b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")


def generate_plan(question, dataset_id=DEFAULT_DATASET_ID):
    """Ask Gemma for declarative intent; the model is never asked for SQL."""
    if dataset_id not in DATASETS:
        raise ValueError("The selected dataset is not registered.")
    plan_schema = QueryPlan.model_json_schema()
    if dataset_id == "electricity_mix":
        catalog_instructions = (
            "The selected dataset is OWID annual country renewable electricity generation. "
            "Its only fields are ENTITY (country or territory name, string), CODE (ISO alpha-3 code, string), "
            "YEAR (integer), and RENEWABLES_TWH (combined generation from solar, wind, hydropower, bioenergy, "
            "geothermal, wave, and tidal in terawatt-hours). It contains no individual source breakdown, "
            "percentage share, total generation, or per-capita values. Use YEAR filters for year requests, "
            "ENTITY filters for named countries, and group by ENTITY or YEAR when comparison/trends are requested. "
            "This bundled snapshot ends in 2025; interpret 'latest available year' as YEAR eq 2025. "
            "SUM and AVG are supported only for RENEWABLES_TWH; COUNT(field) counts non-null values and COUNT(*) "
            "counts rows. Use clarification for ambiguous intent and unsupported for unavailable measures. "
            "Never claim absent rows mean zero. Use an explicit LIMIT no greater than 100."
            " For 'What was renewable electricity generation in India in 2024?', the exact plan is dimensions "
            "[ENTITY, YEAR, RENEWABLES_TWH], no metrics, filters [{field:ENTITY,operator:eq,value:India}, "
            "{field:YEAR,operator:eq,value:2024}], sort [], limit 1. For a trend from 2023 through 2025 in India, "
            "group by YEAR, SUM RENEWABLES_TWH, filter ENTITY eq India AND YEAR gte 2023 AND YEAR lte 2025, "
            "sort YEAR ASC. For top countries in 2025, select ENTITY and RENEWABLES_TWH, filter YEAR eq 2025, "
            "sort RENEWABLES_TWH DESC, and use the requested limit. For 'Which countries generated the most renewable electricity in 2025?', "
            "select [ENTITY, RENEWABLES_TWH], filter only YEAR eq 2025, sort RENEWABLES_TWH DESC, limit 5; "
            "For 'Rank countries by renewable electricity generation for 2025, highest first', use the same plan "
            "with limit null (trusted code will apply the 100-row cap). "
            "filters must contain exactly that one year predicate: do not add ENTITY with a null value, "
            "do not filter ENTITY to a guessed country, and never include null-valued filters. Never omit a country or exact-year filter "
            "stated in the question; if the requested comparison needs multiple countries or unsupported fuel "
            "fields, return unsupported rather than widening the query."
        )
    else:
        catalog_instructions = (
            "The only fields are C_CUSTKEY (integer), C_NAME (string), C_ACCTBAL (number), "
            "C_MKTSEGMENT (string). SUM and AVG only support C_ACCTBAL; MIN/MAX only numeric fields. "
            "String filters only use eq or ne. Set status=clarification when intent or ranking metric is unclear; "
            "use status=unsupported when the request needs data or operations outside this catalog. Do not guess missing metrics. "
            "For a request for the top N individual customers by account balance, return customer dimensions, "
            "no aggregate metric, sort by field C_ACCTBAL with direction DESC, and limit N. "
            "Do not represent ranking individual customers as MAX(C_ACCTBAL) or another grouped metric. "
            "Example: for 'top 5 customers by account balance', use dimensions [C_CUSTKEY, C_NAME, C_ACCTBAL], "
            "metrics [], filters [], sort [{field:C_ACCTBAL,direction:DESC}], limit 5, and assumptions []."
        )
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
                "status=query|clarification|unsupported. dimensions is a list of selected catalog "
                "fields; metrics is a list of aggregate objects; filters is a list of typed comparisons; "
                "sort is a list of objects with exactly the applicable field/operation and direction; "
                "limit is an integer or null; message is for clarification/unsupported; assumptions is a string array. "
                + catalog_instructions + " "
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
