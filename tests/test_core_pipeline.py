"""Core pipeline checks; kept separate from the existing UI/team tests."""
import json
import sys
from pathlib import Path

import pytest
import snowflake.connector as sf_connector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datamind import llm, pipeline, snowflake_client
from datamind.semantic_query import QueryPlan
from datamind.validator import validate_sql, validate_sql_with_evidence


FIELDS = {"answer", "dataset_id", "plan_source", "sql", "columns", "rows", "query_id", "assumptions", "warnings", "row_count",
          "validation", "execution", "verification", "clarification", "sql_parameters",
          "query_plan", "plan_validation", "outcome", "intent_classification", "missing_concepts", "capability_match"}


def _check(evidence, name):
    return next(item for item in evidence["checks"] if item["name"] == name)


def _plan(**overrides):
    plan = {"version": 1, "status": "query", "dimensions": [], "metrics": [], "filters": [],
            "sort": [], "limit": None, "assumptions": []}
    plan.update(overrides)
    return plan


def test_response_has_stable_shape_and_greeting_skips_services(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: pytest.fail("LLM should not be called"))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: pytest.fail("Snowflake should not be called"))
    result = pipeline.ask("Hello")
    assert set(result) == FIELDS
    assert result["sql"] is None
    assert result["query_id"] is None


@pytest.mark.parametrize("question", [
    "Show me the best customers",
    "Show me the top customers",
    "Show me the top customers in the BUILDING segment",
    "Show me the top customers by spending frequency",
])
def test_ambiguous_data_request_clarifies_without_query(monkeypatch, question):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: pytest.fail("LLM should not be called"))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: pytest.fail("Snowflake should not be called"))
    result = pipeline.ask(question)
    assert result["clarification"]["required"] is True
    assert result["clarification"]["question"] == result["answer"]
    assert [option["column"] for option in result["clarification"]["options"]] == ["C_ACCTBAL", "C_NAME", "C_CUSTKEY"]
    assert "frequency" not in result["answer"].lower()
    assert result["sql"] is None and result["query_id"] is None
    assert result["validation"] == {"status": "not_run", "checks": []}
    assert result["execution"] == {"status": "not_run", "checks": []}
    assert result["verification"] == {"status": "not_run", "checks": []}
    assert "Clarification required before querying." in result["warnings"]


def test_clear_account_balance_ranking_is_not_clarified(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: _plan(
        dimensions=["C_CUSTKEY", "C_ACCTBAL"], sort=[{"field": "C_ACCTBAL", "direction": "DESC"}], limit=1))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: (["C_CUSTKEY", "C_ACCTBAL"], [(4, 950.0)], "qid-clear-ranking"))
    result = pipeline.ask("Show me the best customers by account balance")
    assert result["clarification"]["required"] is False
    assert result["query_id"] == "qid-clear-ranking"


def test_exact_top_five_balance_question_compiles_and_executes_validated_plan(monkeypatch):
    question = "Show me top 5 customer with highest account balance"
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: _plan(
        dimensions=["C_CUSTKEY", "C_NAME", "C_ACCTBAL"],
        sort=[{"field": "C_ACCTBAL", "direction": "DESC"}], limit=5,
    ))
    calls = []

    def execute(sql, parameters=None):
        calls.append((sql, parameters))
        return ["C_CUSTKEY", "C_NAME", "C_ACCTBAL"], [(4, "Acme", 950.0)], "qid-top-five"

    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", execute)
    result = pipeline.ask(question)

    assert result["outcome"] == "success"
    assert result["plan_validation"]["status"] == "passed"
    assert result["validation"]["status"] == "passed"
    assert "ORDER BY C_ACCTBAL DESC LIMIT 5" in result["sql"]
    assert calls == [(result["sql"], None)]
    assert result["rows"] == [[4, "Acme", 950.0]]
    assert result["query_id"] == "qid-top-five"


def test_plan_validation_warning_reports_safe_failure_location_without_execution(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: _plan(
        dimensions=["C_CUSTKEY", "C_ACCTBAL"],
        sort=[{"field": "C_ACCTBAL", "direction": "DESCENDING"}], limit=5,
    ))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda *_: pytest.fail("invalid plan reached Snowflake"))
    result = pipeline.ask("Show me top 5 customer with highest account balance")

    assert result["outcome"] == "rejected"
    assert result["sql"] is None
    assert result["execution"]["status"] == "not_run"
    assert "sort[0].direction" in result["warnings"][0]
    assert "DESCENDING" not in result["warnings"][0]


