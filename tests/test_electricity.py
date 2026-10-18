import csv
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datamind import api, pipeline, snowflake_client
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


def _mock_snowflake(monkeypatch, columns, rows, query_id="mock-snowflake-query-id"):
    calls = []

    def execute(sql, parameters=None, dataset_id="tpch_customer"):
        calls.append((sql, list(parameters or []), dataset_id))
        return columns, rows, query_id

    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", execute)
    return calls


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
    assert "FROM DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX" in normalized
    assert "ENTITY = ? AND YEAR = ?" in normalized
    assert "LIMIT 100" in normalized
    assert parameters == ["India", 2024]
    assert "India" not in normalized


def test_tpch_compiler_keeps_existing_fully_qualified_customer_table():
    plan, _ = validate_query_plan(_plan(dimensions=["C_CUSTKEY"], limit=2), "tpch_customer")
    sql, parameters = compile_query_plan(plan, "tpch_customer")
    normalized, evidence = validate_sql_with_evidence(sql, "tpch_customer")
    assert "FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER" in normalized
    assert parameters == []
    assert evidence["status"] == "passed"


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


def test_sql_validator_requires_electricity_snowflake_table_and_field_boundary():
    for sql in (
        "SELECT ENTITY FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER LIMIT 1",
        "SELECT UNKNOWN FROM DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX LIMIT 1",
        "SELECT ENTITY FROM other_table LIMIT 1",
        "SELECT ENTITY FROM electricity_mix LIMIT 1",
        "SELECT ENTITY FROM DATAMIND_DB.OTHER.ELECTRICITY_MIX LIMIT 1",
        "SELECT ENTITY FROM DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX; DELETE FROM DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX",
        "SELECT RANDOM() FROM DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX LIMIT 1",
    ):
        with pytest.raises(SQLValidationError):
            validate_sql_with_evidence(sql, "electricity_mix")


def test_electricity_snowflake_client_uses_registered_database_schema_and_qmark_binding(monkeypatch):
    import sys
    from types import SimpleNamespace

    calls = {}

    class Cursor:
        sfqid = "electricity-qid"
        description = [("ENTITY",), ("YEAR",), ("RENEWABLES_TWH",)]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, parameters=None):
            calls.setdefault("executions", []).append((sql, parameters))

        def fetchmany(self, size):
            calls["fetch_size"] = size
            return [("India", 2024, 403.39)]

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            calls["closed"] = True

    def connect(**kwargs):
        calls["connect"] = kwargs
        return Connection()

    fake_connector = SimpleNamespace(connect=connect)
    monkeypatch.setitem(sys.modules, "snowflake", SimpleNamespace(connector=fake_connector))
    monkeypatch.setitem(sys.modules, "snowflake.connector", fake_connector)
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "unit-test-account")
    monkeypatch.setenv("SNOWFLAKE_USER", "unit-test-user")
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "unit-test-password")
    monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "unit-test-warehouse")

    sql = "SELECT ENTITY, YEAR, RENEWABLES_TWH FROM DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX WHERE ENTITY = ? AND YEAR = ? LIMIT 1"
    columns, rows, query_id = snowflake_client.execute_sql(sql, ["India", 2024], dataset_id="electricity_mix")

    assert calls["connect"]["database"] == "DATAMIND_DB"
    assert calls["connect"]["schema"] == "ANALYTICS"
    assert calls["executions"][-1] == (
        "SELECT ENTITY, YEAR, RENEWABLES_TWH FROM DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX WHERE ENTITY = %s AND YEAR = %s LIMIT 1",
        ("India", 2024),
    )
    assert columns == ["ENTITY", "YEAR", "RENEWABLES_TWH"]
    assert rows == [("India", 2024, 403.39)]
    assert query_id == "electricity-qid"
    assert calls["fetch_size"] == 101 and calls["closed"] is True


def test_api_routes_electricity_plan_to_snowflake_and_returns_actual_query_id(monkeypatch):
    values = [float(row["renewables_twh"]) for row in _independent_rows()
              if row["entity"] == "India" and int(row["year"]) == 2024]
    assert len(values) == 1
    expected = values[0]
    db_calls = _mock_snowflake(
        monkeypatch, ["ENTITY", "YEAR", "RENEWABLES_TWH"],
        [("India", 2024, expected)], "electricity-query-123",
    )
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
    assert result["sql"] and "FROM DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX" in result["sql"]
    assert result["sql_parameters"] == ["India", 2024]
    assert result["query_id"] == "electricity-query-123"
    assert result["execution"]["engine"] == "Snowflake"
    assert result["execution"]["status"] == "succeeded"
    assert result["verification"]["status"] == "passed"
    assert db_calls[0][1:] == (["India", 2024], "electricity_mix")


def test_live_question_accepts_gemmas_string_year_as_a_typed_bound_integer(monkeypatch):
    _mock_snowflake(monkeypatch, ["ENTITY", "YEAR", "RENEWABLES_TWH"], [("India", 2024, 403.39)])
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


