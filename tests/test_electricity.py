import csv
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datamind import api, electricity_client, pipeline
from datamind.semantic_query import PlanValidationError, compile_query_plan, validate_query_plan
from datamind.validator import SQLValidationError, validate_sql_with_evidence

def _plan(**values):
    return {
        "version": 1, "status": "query", "dimensions": [], "metrics": [],
        "filters": [], "sort": [], "limit": None, "assumptions": [], **values,
    }


def _independent_rows():
    with (ROOT / "data" / "electricity_mix.csv").open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def test_bundled_subset_provenance_scope_and_independent_count():
    rows = _independent_rows()
    assert len(rows) == 5387
    assert {r["entity"] for r in rows if r["code"] == "IND"} == {"India"}
    assert min(int(r["year"]) for r in rows) == 2000
    assert max(int(r["year"]) for r in rows) == 2025
    assert all(r["renewables_twh"] != "" for r in rows)


def test_electricity_plan_compiles_filters_as_parameters_and_caps_limit():
    plan, evidence = validate_query_plan(_plan(
        dimensions=["ENTITY", "YEAR", "RENEWABLES_TWH"],
        filters=[
            {"field": "ENTITY", "operator": "eq", "value": "India"},
            {"field": "YEAR", "operator": "eq", "value": 2024},
        ], limit=500,
    ), "electricity_mix")
    sql, parameters = compile_query_plan(plan, "electricity_mix")
    normalized, sql_evidence = validate_sql_with_evidence(sql, "electricity_mix")
    assert evidence["status"] == "passed"
    assert sql_evidence["status"] == "passed"
    assert "FROM electricity_mix" in normalized
    assert "ENTITY = ? AND YEAR = ?" in normalized
    assert "LIMIT 100" in normalized
    assert parameters == ["India", 2024]
    assert "India" not in normalized


def test_model_year_numeric_string_is_normalized_but_malformed_text_is_rejected():
    raw = _plan(dimensions=["YEAR"], filters=[{
        "field": "YEAR", "operator": "eq", "value": "2024",
    }], limit=1)
    plan, evidence = validate_query_plan(raw, "electricity_mix")
    sql, parameters = compile_query_plan(plan, "electricity_mix")
    assert plan.filters[0].value == 2024
    assert type(plan.filters[0].value) is int
    assert parameters == [2024]
    assert "YEAR = ?" in sql
    assert {check["name"]: check["status"] for check in evidence["checks"]}["numeric_filter_normalization"] == "passed"

    raw["filters"][0]["value"] = "2024 OR 1=1"
    with pytest.raises(PlanValidationError):
        validate_query_plan(raw, "electricity_mix")


def test_plan_rejects_fields_and_operators_outside_electricity_catalog():
    with pytest.raises(PlanValidationError):
        validate_query_plan(_plan(dimensions=["C_ACCTBAL"]), "electricity_mix")
    with pytest.raises(PlanValidationError):
        validate_query_plan(_plan(filters=[{
            "field": "ENTITY", "operator": "gt", "value": "India",
        }]), "electricity_mix")
    with pytest.raises(PlanValidationError):
        validate_query_plan(_plan(metrics=[{"operation": "avg", "field": "YEAR"}]), "electricity_mix")
    with pytest.raises(PlanValidationError):
        validate_query_plan({"version": 1, "status": "query", "sql": "DROP TABLE"}, "electricity_mix")


def test_sql_validator_keeps_electricity_table_and_field_boundary():
    for sql in (
        "SELECT ENTITY FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER LIMIT 1",
        "SELECT UNKNOWN FROM electricity_mix LIMIT 1",
        "SELECT ENTITY FROM other_table LIMIT 1",
        "SELECT ENTITY FROM electricity_mix; DELETE FROM electricity_mix",
        "SELECT RANDOM() FROM electricity_mix LIMIT 1",
    ):
        with pytest.raises(SQLValidationError):
            validate_sql_with_evidence(sql, "electricity_mix")