@pytest.mark.parametrize("sql", [
    "SELECT C_CUSTKEY FROM CUSTOMER",
    "SELECT COUNT(*) AS N FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER",
    "SELECT C_ACCTBAL FROM CUSTOMER WHERE C_MKTSEGMENT = 'BUILDING' ORDER BY C_ACCTBAL DESC LIMIT 5",
])
def test_approved_selects_validate_and_are_limited(sql):
    normalized = validate_sql(sql)
    assert "LIMIT" in normalized.upper()
    assert "100" in normalized or "5" in normalized


def test_validation_evidence_reports_actual_limit_cap():
    normalized, evidence = validate_sql_with_evidence("SELECT C_CUSTKEY FROM CUSTOMER LIMIT 500")
    assert normalized.endswith("LIMIT 100")
    assert evidence["status"] == "passed"
    assert _check(evidence, "row_limit") == {
        "name": "row_limit", "status": "passed",
        "detail": "Requested LIMIT 500 was capped at 100.",
    }


def test_validator_allows_and_only_for_safe_where_filter_comparisons():
    sql, evidence = validate_sql_with_evidence(
        "SELECT C_CUSTKEY FROM CUSTOMER WHERE C_MKTSEGMENT = 'BUILDING' AND C_ACCTBAL > 0 LIMIT 5"
    )

    assert "AND" in sql
    assert _check(evidence, "logical_operators")["status"] == "passed"


@pytest.mark.parametrize("sql", [
    "SELECT C_CUSTKEY AND C_ACCTBAL FROM CUSTOMER LIMIT 5",
    "SELECT C_CUSTKEY FROM CUSTOMER WHERE C_CUSTKEY = 1 OR C_CUSTKEY = 2 LIMIT 5",
    "SELECT C_CUSTKEY FROM CUSTOMER WHERE NOT C_CUSTKEY = 1 LIMIT 5",
    "SELECT C_CUSTKEY FROM CUSTOMER WHERE C_CUSTKEY = 1 AND C_NAME LIKE 'A%' LIMIT 5",
    "SELECT C_CUSTKEY FROM CUSTOMER HAVING C_CUSTKEY = 1 AND C_ACCTBAL > 0 LIMIT 5",
])
def test_validator_rejects_logical_operators_outside_safe_where_conjunctions(sql):
    with pytest.raises(ValueError):
        validate_sql(sql)


@pytest.mark.parametrize("sql", [
    "DELETE FROM CUSTOMER",
    "SELECT * FROM CUSTOMER",
    "SELECT C_ADDRESS FROM CUSTOMER",
    "SELECT C_CUSTKEY FROM OTHER_DB.TPCH_SF1.CUSTOMER",
    "SELECT C_CUSTKEY FROM CUSTOMER; DROP TABLE CUSTOMER",
    "SELECT C_CUSTKEY FROM CUSTOMER JOIN ORDERS ON 1=1",
    "SELECT C_CUSTKEY FROM CUSTOMER WHERE RANDOM() > 0",
    "SELECT C_CUSTKEY FROM CUSTOMER WHERE CURRENT_USER() = 'x'",
    "SELECT C_CUSTKEY FROM CUSTOMER LIMIT 0",
    "SELECT C_CUSTKEY FROM CUSTOMER LIMIT -1",
    "SELECT C_CUSTKEY FROM CUSTOMER WHERE C_CUSTKEY IN (SELECT C_CUSTKEY FROM CUSTOMER)",
    "SELECT ? FROM CUSTOMER",
    "SELECT C_CUSTKEY FROM CUSTOMER WHERE C_CUSTKEY IN (?)",
])
def test_unsafe_sql_is_rejected(sql):
    with pytest.raises(ValueError):
        validate_sql(sql)


