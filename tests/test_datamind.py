import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from datamind import pipeline
from datamind.validator import validate_sql


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
    monkeypatch.setattr(pipeline.llm, "generate_sql", fail)
    assert pipeline.ask(question)["sql"] is None


def test_ambiguous_question_requests_clarification(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: pytest.fail("unexpected call"))
    result = pipeline.ask("Who are the best customers?")
    assert "define" in result["answer"]
    assert result["warnings"]


def test_pipeline_success_returns_snowflake_evidence(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: {"sql": "SELECT C_CUSTKEY FROM CUSTOMER", "assumptions": ["all customers"]})
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda sql: (["C_CUSTKEY"], [(42,)], "qid-1"))
    result = pipeline.ask("show a customer key")
    assert result["rows"] == [[42]]
    assert result["query_id"] == "qid-1"
    assert result["row_count"] == 1
    assert result["sql"].endswith("LIMIT 100")
    assert "42" in result["answer"]


def test_model_failure_is_honest(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    result = pipeline.ask("show customer keys")
    assert "failed" in result["answer"] or "couldn’t complete" in result["answer"]
    assert result["query_id"] is None
    assert result["rows"] == []


def test_database_failure_preserves_sql_and_does_not_claim_success(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_sql", lambda _: {"sql": "SELECT C_CUSTKEY FROM CUSTOMER"})
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    result = pipeline.ask("show customer keys")
    assert result["sql"] and result["query_id"] is None
    assert "failed" in result["answer"]
    assert result["row_count"] == 0