def test_local_executor_preserves_null_and_uses_sql_count_semantics(tmp_path, monkeypatch):
    sample = tmp_path / "electricity.csv"
    sample.write_text(
        "entity,code,year,renewables_twh\nA,AAA,2020,10\nB,BBB,2020,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(electricity_client, "DATA_PATH", sample)
    columns, rows, query_id = electricity_client.execute_sql(
        "SELECT COUNT(*) AS ROWS, COUNT(RENEWABLES_TWH) AS VALUES_PRESENT, "
        "AVG(RENEWABLES_TWH) AS MEAN FROM electricity_mix LIMIT 100"
    )
    assert columns == ["ROWS", "VALUES_PRESENT", "MEAN"]
    assert rows == [(2, 1, 10.0)]
    assert query_id is None


def test_local_executor_returns_empty_results_and_caps_rows():
    columns, rows, query_id = electricity_client.execute_sql(
        "SELECT ENTITY FROM electricity_mix WHERE ENTITY = ? LIMIT 100", ["not a country"]
    )
    assert columns == ["ENTITY"] and rows == []
    assert query_id is None
    with pytest.raises(SQLValidationError):
        electricity_client.execute_sql("SELECT ENTITY FROM electricity_mix LIMIT -1")


def test_http_api_executes_real_local_query_with_independent_expected_value(monkeypatch):
    values = [float(row["renewables_twh"]) for row in _independent_rows()
              if row["entity"] == "India" and int(row["year"]) == 2024]
    assert len(values) == 1
    expected = values[0]
    generated = []

    def generate(question, dataset_id):
        generated.append((question, dataset_id))
        return _plan(
            dimensions=["ENTITY", "YEAR", "RENEWABLES_TWH"],
            filters=[
                {"field": "ENTITY", "operator": "eq", "value": "India"},
                {"field": "YEAR", "operator": "eq", "value": 2024},
            ], limit=1,
        )

    monkeypatch.setattr(pipeline.llm, "generate_plan", generate)
    response = TestClient(api.app).post("/api/query", json={
        "question": "Show renewable electricity generation in India in 2024",
        "dataset_id": "electricity_mix",
    })
    assert response.status_code == 200
    result = response.json()
    assert generated == [("Show renewable electricity generation in India in 2024", "electricity_mix")]
    assert result["dataset_id"] == "electricity_mix"
    assert result["columns"] == ["ENTITY", "YEAR", "RENEWABLES_TWH"]
    assert result["rows"] == [["India", 2024, expected]]
    assert result["row_count"] == 1
    assert result["sql"] and "FROM electricity_mix" in result["sql"]
    assert result["sql_parameters"] == ["India", 2024]
    assert result["query_id"] is None
    assert result["execution"]["engine"] == "local dataset"
    assert result["execution"]["status"] == "succeeded"
    assert result["verification"]["status"] == "passed"


def test_live_question_accepts_gemmas_string_year_as_a_typed_bound_integer(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda question, dataset_id: _plan(
        dimensions=["ENTITY", "YEAR", "RENEWABLES_TWH"],
        filters=[
            {"field": "ENTITY", "operator": "eq", "value": "India"},
            {"field": "YEAR", "operator": "eq", "value": "2024"},
        ], limit=1,
    ))
    result = pipeline.ask("What was renewable electricity generation in India in 2024?", "electricity_mix")
    assert result["outcome"] == "success"
    assert result["sql_parameters"] == ["India", 2024]
    assert type(result["sql_parameters"][1]) is int
    assert result["rows"] == [["India", 2024, 403.39]]
    normalization = next(check for check in result["plan_validation"]["checks"]
                         if check["name"] == "numeric_filter_normalization")
    assert normalization["status"] == "passed"


def test_api_defaults_to_tpch_and_lists_both_datasets(monkeypatch):
    seen = []
    monkeypatch.setattr(api, "ask", lambda question: seen.append(question) or {
        "answer": "ok", "sql": None, "columns": [], "rows": [], "query_id": None,
        "assumptions": [], "warnings": [], "row_count": 0,
    })
    response = TestClient(api.app).post("/api/query", json={"question": "hello"})
    assert response.status_code == 200
    assert response.json()["dataset_id"] == "tpch_customer"
    assert seen == ["hello"]
    catalog = TestClient(api.app).get("/api/datasets").json()
    assert catalog["default_dataset_id"] == "tpch_customer"
    assert {item["id"] for item in catalog["datasets"]} == {"tpch_customer", "electricity_mix"}


def test_unknown_dataset_is_rejected_before_model_or_database(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda *args, **kwargs: pytest.fail("model called"))
    monkeypatch.setattr(electricity_client, "execute_sql", lambda *args: pytest.fail("local DB called"))
    result = pipeline.ask("count rows", "unknown")
    assert result["dataset_id"] == "unknown"
    assert result["outcome"] == "unsupported"
    assert result["sql"] is None and result["query_id"] is None


def test_model_plan_cannot_drop_explicit_country_and_year_filters(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda question, dataset_id: _plan(
        dimensions=["ENTITY", "YEAR", "RENEWABLES_TWH"], limit=100,
    ))
    monkeypatch.setattr(electricity_client, "execute_sql", lambda *args: pytest.fail("unfiltered query reached local DB"))
    result = pipeline.ask("What was renewable electricity generation in India in 2024?", "electricity_mix")
    assert result["outcome"] == "rejected"
    assert result["sql"] is None and result["query_id"] is None
    assert result["plan_validation"]["status"] == "rejected"
    assert result["plan_validation"]["checks"][-1]["name"] == "explicit_question_scope"
    assert result["plan_validation"]["checks"][-1]["status"] == "failed"
    assert result["execution"]["status"] == "not_run"


def test_explicit_year_range_requires_both_bounds(monkeypatch):
    plan = _plan(
        dimensions=["YEAR"], metrics=[{"operation": "sum", "field": "RENEWABLES_TWH"}],
        filters=[
            {"field": "ENTITY", "operator": "eq", "value": "India"},
            {"field": "YEAR", "operator": "gte", "value": 2023},
            {"field": "YEAR", "operator": "lte", "value": 2025},
        ], sort=[{"field": "YEAR", "direction": "ASC"}], limit=100,
    )
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda question, dataset_id: plan)
    result = pipeline.ask("How did renewable generation change in India from 2023 through 2025?", "electricity_mix")
    assert result["outcome"] == "success"
    assert result["rows"] == [[2023, 369.97], [2024, 403.39], [2025, 500.98]]
    assert result["plan_validation"]["checks"][-1]["status"] == "passed"