def test_pipeline_returns_actual_rows_sql_and_query_id(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: _plan(
        dimensions=["C_CUSTKEY", "C_NAME"], sort=[{"field": "C_CUSTKEY", "direction": "ASC"}],
        limit=2, assumptions=["ordered by key"]))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: (
        ["C_CUSTKEY", "C_NAME"], [(7, "Alpha"), (9, "Beta")], "qid-actual",
    ))
    result = pipeline.ask("Show two customers")
    assert "SELECT C_CUSTKEY, C_NAME FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER" in result["sql"]
    assert "ORDER BY C_CUSTKEY ASC LIMIT 2" in result["sql"]
    assert result["columns"] == ["C_CUSTKEY", "C_NAME"]
    assert result["rows"] == [[7, "Alpha"], [9, "Beta"]]
    assert result["query_id"] == "qid-actual"
    assert result["row_count"] == 2
    assert "C_CUSTKEY=7" in result["answer"] and "C_NAME=Alpha" in result["answer"]
    assert result["assumptions"] == ["ordered by key"]
    assert result["validation"]["status"] == "passed"
    assert _check(result["validation"], "single_statement")["status"] == "passed"
    assert _check(result["validation"], "approved_table")["detail"] == "Only SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER is referenced."
    assert _check(result["validation"], "approved_columns")["status"] == "passed"
    assert _check(result["validation"], "row_limit")["detail"] == "LIMIT 2 is within the 100-row maximum."
    assert result["execution"]["status"] == "succeeded"
    assert result["verification"]["status"] == "passed"
    assert _check(result["verification"], "returned_row_count")["status"] == "passed"
    assert _check(result["verification"], "answer_row_count")["status"] == "passed"
    assert _check(result["verification"], "displayed_samples")["status"] == "passed"
    assert _check(result["verification"], "semantic_correctness")["status"] == "not_run"


def test_pipeline_passes_filter_values_separately_from_compiled_sql(monkeypatch):
    value = "BUILDING' OR 1=1 --"
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: _plan(
        dimensions=["C_CUSTKEY"],
        filters=[{"field": "C_MKTSEGMENT", "operator": "eq", "value": value}],
    ))
    calls = []

    def execute(sql, parameters):
        calls.append((sql, parameters))
        return ["C_CUSTKEY"], [(4,)], "qid-bound"

    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", execute)
    result = pipeline.ask("Find this customer")

    assert "C_MKTSEGMENT = ?" in result["sql"]
    assert value not in result["sql"]
    assert result["sql_parameters"] == [value]
    assert calls == [(result["sql"], [value])]
    assert result["query_id"] == "qid-bound"
    assert _check(result["validation"], "parameter_binding")["status"] == "passed"


def test_model_supplied_sql_field_is_rejected_before_compilation(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: {"version": 1, "status": "query", "sql": "SELECT C_ADDRESS FROM CUSTOMER"})
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: pytest.fail("invalid SQL reached Snowflake"))
    result = pipeline.ask("Show customer names")
    assert result["sql"] is None
    assert result["query_id"] is None
    assert "rejected before SQL compilation" in result["answer"]
    assert result["warnings"]
    assert result["plan_validation"]["status"] == "rejected"
    assert _check(result["plan_validation"], "plan_schema")["status"] == "failed"
    assert result["validation"] == {"status": "not_run", "checks": []}
    assert result["execution"] == {"status": "not_run", "checks": []}
    assert result["verification"] == {"status": "not_run", "checks": []}


def test_empty_result_is_success_without_fabricated_values(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: _plan(
        dimensions=["C_CUSTKEY"], filters=[{"field": "C_CUSTKEY", "operator": "eq", "value": -1}]))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda *args: (["C_CUSTKEY"], [], "qid-empty"))
    result = pipeline.ask("Find key minus one")
    assert result["answer"] == "The query completed successfully and returned no rows."
    assert result["rows"] == [] and result["row_count"] == 0
    assert result["query_id"] == "qid-empty"
    assert result["execution"]["status"] == "succeeded"
    assert result["validation"]["status"] == "passed"
    assert result["verification"]["status"] == "passed"
    assert _check(result["verification"], "empty_result_description")["status"] == "passed"
    assert _check(result["verification"], "displayed_samples")["status"] == "skipped"


def test_verifier_detects_row_count_mismatch():
    evidence = pipeline._verify_answer("Snowflake returned 2 rows: C_CUSTKEY=1.", ["C_CUSTKEY"], [[1]], 2)
    assert evidence["status"] == "failed"
    assert _check(evidence, "returned_row_count")["status"] == "failed"
    assert _check(evidence, "answer_row_count")["status"] == "failed"


