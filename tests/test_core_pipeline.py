"""Core pipeline checks; kept separate from the existing UI/team tests."""
import json
import sys
from pathlib import Path

import pytest
import snowflake.connector as sf_connector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datamind import llm, pipeline, snowflake_client
from datamind.validator import validate_sql, validate_sql_with_evidence


FIELDS = {"answer", "sql", "columns", "rows", "query_id", "assumptions", "warnings", "row_count",
          "validation", "execution", "verification", "clarification"}


def _check(evidence, name):
    return next(item for item in evidence["checks"] if item["name"] == name)


def test_response_has_stable_shape_and_greeting_skips_services(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: pytest.fail("LLM should not be called"))
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
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: pytest.fail("LLM should not be called"))
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
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: {"sql": "SELECT C_CUSTKEY, C_ACCTBAL FROM CUSTOMER ORDER BY C_ACCTBAL DESC LIMIT 1"})
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: (["C_CUSTKEY", "C_ACCTBAL"], [(4, 950.0)], "qid-clear-ranking"))
    result = pipeline.ask("Show me the best customers by account balance")
    assert result["clarification"]["required"] is False
    assert result["query_id"] == "qid-clear-ranking"


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


@pytest.mark.parametrize("sql", [
    "DELETE FROM CUSTOMER",
    "SELECT * FROM CUSTOMER",
    "SELECT C_ADDRESS FROM CUSTOMER",
    "SELECT C_CUSTKEY FROM OTHER_DB.TPCH_SF1.CUSTOMER",
    "SELECT C_CUSTKEY FROM CUSTOMER; DROP TABLE CUSTOMER",
    "SELECT C_CUSTKEY FROM CUSTOMER JOIN ORDERS ON 1=1",
    "SELECT C_CUSTKEY FROM CUSTOMER WHERE RANDOM() > 0",
    "SELECT C_CUSTKEY FROM CUSTOMER LIMIT 0",
    "SELECT C_CUSTKEY FROM CUSTOMER LIMIT -1",
    "SELECT C_CUSTKEY FROM CUSTOMER WHERE C_CUSTKEY IN (SELECT C_CUSTKEY FROM CUSTOMER)",
])
def test_unsafe_sql_is_rejected(sql):
    with pytest.raises(ValueError):
        validate_sql(sql)


def test_pipeline_returns_actual_rows_sql_and_query_id(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: {
        "sql": "SELECT C_CUSTKEY, C_NAME FROM CUSTOMER LIMIT 2",
        "assumptions": "ordered by key",
    })
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: (
        ["C_CUSTKEY", "C_NAME"], [(7, "Alpha"), (9, "Beta")], "qid-actual",
    ))
    result = pipeline.ask("Show two customers")
    assert result["sql"] == "SELECT C_CUSTKEY, C_NAME FROM CUSTOMER LIMIT 2"
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


def test_invalid_generated_sql_is_not_executed_and_is_retained(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: {"sql": "SELECT C_ADDRESS FROM CUSTOMER"})
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: pytest.fail("invalid SQL reached Snowflake"))
    result = pipeline.ask("Show addresses")
    assert result["sql"] == "SELECT C_ADDRESS FROM CUSTOMER"
    assert result["query_id"] is None
    assert "validation failed" in result["answer"]
    assert result["warnings"]
    assert result["validation"]["status"] == "rejected"
    assert _check(result["validation"], "approved_columns")["status"] == "failed"
    assert result["execution"] == {"status": "not_run", "checks": []}
    assert result["verification"] == {"status": "not_run", "checks": []}


def test_empty_result_is_success_without_fabricated_values(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: {"sql": "SELECT C_CUSTKEY FROM CUSTOMER WHERE C_CUSTKEY = -1"})
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: (["C_CUSTKEY"], [], "qid-empty"))
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
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: pytest.fail("Snowflake should not be called"))
    result = pipeline.ask("Count customers")
    assert set(result) == FIELDS
    assert result["query_id"] is None and result["rows"] == []
    assert "failed" in result["answer"]
    assert "TimeoutError" in result["warnings"][0]


def test_database_failure_preserves_sql_and_available_query_id(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: {"sql": "SELECT C_CUSTKEY FROM CUSTOMER"})
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
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: (_ for _ in ()).throw(TimeoutError("sensitive detail")))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: pytest.fail("Snowflake should not be called"))
    result = pipeline.ask("Count customers")
    assert result["validation"] == {"status": "not_run", "checks": []}
    assert result["execution"] == {"status": "not_run", "checks": []}
    assert result["verification"] == {"status": "not_run", "checks": []}
    assert "sensitive detail" not in str(result)


def test_ollama_http_response_is_parsed(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return json.dumps({"message": {"content": json.dumps({"sql": "SELECT C_CUSTKEY FROM CUSTOMER", "assumptions": []})}}).encode()

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda request, timeout: Response())
    result = llm.generate_sql("show keys")
    assert result["sql"] == "SELECT C_CUSTKEY FROM CUSTOMER"


def test_snowflake_client_sets_timeout_and_returns_query_id(monkeypatch):
    calls = []
    class Cursor:
        description = [("C_CUSTKEY",)]
        sfqid = "qid-from-snowflake"
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def execute(self, sql):
            calls.append(sql)
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
    columns, rows, query_id = snowflake_client.execute_sql("SELECT C_CUSTKEY FROM CUSTOMER LIMIT 1")
    assert calls[0] == "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 30"
    assert rows == [(12,)] and query_id == "qid-from-snowflake"
