"""DataMind's user-facing question pipeline."""
import re

from dotenv import load_dotenv

from . import llm, snowflake_client
from .validator import SQLValidationError, validate_sql_with_evidence

load_dotenv()


def _intent(question):
    text = " ".join(question.lower().strip().split()).strip(".!?, ")
    if text in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "thanks", "thank you"}:
        return "greeting"
    if any(phrase in text for phrase in ("who are you", "what are you", "what can you do", "your capabilities", "tell me about yourself")):
        return "identity"
    ranking_request = any(term in text for term in (
        "best customer", "top customer", "high value", "valuable customer",
        "good customer", "most important customer",
    ))
    # Balance is the implemented value metric. Name/key only count when the
    # user explicitly says to order by that supported column; a segment filter
    # alone does not define what makes a customer "best".
    has_supported_metric = "balance" in text or "c_acctbal" in text or bool(re.search(
        r"\b(?:by|based on|ordered by|sorted by)\s+(?:the\s+)?(?:customer\s+)?(?:name|key)\b|\b(?:c_name|c_custkey)\b",
        text,
    ))
    if ranking_request and not has_supported_metric:
        return "ambiguous"
    return "data"


def _answer(columns, rows):
    count = len(rows)
    if count == 0:
        return "The query completed successfully and returned no rows."
    if count == 1:
        evidence = ", ".join(
            f"{name}={value if value is not None else 'NULL'}"
            for name, value in zip(columns, rows[0])
        )
        return f"Snowflake returned 1 row: {evidence}."
    shown = min(count, 3)
    samples = []
    for row in rows[:shown]:
        samples.append(", ".join(
            f"{name}={value if value is not None else 'NULL'}"
            for name, value in zip(columns, row)
        ))
    details = "; ".join(samples)
    suffix = f" Showing {shown} of {count} rows; see rows for the complete result." if count > shown else ""
    return f"Snowflake returned {count} rows: {details}.{suffix}"


def ask(question):
    """Answer a question as a dictionary with SQL and Snowflake evidence."""
    base = {"answer": "", "sql": None, "columns": [], "rows": [], "query_id": None,
            "assumptions": [], "warnings": [], "row_count": 0,
            "validation": {"status": "not_run", "checks": []},
            "execution": {"status": "not_run", "checks": []},
            "verification": {"status": "not_run", "checks": []},
            "clarification": {"required": False, "question": None, "options": []}}
    if not isinstance(question, str) or not question.strip():
        base.update(answer="Please enter a question.", warnings=["Question is empty."])
        return base
    intent = _intent(question)
    if intent == "greeting":
        base["answer"] = "Hello! I’m DataMind. Ask me about the Snowflake CUSTOMER dataset."
        return base
    if intent == "identity":
        base["answer"] = "I’m DataMind, an assistant that answers questions about the Snowflake TPC-H CUSTOMER dataset. I can query customer key, name, account balance, and market segment."
        return base
    if intent == "ambiguous":
        question = "How should I define “best” or “top”? Choose highest account balance, customer name A–Z, or customer key ascending."
        base["answer"] = question
        base["warnings"] = ["Clarification required before querying."]
        base["clarification"] = {
            "required": True,
            "question": question,
            "options": [
                {"label": "Highest account balance", "column": "C_ACCTBAL", "direction": "DESC"},
                {"label": "Customer name A–Z", "column": "C_NAME", "direction": "ASC"},
                {"label": "Customer key ascending", "column": "C_CUSTKEY", "direction": "ASC"},
            ],
        }
        return base
    try:
        generated = llm.generate_sql(question)
        assumptions = generated.get("assumptions", [])
        if isinstance(assumptions, str):
            assumptions = [assumptions]
        base["assumptions"] = [str(item) for item in assumptions] if isinstance(assumptions, list) else []
        base["sql"] = generated.get("sql")
    except Exception as exc:
        base["answer"] = "I couldn’t complete the request because SQL generation or validation failed."
        base["warnings"] = [f"SQL generation failed ({type(exc).__name__})."]
        return base
    try:
        base["sql"], base["validation"] = validate_sql_with_evidence(base["sql"])
    except SQLValidationError as exc:
        base["validation"] = exc.evidence
        base["answer"] = "I couldn’t complete the request because SQL validation failed: the generated query was rejected."
        base["warnings"] = [str(exc)]
        return base
    except Exception as exc:
        base["validation"] = {"status": "rejected", "checks": []}
        base["answer"] = "I couldn’t complete the request because SQL validation failed."
        base["warnings"] = [f"SQL validation failed ({type(exc).__name__})."]
        return base
    try:
        columns, rows, query_id = snowflake_client.execute_sql(base["sql"])
        columns = list(columns)
        rows = [list(row) for row in rows]
        base.update(columns=columns, rows=rows, query_id=query_id, row_count=len(rows))
        if any(len(row) != len(columns) for row in rows):
            raise ValueError("Snowflake returned rows that do not match the column metadata.")
        base.update(columns=columns, rows=rows, query_id=query_id,
                    row_count=len(rows), answer=_answer(columns, rows))
        base["execution"] = {"status": "succeeded", "checks": [
            {"name": "snowflake_execution", "status": "passed", "detail": "Snowflake returned result metadata and rows."}
        ]}
    except Exception as exc:
        base["query_id"] = getattr(exc, "query_id", base["query_id"])
        base["answer"] = "The Snowflake query failed; no result values are available."
        base["warnings"] = [f"Snowflake execution failed ({type(exc).__name__})."]
        base["execution"] = {"status": "failed", "checks": [
            {"name": "snowflake_execution", "status": "failed", "detail": "Snowflake did not return a complete result."}
        ]}
    return base
