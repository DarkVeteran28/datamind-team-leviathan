import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from datamind import pipeline
from datamind.validator import validate_sql


def _plan(**overrides):
    plan = {"version": 1, "status": "query", "dimensions": [], "metrics": [], "filters": [],
            "sort": [], "limit": None, "assumptions": []}
    plan.update(overrides)
    return plan


def test_valid_query_adds_limit_and_caps_limit():
    assert "LIMIT 100" in validate_sql("SELECT C_CUSTKEY FROM CUSTOMER")
    assert "LIMIT 100" in validate_sql("SELECT C_CUSTKEY FROM CUSTOMER LIMIT 500")


@pytest.mark.parametrize("sql", [
    "DELETE FROM CUSTOMER", "SELECT * FROM CUSTOMER", "SELECT C_ADDRESS FROM CUSTOMER",
    "SELECT C_CUSTKEY FROM OTHER.CUSTOMER", "SELECT C_CUSTKEY FROM CUSTOMER; DROP TABLE CUSTOMER",
    "SELECT C_CUSTKEY FROM CUSTOMER JOIN ORDERS ON 1=1",
    "SELECT C_CUSTKEY FROM CUSTOMER WHERE RANDOM() > 0.5",
])
def test_invalid_or_malicious_sql_rejected(sql):
    with pytest.raises(ValueError):
        validate_sql(sql)


@pytest.mark.parametrize("question", ["hello", "Who are you?", "What can you do?"])
def test_non_data_intents_do_not_query(question, monkeypatch):
    def fail(_):
        raise AssertionError("model should not run")
    monkeypatch.setattr(pipeline.llm, "generate_plan", fail)
    assert pipeline.ask(question)["sql"] is None


def test_ambiguous_question_requests_clarification(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: pytest.fail("unexpected call"))
    result = pipeline.ask("Who are the best customers?")
    assert "define" in result["answer"]
    assert result["warnings"]


def test_pipeline_success_returns_snowflake_evidence(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: _plan(dimensions=["C_CUSTKEY"], assumptions=["all customers"]))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda *args: (["C_CUSTKEY"], [(42,)], "qid-1"))
    result = pipeline.ask("show a customer key")
    assert result["rows"] == [[42]]
    assert result["query_id"] == "qid-1"
    assert result["row_count"] == 1
    assert result["sql"].endswith("LIMIT 100")
    assert "42" in result["answer"]


def test_model_failure_is_honest(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    result = pipeline.ask("show customer keys")
    assert "failed" in result["answer"] or "couldn’t complete" in result["answer"]
    assert result["query_id"] is None
    assert result["rows"] == []


def test_database_failure_preserves_sql_and_does_not_claim_success(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: _plan(dimensions=["C_CUSTKEY"]))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    result = pipeline.ask("show customer keys")
    assert result["sql"] and result["query_id"] is None
    assert "failed" in result["answer"]
    assert result["row_count"] == 0


@pytest.mark.parametrize(("question", "sql", "columns", "rows", "evidence"), [
    ("How many customers are there?", "SELECT COUNT(*) AS CUSTOMER_COUNT FROM CUSTOMER",
     ["CUSTOMER_COUNT"], [(25,)], "CUSTOMER_COUNT=25"),
    ("Show a customer in BUILDING", "SELECT C_CUSTKEY, C_MKTSEGMENT FROM CUSTOMER WHERE C_MKTSEGMENT = 'BUILDING' LIMIT 1",
     ["C_CUSTKEY", "C_MKTSEGMENT"], [(7, "BUILDING")], "C_MKTSEGMENT=BUILDING"),
])
def test_aggregation_and_filter_answers_use_returned_values(monkeypatch, question, sql, columns, rows, evidence):
    if "COUNT(*)" in sql:
        test_plan = _plan(metrics=[{"operation": "count"}])
    else:
        test_plan = _plan(dimensions=["C_CUSTKEY", "C_MKTSEGMENT"], filters=[
            {"field": "C_MKTSEGMENT", "operator": "eq", "value": "BUILDING"}], limit=1)
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: test_plan)
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda *args: (columns, rows, "qid-evidence"))
    result = pipeline.ask(question)
    assert evidence in result["answer"]
    assert result["rows"] == [list(row) for row in rows]
    assert result["query_id"] == "qid-evidence"


def test_empty_result_is_reported_without_invented_values(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _: _plan(dimensions=["C_CUSTKEY"], filters=[
        {"field": "C_CUSTKEY", "operator": "eq", "value": -1}]))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda *args: (["C_CUSTKEY"], [], "qid-empty"))
    result = pipeline.ask("Find this customer key")
    assert result["answer"] == "The query completed successfully and returned no rows."
    assert result["rows"] == []
    assert result["row_count"] == 0


def test_mocked_evaluation_corpus():
    from eval.run_evaluation import run_case
    import json
    from pathlib import Path

    cases = json.loads((Path(__file__).parents[1] / "eval" / "cases.json").read_text())
    assert all(not run_case(case) for case in cases)