def test_verifier_detects_sample_value_mismatch():
    evidence = pipeline._verify_answer("Snowflake returned 1 row: C_CUSTKEY=999.", ["C_CUSTKEY"], [[1]], 1)
    assert evidence["status"] == "failed"
    assert _check(evidence, "displayed_samples")["status"] == "failed"


def test_verifier_marks_unavailable_checks_honestly():
    evidence = pipeline._verify_answer("Snowflake returned 1 row: C_CUSTKEY=1.", ["C_CUSTKEY"], [[1]], 1)
    assert _check(evidence, "ranking_order")["status"] == "skipped"
    assert _check(evidence, "semantic_correctness")["status"] == "not_run"


def test_llm_failure_is_structured_and_does_not_call_snowflake(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: pytest.fail("Snowflake should not be called"))
    result = pipeline.ask("Count customers")
    assert set(result) == FIELDS
    assert result["query_id"] is None and result["rows"] == []
    assert "failed" in result["answer"]
    assert "TimeoutError" in result["warnings"][0]


def test_database_failure_preserves_sql_and_available_query_id(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: _plan(dimensions=["C_CUSTKEY"]))
    def failed(_):
        raise snowflake_client.SnowflakeExecutionError("qid-failed")
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", failed)
    result = pipeline.ask("Show customer keys")
    assert result["sql"] and result["query_id"] == "qid-failed"
    assert result["rows"] == [] and result["row_count"] == 0
    assert "query failed" in result["answer"]
    assert result["validation"]["status"] == "passed"
    assert result["execution"]["status"] == "failed"
    assert result["verification"]["status"] == "not_run"


def test_llm_failure_does_not_claim_validation_execution_or_verification(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: (_ for _ in ()).throw(TimeoutError("sensitive detail")))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: pytest.fail("Snowflake should not be called"))
    result = pipeline.ask("Count customers")
    assert result["validation"] == {"status": "not_run", "checks": []}
    assert result["execution"] == {"status": "not_run", "checks": []}
    assert result["verification"] == {"status": "not_run", "checks": []}
    assert "sensitive detail" not in str(result)


def test_ollama_http_response_is_parsed(monkeypatch):
    requests = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return json.dumps({"message": {"content": json.dumps(_plan(dimensions=["C_CUSTKEY"]))}}).encode()

    def open_request(request, timeout):
        requests.append((json.loads(request.data), timeout))
        return Response()

    monkeypatch.setattr(llm.urllib.request, "urlopen", open_request)
    result = llm.generate_plan("show keys")
    assert result["dimensions"] == ["C_CUSTKEY"]
    assert requests[0][0]["format"] == QueryPlan.model_json_schema()
    assert requests[0][1] == 120
    assert "top N individual customers" in requests[0][0]["messages"][0]["content"]


def test_snowflake_client_sets_timeout_and_returns_query_id(monkeypatch):
    calls = []
    class Cursor:
        description = [("C_CUSTKEY",)]
        sfqid = "qid-from-snowflake"
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def execute(self, sql, parameters=None):
            calls.append((sql, parameters))
        def fetchmany(self, count):
            assert count == 101
            return [(12,)]
    class Connection:
        def cursor(self):
            return Cursor()
        def close(self):
            pass
    monkeypatch.setattr(sf_connector, "connect", lambda **_: Connection())
    for key, value in {
        "SNOWFLAKE_ACCOUNT": "test-account", "SNOWFLAKE_USER": "test-user",
        "SNOWFLAKE_PASSWORD": "never-print", "SNOWFLAKE_WAREHOUSE": "test-warehouse",
    }.items():
        monkeypatch.setenv(key, value)
    columns, rows, query_id = snowflake_client.execute_sql("SELECT C_CUSTKEY FROM CUSTOMER WHERE C_CUSTKEY = ? LIMIT 1", [12])
    assert calls[0][0] == "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 30"
    assert calls[2] == ("SELECT C_CUSTKEY FROM CUSTOMER WHERE C_CUSTKEY = %s LIMIT 1", (12,))
    assert rows == [(12,)] and query_id == "qid-from-snowflake"
