"""Typed query-plan schema, semantic validation, and SQL compiler tests."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datamind.semantic_query import PlanValidationError, compile_query_plan, validate_query_plan
from datamind.validator import validate_sql_with_evidence


def plan(**overrides):
    value = {"version": 1, "status": "query", "dimensions": [], "metrics": [],
             "filters": [], "sort": [], "limit": None, "assumptions": []}
    value.update(overrides)
    return value


def test_compiles_grouped_aggregate_with_deterministic_identifiers():
    validated, evidence = validate_query_plan(plan(
        dimensions=["C_MKTSEGMENT"], metrics=[{"operation": "count"}],
        sort=[{"field": "C_MKTSEGMENT", "direction": "ASC"}], limit=10,
    ))
    sql, parameters = compile_query_plan(validated)

    assert "SELECT C_MKTSEGMENT, COUNT(*) AS CUSTOMER_COUNT" in sql
    assert "GROUP BY C_MKTSEGMENT" in sql
    assert "ORDER BY C_MKTSEGMENT ASC LIMIT 10" in sql
    assert parameters == []
    assert evidence["status"] == "passed"


def test_compiles_numeric_metric_and_sort_from_approved_catalog():
    validated, _ = validate_query_plan(plan(
        metrics=[{"operation": "avg", "field": "C_ACCTBAL"}],
        sort=[{"field": "C_ACCTBAL", "operation": "avg", "direction": "DESC"}], limit=3,
    ))
    sql, _ = compile_query_plan(validated)
    assert "AVG(C_ACCTBAL) AS C_ACCTBAL_AVG" in sql
    assert "ORDER BY AVG(C_ACCTBAL) DESC LIMIT 3" in sql


def test_row_query_can_sort_by_an_approved_field_not_in_the_projection():
    validated, _ = validate_query_plan(plan(
        dimensions=["C_CUSTKEY"], sort=[{"field": "C_ACCTBAL", "direction": "DESC"}], limit=5,
    ))
    sql, _ = compile_query_plan(validated)
    assert "SELECT C_CUSTKEY FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER" in sql
    assert "ORDER BY C_ACCTBAL DESC LIMIT 5" in sql


def test_filter_values_are_parameter_bound_and_cannot_change_compiled_sql():
    injected = "BUILDING' OR 1=1; DROP TABLE CUSTOMER --"
    validated, _ = validate_query_plan(plan(
        dimensions=["C_CUSTKEY"],
        filters=[{"field": "C_MKTSEGMENT", "operator": "eq", "value": injected}],
    ))
    sql, parameters = compile_query_plan(validated)
    normalized, safety = validate_sql_with_evidence(sql)

    assert "?" in normalized
    assert injected not in normalized
    assert parameters == [injected]
    assert safety["status"] == "passed"


@pytest.mark.parametrize("raw", [
    plan(dimensions=["C_ADDRESS"]),
    plan(metrics=[{"operation": "sum", "field": "C_CUSTKEY"}]),
    plan(metrics=[{"operation": "avg", "field": "C_NAME"}]),
    plan(filters=[{"field": "C_MKTSEGMENT", "operator": "gt", "value": "BUILDING"}], dimensions=["C_CUSTKEY"]),
    plan(filters=[{"field": "C_CUSTKEY", "operator": "eq", "value": "1"}], dimensions=["C_CUSTKEY"]),
    plan(metrics=[{"operation": "count"}], sort=[{"field": "C_ACCTBAL", "direction": "DESC"}]),
    plan(sql="SELECT C_CUSTKEY FROM CUSTOMER"),
    {"version": 1, "status": "query", "dimensions": ["C_CUSTKEY"], "table": "OTHER_DB.CUSTOMER"},
    {"version": 1.0, "status": "query", "dimensions": ["C_CUSTKEY"]},
])
def test_invalid_or_untrusted_plan_is_rejected(raw):
    with pytest.raises(PlanValidationError):
        validate_query_plan(raw)


def test_missing_and_excessive_limits_are_enforced_in_trusted_code():
    missing, missing_evidence = validate_query_plan(plan(dimensions=["C_CUSTKEY"]))
    excessive, excessive_evidence = validate_query_plan(plan(dimensions=["C_CUSTKEY"], limit=1000))

    assert missing.limit == 100
    assert excessive.limit == 100
    assert missing_evidence["checks"][-1]["name"] == "result_limit"
    assert "applied by trusted code" in missing_evidence["checks"][-1]["detail"]
    assert "applied by trusted code" in excessive_evidence["checks"][-1]["detail"]


@pytest.mark.parametrize("limit", [0, -1, 1.5, "10"])
def test_invalid_limit_types_and_values_fail_closed(limit):
    with pytest.raises(PlanValidationError):
        validate_query_plan(plan(dimensions=["C_CUSTKEY"], limit=limit))


def test_clarification_and_unsupported_plans_are_non_executable():
    clarification, _ = validate_query_plan(plan(status="clarification", message="Which measure?"))
    unsupported, _ = validate_query_plan(plan(status="unsupported", message="Purchase history is unavailable."))
    assert clarification.status == "clarification"
    assert unsupported.status == "unsupported"
    with pytest.raises(ValueError):
        compile_query_plan(clarification)
