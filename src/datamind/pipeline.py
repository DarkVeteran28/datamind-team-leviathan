"""DataMind's user-facing question pipeline."""
from dotenv import load_dotenv

from . import llm, snowflake_client
from .validator import validate_sql

load_dotenv()


def _intent(question):
    text = " ".join(question.lower().strip().split()).strip(".!?, ")
    if text in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "thanks", "thank you"}:
        return "greeting"
    if any(phrase in text for phrase in ("who are you", "what are you", "what can you do", "your capabilities", "tell me about yourself")):
        return "identity"
    # Terms whose meaning depends on an unstated metric, order, or threshold.
    if any(term in text for term in ("best customer", "top customer", "high value", "valuable customer", "good customer", "most important")) and not any(metric in text for metric in ("balance", "account balance", "name", "key", "segment")):
        return "ambiguous"
    return "data"


def _answer(columns, rows):
    count = len(rows)
    if count == 0:
        return "The query completed successfully and returned no rows."
    if count == 1:
        evidence = ", ".join(f"{name}={value if value is not None else 'NULL'}" for name, value in zip(columns, rows[0]))
        return f"The query returned 1 row: {evidence}."
    return f"The query returned {count} rows. The result table below contains the Snowflake values."


def ask(question):
    """Answer a question as a dictionary with SQL and Snowflake evidence."""
    base = {"answer": "", "sql": None, "columns": [], "rows": [], "query_id": None,
            "assumptions": [], "warnings": [], "row_count": 0}
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
        base["answer"] = "How should I define that—for example, by highest account balance or by a particular market segment?"
        base["warnings"] = ["Clarification required before querying."]
        return base
    try:
        generated = llm.generate_sql(question)
        base["assumptions"] = generated.get("assumptions", [])
        base["sql"] = generated.get("sql")
        base["sql"] = validate_sql(base["sql"])
    except Exception as exc:
        base["answer"] = "I couldn’t complete the request because SQL generation or validation failed."
        base["warnings"] = [str(exc)]
        return base
    try:
        columns, rows, query_id = snowflake_client.execute_sql(base["sql"])
        base.update(columns=list(columns), rows=[list(row) for row in rows], query_id=query_id,
                    row_count=len(rows), answer=_answer(columns, rows))
    except Exception as exc:
        base["answer"] = "The Snowflake query failed; no result values are available."
        base["warnings"] = [str(exc)]
    return base