def test_multiple_named_countries_are_rejected_instead_of_widening_or_anding(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda question, dataset_id: _plan(
        dimensions=["ENTITY", "RENEWABLES_TWH"], filters=[
            {"field": "ENTITY", "operator": "eq", "value": "India"},
        ], limit=10,
    ))
    monkeypatch.setattr(electricity_client, "execute_sql", lambda *args: pytest.fail("partial country comparison executed"))
    result = pipeline.ask("Compare India and China renewable generation in 2024", "electricity_mix")
    assert result["outcome"] == "rejected"
    assert result["sql"] is None
    assert result["plan_validation"]["checks"][-1]["status"] == "failed"


def test_unnamed_country_ranking_cannot_invent_a_country_or_omit_sort(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda question, dataset_id: _plan(
        dimensions=["ENTITY", "RENEWABLES_TWH"], filters=[
            {"field": "YEAR", "operator": "eq", "value": 2025},
            {"field": "ENTITY", "operator": "eq", "value": "China"},
        ], limit=100,
    ))
    monkeypatch.setattr(electricity_client, "execute_sql", lambda *args: pytest.fail("invented-country query executed"))
    result = pipeline.ask("Which countries had the most electricity generation in 2025?", "electricity_mix")
    assert result["outcome"] == "rejected"
    assert result["sql"] is None
    assert "country filter that was not stated" in result["warnings"][0]


def test_deterministic_country_ranking_uses_typed_plan_and_actual_local_rows(monkeypatch):
    rows = _independent_rows()
    expected = sorted([[row["entity"], float(row["renewables_twh"])] for row in rows if row["year"] == "2025"],
                      key=lambda row: row[1], reverse=True)[:3]
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda *args, **kwargs: pytest.fail("this explicit intent uses the deterministic typed-plan rule"))
    result = pipeline.ask("Rank top 3 countries by renewable electricity generation for 2025, highest first.", "electricity_mix")
    assert result["plan_source"] == "deterministic_rule"
    assert result["query_plan"]["filters"] == [{"field": "YEAR", "operator": "eq", "value": 2025}]
    assert result["query_plan"]["sort"] == [{"field": "RENEWABLES_TWH", "operation": None, "direction": "DESC"}]
    assert result["sql_parameters"] == [2025]
    assert result["rows"] == expected
    assert result["row_count"] == 3
    assert result["query_id"] is None
    assert result["validation"]["status"] == "passed"
    assert result["execution"]["status"] == "succeeded"
    assert result["verification"]["status"] == "passed"


def test_country_generated_most_wording_uses_same_supported_typed_plan(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda *args, **kwargs: pytest.fail("recognized exact ranking should not need an LLM guess"))
    result = pipeline.ask("Which countries generated the most renewable electricity in 2025?", "electricity_mix")
    assert result["plan_source"] == "deterministic_rule"
    assert result["query_plan"]["filters"] == [{"field": "YEAR", "operator": "eq", "value": 2025}]
    assert result["query_plan"]["sort"][0]["field"] == "RENEWABLES_TWH"
    assert result["query_plan"]["sort"][0]["direction"] == "DESC"
    assert result["rows"][:3] == [["China", 3920.47], ["United States", 1158.8], ["Brazil", 649.97]]


def test_country_ranking_without_a_year_requests_clarification(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda *args, **kwargs: pytest.fail("ambiguous year must clarify before model planning"))
    monkeypatch.setattr(electricity_client, "execute_sql", lambda *args: pytest.fail("ambiguous ranking reached SQLite"))
    result = pipeline.ask("Which countries generate the most renewable electricity?", "electricity_mix")
    assert result["outcome"] == "clarification"
    assert result["clarification"]["required"] is True
    assert "2000–2025" in result["answer"]
    assert result["sql"] is None and result["query_id"] is None
    assert result["plan_source"] == "not_run"
    assert result["validation"]["status"] == "not_run"
    assert result["execution"]["status"] == "not_run"

