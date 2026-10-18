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


def _verify_answer(answer, columns, rows, row_count):
    """Check deterministic answer/result consistency, not SQL intent correctness."""
    actual_count = len(rows)
    checks = []

    metadata_matches = row_count == actual_count
    checks.append({
        "name": "returned_row_count",
        "status": "passed" if metadata_matches else "failed",
        "detail": (f"row_count {row_count} matches {actual_count} returned rows."
                   if metadata_matches else f"row_count {row_count} does not match {actual_count} returned rows."),
    })

    if actual_count == 0:
        empty_is_described = answer == "The query completed successfully and returned no rows."
        checks.append({
            "name": "empty_result_description",
            "status": "passed" if empty_is_described else "failed",
            "detail": ("The answer describes an empty result." if empty_is_described
                       else "The answer does not accurately describe the empty result."),
        })
        checks.append({"name": "displayed_samples", "status": "skipped",
                       "detail": "No returned rows are available for sample comparison."})
    else:
        match = re.match(r"^Snowflake returned (\d+) rows?:", answer)
        reported_count_matches = bool(match and int(match.group(1)) == actual_count)
        checks.append({
            "name": "answer_row_count",
            "status": "passed" if reported_count_matches else "failed",
            "detail": (f"The answer reports {actual_count} returned rows." if reported_count_matches
                       else "The row count stated in the answer does not match returned rows."),
        })
        sample_count = min(actual_count, 3)
        samples = [", ".join(
            f"{column}={value if value is not None else 'NULL'}"
            for column, value in zip(columns, row)
        ) for row in rows[:sample_count]]
        details = "; ".join(samples)
        row_label = "row" if actual_count == 1 else "rows"
        suffix = (f" Showing {sample_count} of {actual_count} rows; see rows for the complete result."
                  if actual_count > sample_count else "")
        expected_answer = f"Snowflake returned {actual_count} {row_label}: {details}.{suffix}"
        rendered_answer_matches = answer == expected_answer
        checks.append({
            "name": "displayed_samples",
            "status": "passed" if rendered_answer_matches else "failed",
            "detail": ("Displayed values match the deterministic rendering of returned columns and rows."
                       if rendered_answer_matches else
                       "Displayed values do not match the deterministic rendering of returned columns and rows."),
        })
        checks.append({"name": "empty_result_description", "status": "passed",
                       "detail": "Returned rows are present and the answer does not describe an empty result."})

    checks.append({"name": "ranking_order", "status": "skipped",
                   "detail": "The answer makes no explicit ranking claim to compare."})
    checks.append({"name": "semantic_correctness", "status": "not_run",
                   "detail": "Consistency checks do not establish that SQL fully captures the user's intent."})
    status = "failed" if any(check["status"] == "failed" for check in checks) else "passed"
    return {"status": status, "checks": checks}


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
        base["verification"] = _verify_answer(base["answer"], columns, rows, base["row_count"])
        if base["verification"]["status"] == "failed":
            base["warnings"].append("Answer/result consistency verification failed.")
    except Exception as exc:
        base["query_id"] = getattr(exc, "query_id", base["query_id"])
        base["answer"] = "The Snowflake query failed; no result values are available."
        base["warnings"] = [f"Snowflake execution failed ({type(exc).__name__})."]
        base["execution"] = {"status": "failed", "checks": [
            {"name": "snowflake_execution", "status": "failed", "detail": "Snowflake did not return a complete result."}
        ]}
    return base
