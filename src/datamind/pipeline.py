"""DataMind's user-facing question pipeline."""
import re

from dotenv import load_dotenv

from . import electricity_client, llm, snowflake_client
from .dataset_registry import DATASETS, DEFAULT_DATASET_ID
from .semantic_query import (
    PlanValidationError,
    compile_query_plan,
    validate_query_plan,
)
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


def _is_electricity_country_ranking(question):
    text = question.casefold()
    return bool(
        re.search(r"\b(?:country|countries)\b", text)
        and re.search(r"\b(?:rank|top|most|highest|largest)\b", text)
        and "renewable" in text
        and re.search(r"\b(?:generation|generated|generate)\b", text)
    )


def _answer(columns, rows, source="Snowflake"):
    count = len(rows)
    if count == 0:
        return "The query completed successfully and returned no rows."
    if count == 1:
        evidence = ", ".join(
            f"{name}={value if value is not None else 'NULL'}"
            for name, value in zip(columns, rows[0])
        )
        return f"{source} returned 1 row: {evidence}."
    shown = min(count, 3)
    samples = []
    for row in rows[:shown]:
        samples.append(", ".join(
            f"{name}={value if value is not None else 'NULL'}"
            for name, value in zip(columns, row)
        ))
    details = "; ".join(samples)
    suffix = f" Showing {shown} of {count} rows; see rows for the complete result." if count > shown else ""
    return f"{source} returned {count} rows: {details}.{suffix}"


def _verify_answer(answer, columns, rows, row_count, source="Snowflake"):
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
        match = re.match(r"^(.*?) returned (\d+) rows?:", answer)
        reported_count_matches = bool(match and match.group(1) == source and int(match.group(2)) == actual_count)
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
        expected_answer = f"{source} returned {actual_count} {row_label}: {details}.{suffix}"
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