def test_snowflake_failure_does_not_fall_back_to_the_csv_or_fake_success(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda question, dataset_id: _plan(
        dimensions=["ENTITY", "YEAR", "RENEWABLES_TWH"],
        filters=[
            {"field": "ENTITY", "operator": "eq", "value": "India"},
            {"field": "YEAR", "operator": "eq", "value": 2024},
        ], limit=1,
    ))

    def fail(_sql, _parameters=None, dataset_id=None):
        assert dataset_id == "electricity_mix"
        raise snowflake_client.SnowflakeExecutionError("electricity-query-failed")

    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", fail)
    result = pipeline.ask("What was renewable electricity generation in India in 2024?", "electricity_mix")
    assert result["dataset_id"] == "electricity_mix"
    assert result["sql"] and "DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX" in result["sql"]
    assert result["query_id"] == "electricity-query-failed"
    assert result["rows"] == [] and result["row_count"] == 0
    assert result["execution"]["engine"] == "Snowflake"
    assert result["execution"]["status"] == "failed"
    assert result["verification"]["status"] == "not_run"


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
    datasets = {item["id"]: item for item in catalog["datasets"]}
    assert set(datasets) == {"tpch_customer", "electricity_mix"}
    assert datasets["electricity_mix"]["table"] == "DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX"
    assert datasets["electricity_mix"]["availability"] == "requires_snowflake_credentials"


def test_unknown_dataset_is_rejected_before_model_or_database(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda *args, **kwargs: pytest.fail("model called"))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda *args, **kwargs: pytest.fail("Snowflake called"))
    result = pipeline.ask("count rows", "unknown")
    assert result["dataset_id"] == "unknown"
    assert result["outcome"] == "unsupported"
    assert result["sql"] is None and result["query_id"] is None


def test_model_plan_cannot_drop_explicit_country_and_year_filters(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda question, dataset_id: _plan(
        dimensions=["ENTITY", "YEAR", "RENEWABLES_TWH"], limit=100,
    ))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda *args, **kwargs: pytest.fail("unfiltered query reached Snowflake"))
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
    _mock_snowflake(monkeypatch, ["YEAR", "RENEWABLES_TWH_SUM"], [(2023, 369.97), (2024, 403.39), (2025, 500.98)])
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
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda *args, **kwargs: pytest.fail("partial country comparison executed"))
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
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda *args, **kwargs: pytest.fail("invented-country query executed"))
    result = pipeline.ask("Which countries had the most electricity generation in 2025?", "electricity_mix")
    assert result["outcome"] == "rejected"
    assert result["sql"] is None
    assert "country filter that was not stated" in result["warnings"][0]


def test_deterministic_country_ranking_uses_typed_plan_and_snowflake_rows(monkeypatch):
    rows = _independent_rows()
    expected = sorted([[row["entity"], float(row["renewables_twh"])] for row in rows if row["year"] == "2025"],
                      key=lambda row: row[1], reverse=True)[:3]
    _mock_snowflake(monkeypatch, ["ENTITY", "RENEWABLES_TWH"], [tuple(row) for row in expected])
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda *args, **kwargs: pytest.fail("this explicit intent uses the deterministic typed-plan rule"))
    result = pipeline.ask("Rank top 3 countries by renewable electricity generation for 2025, highest first.", "electricity_mix")
    assert result["plan_source"] == "deterministic_rule"
    assert result["query_plan"]["filters"] == [{"field": "YEAR", "operator": "eq", "value": 2025}]
    assert result["query_plan"]["sort"] == [{"field": "RENEWABLES_TWH", "operation": None, "direction": "DESC"}]
    assert result["sql_parameters"] == [2025]
    assert result["rows"] == expected
    assert result["row_count"] == 3
    assert result["query_id"] == "mock-snowflake-query-id"
    assert result["validation"]["status"] == "passed"
    assert result["execution"]["status"] == "succeeded"
    assert result["verification"]["status"] == "passed"


def test_country_generated_most_wording_uses_same_supported_typed_plan(monkeypatch):
    _mock_snowflake(monkeypatch, ["ENTITY", "RENEWABLES_TWH"], [
        ("China", 3920.47), ("United States", 1158.8), ("Brazil", 649.97),
    ])
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda *args, **kwargs: pytest.fail("recognized exact ranking should not need an LLM guess"))
    result = pipeline.ask("Which countries generated the most renewable electricity in 2025?", "electricity_mix")
    assert result["plan_source"] == "deterministic_rule"
    assert result["query_plan"]["filters"] == [{"field": "YEAR", "operator": "eq", "value": 2025}]
    assert result["query_plan"]["sort"][0]["field"] == "RENEWABLES_TWH"
    assert result["query_plan"]["sort"][0]["direction"] == "DESC"
    assert result["rows"][:3] == [["China", 3920.47], ["United States", 1158.8], ["Brazil", 649.97]]


def test_country_ranking_without_a_year_requests_clarification(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "generate_plan", lambda *args, **kwargs: pytest.fail("ambiguous year must clarify before model planning"))
    monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", lambda *args, **kwargs: pytest.fail("ambiguous ranking reached Snowflake"))
    result = pipeline.ask("Which countries generate the most renewable electricity?", "electricity_mix")
    assert result["outcome"] == "clarification"
    assert result["clarification"]["required"] is True
    assert "2000–2025" in result["answer"]
    assert result["sql"] is None and result["query_id"] is None
    assert result["plan_source"] == "not_run"
    assert result["validation"]["status"] == "not_run"
    assert result["execution"]["status"] == "not_run"