def _validate_explicit_electricity_scope(question, plan, evidence):
    """Fail closed if Gemma drops an explicit, supported country or year constraint."""
    checks = list(evidence.get("checks", []))
    filters = plan.filters
    mentions = electricity_client.entity_mentions(question)
    entity_filter_values = [item.value for item in filters if item.field == "ENTITY" and item.operator == "eq"]
    if len(entity_filter_values) > 1:
        detail = "Multiple country filters require a multi-value operator that is not supported."
        checks.append({"name": "explicit_question_scope", "status": "failed", "detail": detail})
        raise PlanValidationError(detail, {"status": "rejected", "checks": checks})
    explicit_values = [value for value in entity_filter_values
                        if re.search(r"(?<!\w)" + re.escape(value.casefold()) + r"(?!\w)", question.casefold())]
    if len(explicit_values) < len(entity_filter_values):
        detail = "The generated plan added a country filter that was not stated in the question."
        checks.append({"name": "explicit_question_scope", "status": "failed", "detail": detail})
        raise PlanValidationError(detail, {"status": "rejected", "checks": checks})
    if len(mentions) > 1:
        detail = "Multiple named countries require a multi-value filter that is not supported."
        checks.append({"name": "explicit_question_scope", "status": "failed", "detail": detail})
        raise PlanValidationError(detail, {"status": "rejected", "checks": checks})
    if mentions:
        matching = [item for item in filters if item.field == "ENTITY" and item.operator == "eq" and item.value.casefold() == mentions[0].casefold()]
        if not matching:
            detail = "The generated plan did not preserve the explicitly named country filter."
            checks.append({"name": "explicit_question_scope", "status": "failed", "detail": detail})
            raise PlanValidationError(detail, {"status": "rejected", "checks": checks})

    country_ranking = _is_electricity_country_ranking(question)
    if country_ranking:
        ranked_countries = "ENTITY" in plan.dimensions
        metric_selected = "RENEWABLES_TWH" in plan.dimensions or any(
            metric.field == "RENEWABLES_TWH" for metric in plan.metrics
        )
        ranked_by_generation = any(
            item.field == "RENEWABLES_TWH" and item.direction == "DESC" and item.operation is None
            for item in plan.sort
        )
        if not (ranked_countries and metric_selected and ranked_by_generation):
            detail = "The generated plan did not express a country ranking by renewable generation."
            checks.append({"name": "explicit_question_scope", "status": "failed", "detail": detail})
            raise PlanValidationError(detail, {"status": "rejected", "checks": checks})

    years = sorted({int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", question)})
    year_filters = [item for item in filters if item.field == "YEAR"]
    lowered = question.casefold()
    if len(years) == 1:
        matched = any(item.operator == "eq" and item.value == years[0] for item in year_filters)
        if not matched:
            detail = "The generated plan did not preserve the explicitly requested year."
            checks.append({"name": "explicit_question_scope", "status": "failed", "detail": detail})
            raise PlanValidationError(detail, {"status": "rejected", "checks": checks})
    elif len(years) > 1:
        is_range = (
            bool(re.search(r"\b(?:from|between)\b", lowered)
                 and re.search(r"\b(?:through|until|to)\b", lowered))
            or bool(re.search(r"\b(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}\b", question))
        )
        if not is_range:
            detail = "Multiple distinct years need a range or comparison that the current filter grammar does not support."
            checks.append({"name": "explicit_question_scope", "status": "failed", "detail": detail})
            raise PlanValidationError(detail, {"status": "rejected", "checks": checks})
        lower_ok = any(item.operator in {"eq", "gte", "gt"} and item.value == years[0] for item in year_filters)
        upper_ok = any(item.operator in {"eq", "lte", "lt"} and item.value == years[-1] for item in year_filters)
        if not lower_ok or not upper_ok:
            detail = "The generated plan did not preserve both ends of the explicitly requested year range."
            checks.append({"name": "explicit_question_scope", "status": "failed", "detail": detail})
            raise PlanValidationError(detail, {"status": "rejected", "checks": checks})
    elif "latest" in lowered or "most recent" in lowered:
        latest_year = DATASETS["electricity_mix"]["subset"]["year_max"]
        if not any(item.operator == "eq" and item.value == latest_year for item in year_filters):
            detail = "The generated plan did not apply the latest year in the bundled snapshot."
            checks.append({"name": "explicit_question_scope", "status": "failed", "detail": detail})
            raise PlanValidationError(detail, {"status": "rejected", "checks": checks})
    checks.append({"name": "explicit_question_scope", "status": "passed",
                   "detail": "Recognized explicit country and year constraints are preserved in the validated plan."})
    return {"status": "passed", "checks": checks}


def _deterministic_electricity_ranking(question):
    """Build a typed plan for a narrow, explicit all-country generation ranking."""
    text = question.casefold()
    if not _is_electricity_country_ranking(question):
        return None
    if electricity_client.entity_mentions(question):
        return None
    years = sorted({int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", question)})
    if len(years) > 1:
        return None
    year = years[0] if years else (
        DATASETS["electricity_mix"]["subset"]["year_max"]
        if "latest" in text or "most recent" in text else None
    )
    if year is None:
        return None
    limit_match = re.search(r"\btop\s+(\d{1,3})\b", text)
    limit = int(limit_match.group(1)) if limit_match else 5
    assumptions = [] if limit_match else ["Showing the top five because no result count was specified."]
    return {
        "version": 1, "status": "query",
        "dimensions": ["ENTITY", "RENEWABLES_TWH"],
        "metrics": [],
        "filters": [{"field": "YEAR", "operator": "eq", "value": year}],
        "sort": [{"field": "RENEWABLES_TWH", "direction": "DESC"}],
        "limit": limit, "assumptions": assumptions,
    }


def ask(question, dataset_id=DEFAULT_DATASET_ID):
    """Answer a question as a dictionary with SQL and Snowflake evidence."""
    base = {"answer": "", "dataset_id": dataset_id, "plan_source": "not_run", "sql": None, "sql_parameters": [], "query_plan": None,
            "plan_validation": {"status": "not_run", "checks": []},
            "outcome": "no_query", "columns": [], "rows": [], "query_id": None,
            "assumptions": [], "warnings": [], "row_count": 0,
            "validation": {"status": "not_run", "checks": []},
            "execution": {"status": "not_run", "checks": []},
            "verification": {"status": "not_run", "checks": []},
            "clarification": {"required": False, "question": None, "options": []}}
    if not isinstance(question, str) or not question.strip():
        base.update(answer="Please enter a question.", warnings=["Question is empty."])
        return base
    if dataset_id not in DATASETS:
        base.update(answer="The requested dataset is not supported.", outcome="unsupported",
                    warnings=["Dataset ID is not registered."])
        return base
    engine = "local dataset" if dataset_id == "electricity_mix" else "Snowflake"
    intent = _intent(question)
    if intent == "greeting":
        base["answer"] = f"Hello! I’m DataMind. Ask me about {DATASETS[dataset_id]['name']}."
        return base
    if intent == "identity":
        fields = ", ".join(DATASETS[dataset_id]["fields"])
        base["answer"] = f"I’m DataMind. I can query {DATASETS[dataset_id]['name']}: {fields}."
        return base
    if dataset_id == "electricity_mix" and _is_electricity_country_ranking(question):
        lowered = question.casefold()
        has_year = bool(re.search(r"\b(?:19|20)\d{2}\b", question))
        if not has_year and "latest" not in lowered and "most recent" not in lowered:
            clarification = ("Which year should I rank? This bundled dataset covers 2000–2025. "
                             "Name a year or ask for the latest available year (2025).")
            base.update(answer=clarification, outcome="clarification",
                        warnings=["Clarification required before query planning."],
                        clarification={"required": True, "question": clarification, "options": []})
            return base
    if intent == "ambiguous":
        question = "How should I define “best” or “top”? Choose highest account balance, customer name A–Z, or customer key ascending."
        base["answer"] = question
        base["warnings"] = ["Clarification required before querying."]
        base["outcome"] = "clarification"
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
        deterministic_plan = (_deterministic_electricity_ranking(question)
                              if dataset_id == "electricity_mix" else None)
        if deterministic_plan is not None:
            generated = deterministic_plan
            base["plan_source"] = "deterministic_rule"
        else:
            base["plan_source"] = "ollama"
            generated = (llm.generate_plan(question) if dataset_id == DEFAULT_DATASET_ID
                         else llm.generate_plan(question, dataset_id=dataset_id))
    except Exception as exc:
        base["answer"] = "I couldn’t complete the request because query-plan generation failed."
        base["warnings"] = [f"Query-plan generation failed ({type(exc).__name__})."]
        base["outcome"] = "failed"
        return base
    try:
        plan, base["plan_validation"] = validate_query_plan(generated, dataset_id)
        if dataset_id == "electricity_mix" and plan.status == "query":
            base["plan_validation"] = _validate_explicit_electricity_scope(question, plan, base["plan_validation"])
    except PlanValidationError as exc:
        base["plan_validation"] = exc.evidence
        base["answer"] = "The generated query plan was rejected before SQL compilation."
        failed_check = next((item for item in exc.evidence.get("checks", [])
                             if item.get("status") == "failed"), None)
        reason = failed_check.get("detail") if failed_check else "the plan is malformed or unsupported."
        base["warnings"] = [f"Query-plan validation failed: {reason}"]
        base["outcome"] = "rejected"
        return base
    base["query_plan"] = plan.model_dump(mode="json")
    base["assumptions"] = list(plan.assumptions)
    if plan.status == "clarification":
        base["answer"] = plan.message or "Please clarify what data you want to inspect."
        base["clarification"] = {
            "required": True,
            "question": base["answer"],
            "options": [],
        }
        base["warnings"] = ["Clarification required before query compilation."]
        base["outcome"] = "clarification"
        return base
    if plan.status == "unsupported":
        base["answer"] = ("This request is outside the supported CUSTOMER fields and query operations."
                          if dataset_id == DEFAULT_DATASET_ID else
                          f"This request is outside the supported {DATASETS[dataset_id]['name']} fields and query operations.")
        base["warnings"] = ["The query plan marked this request as unsupported."]
        base["outcome"] = "unsupported"
        return base
    try:
        base["sql"], base["sql_parameters"] = compile_query_plan(plan, dataset_id)
        base["sql"], base["validation"] = validate_sql_with_evidence(base["sql"], dataset_id)
    except SQLValidationError as exc:
        base["validation"] = exc.evidence
        base["answer"] = "The compiled SQL was rejected by the safety validator before execution."
        base["warnings"] = ["SQL validation failed: the compiled statement did not pass safety checks."]
        base["outcome"] = "rejected"
        return base
    except Exception as exc:
        base["answer"] = "The query plan could not be compiled into a supported SQL statement."
        base["warnings"] = [f"SQL compilation failed ({type(exc).__name__})."]
        base["outcome"] = "rejected"
        return base
    try:
        if dataset_id == "electricity_mix":
            columns, rows, query_id = electricity_client.execute_sql(base["sql"], base["sql_parameters"])
        elif base["sql_parameters"]:
            columns, rows, query_id = snowflake_client.execute_sql(base["sql"], base["sql_parameters"])
        else:
            columns, rows, query_id = snowflake_client.execute_sql(base["sql"])
        columns = list(columns)
        rows = [list(row) for row in rows]
        base.update(columns=columns, rows=rows, query_id=query_id, row_count=len(rows))
        if any(len(row) != len(columns) for row in rows):
            raise ValueError("Snowflake returned rows that do not match the column metadata.")
        base.update(columns=columns, rows=rows, query_id=query_id,
                    row_count=len(rows), answer=_answer(columns, rows, engine))
        base["execution"] = {"status": "succeeded", "engine": engine, "dataset_id": dataset_id, "checks": [
            {"name": "data_execution", "status": "passed", "detail": f"{engine} returned result metadata and rows."}
        ]}
        base["outcome"] = "success"
        base["verification"] = _verify_answer(base["answer"], columns, rows, base["row_count"], engine)
        if base["verification"]["status"] == "failed":
            base["warnings"].append("Answer/result consistency verification failed.")
    except Exception as exc:
        base["query_id"] = getattr(exc, "query_id", base["query_id"])
        base["answer"] = f"The {engine} query failed; no result values are available."
        base["warnings"] = [f"{engine} execution failed ({type(exc).__name__})."]
        base["execution"] = {"status": "failed", "engine": engine, "dataset_id": dataset_id, "checks": [
            {"name": "data_execution", "status": "failed", "detail": f"{engine} did not return a complete result."}
        ]}
        base["outcome"] = "failed"
    return base
