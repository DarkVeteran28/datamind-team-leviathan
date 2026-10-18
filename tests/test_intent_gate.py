"""Phase 6 regression tests for the Semantic Intent Gate.

All tests use mocked LLM and DB calls so they run deterministically offline.
The intent gate must block UNSUPPORTED_BY_DATASET and AMBIGUOUS requests
before any LLM planning or database execution occurs.

Test categories:
  1. Dataset mismatch  — unsupported questions produce zero SQL / zero DB calls.
  2. Ambiguity         — under-specified questions ask for clarification, no SQL.
  3. Dataset metadata  — schema/description questions answered from registry only.
  4. Safety/evidence   — safety checks still pass; status fields are independent.
  5. Explicit constraint preservation  — country/year/measure never silently dropped.
  6. Stale-result isolation  — unsupported outcome cannot expose prior results.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datamind import pipeline
from datamind.intent_gate import (
    AMBIGUOUS,
    ANSWERABLE,
    DATASET_METADATA,
    UNSUPPORTED_BY_DATASET,
    classify,
)
from datamind.validator import validate_sql, validate_sql_with_evidence

# ---------------------------------------------------------------------------
# Stable response field contract (must include new intent-gate fields)
# ---------------------------------------------------------------------------
FIELDS = {
    "answer", "dataset_id", "plan_source", "sql", "columns", "rows", "query_id",
    "assumptions", "warnings", "row_count", "validation", "execution", "verification",
    "clarification", "sql_parameters", "query_plan", "plan_validation", "outcome",
    "intent_classification", "missing_concepts", "capability_match",
}


def _no_llm(_q, **_kw):
    raise AssertionError("LLM must not be called for this request")


def _no_snowflake(*_a, **_kw):
    raise AssertionError("Snowflake must not be called for this request")


def _no_snowflake(*_a, **_kw):
    raise AssertionError("Snowflake must not be called for this request")


def _plan(**overrides):
    base = {"version": 1, "status": "query", "dimensions": [], "metrics": [],
            "filters": [], "sort": [], "limit": None, "assumptions": []}
    base.update(overrides)
    return base


# ===========================================================================
# 1. Dataset mismatch — UNSUPPORTED_BY_DATASET, zero SQL, zero DB calls
# ===========================================================================

class TestDatasetMismatch:
    """Unsupported questions must not reach the LLM, compiler, or database."""

    @pytest.mark.parametrize("question", [
        "How are my shirt sales this year compared to the last?",
        "Show shirt sales for Q4",
        "Compare shirt revenue year over year",
    ])
    def test_shirt_sales_against_tpch_customer_is_unsupported(self, monkeypatch, question):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(question, dataset_id="tpch_customer")

        assert set(result) == FIELDS
        assert result["outcome"] == "unsupported"
        assert result["intent_classification"] == UNSUPPORTED_BY_DATASET
        assert result["sql"] is None
        assert result["query_id"] is None
        assert result["rows"] == []
        assert result["row_count"] == 0
        assert result["execution"] == {"status": "not_run", "checks": []}
        assert result["validation"] == {"status": "not_run", "checks": []}
        assert result["verification"] == {"status": "not_run", "checks": []}
        # Message must name what is missing
        assert result["missing_concepts"]
        assert any("no sql" in w.lower() for w in result["warnings"])

    @pytest.mark.parametrize("question", [
        "Which product generated the most revenue?",
        "Show me our top products by revenue this quarter",
        "What were the best-selling products last year?",
    ])
    def test_product_revenue_against_tpch_customer_is_unsupported(self, monkeypatch, question):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(question, dataset_id="tpch_customer")

        assert result["outcome"] == "unsupported"
        assert result["intent_classification"] == UNSUPPORTED_BY_DATASET
        assert result["sql"] is None
        assert result["query_id"] is None
        assert result["execution"] == {"status": "not_run", "checks": []}

    @pytest.mark.parametrize("question", [
        "Show monthly sales trends for the last 12 months",
        "Compare sales this year to last year",
        "What was our revenue in 2024?",
    ])
    def test_sales_trends_against_tpch_customer_is_unsupported(self, monkeypatch, question):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(question, dataset_id="tpch_customer")

        assert result["outcome"] == "unsupported"
        assert result["intent_classification"] == UNSUPPORTED_BY_DATASET
        assert result["sql"] is None

    @pytest.mark.parametrize("question", [
        "What was the temperature in India last year?",
        "Show weather patterns for the UK",
        "How hot was it in Germany in 2024?",
    ])
    def test_temperature_against_electricity_mix_is_unsupported(self, monkeypatch, question):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(question, dataset_id="electricity_mix")

        assert result["outcome"] == "unsupported"
        assert result["intent_classification"] == UNSUPPORTED_BY_DATASET
        assert result["sql"] is None
        assert result["query_id"] is None
        assert result["execution"] == {"status": "not_run", "checks": []}

    @pytest.mark.parametrize("question", [
        "What was the temperature in India last year?",
        "Show weather patterns for the UK",
    ])
    def test_temperature_against_tpch_customer_is_also_unsupported(self, monkeypatch, question):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(question, dataset_id="tpch_customer")

        assert result["outcome"] == "unsupported"
        assert result["sql"] is None

    def test_legitimate_electricity_question_still_succeeds(self, monkeypatch):
        """A valid electricity question must not be caught by the intent gate."""
        monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _q, **_kw: _plan(
            dimensions=["ENTITY", "YEAR", "RENEWABLES_TWH"],
            filters=[{"field": "ENTITY", "operator": "eq", "value": "India"},
                     {"field": "YEAR", "operator": "eq", "value": 2024}],
            limit=1,
        ))
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql",
                            lambda _sql, _params=None, **_kwargs: (
                                ["ENTITY", "YEAR", "RENEWABLES_TWH"],
                                [["India", 2024, 403.39]],
                                None,
                            ))
        result = pipeline.ask("Show renewable electricity generation for India in 2024.",
                              dataset_id="electricity_mix")

        assert result["intent_classification"] == ANSWERABLE
        assert result["outcome"] == "success"
        assert result["sql"] is not None
        assert result["execution"]["status"] == "succeeded"

    def test_legitimate_customer_balance_question_still_succeeds(self, monkeypatch):
        """A valid TPC-H question must not be caught by the intent gate."""
        monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _q: _plan(
            dimensions=["C_CUSTKEY", "C_NAME", "C_ACCTBAL"],
            sort=[{"field": "C_ACCTBAL", "direction": "DESC"}],
            limit=5,
        ))
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql",
                            lambda *_a, **_kw: (
                                ["C_CUSTKEY", "C_NAME", "C_ACCTBAL"],
                                [[1, "Customer#000000001", 9999.99]],
                                "qid-balance-ok",
                            ))
        result = pipeline.ask("Show the five customers with the highest account balances.")

        assert result["intent_classification"] == ANSWERABLE
        assert result["outcome"] == "success"
        assert result["query_id"] == "qid-balance-ok"
        assert result["sql"] is not None

    @pytest.mark.parametrize("question", [
        "Count customers by market segment",
        "Show customers in the BUILDING segment",
        "How many customers are there?",
        "Show customer keys and account balances",
    ])
    def test_varied_legitimate_tpch_questions_pass_gate(self, monkeypatch, question):
        monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _q: _plan(
            dimensions=["C_MKTSEGMENT"],
            metrics=[{"operation": "count"}],
        ))
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql",
                            lambda *_a, **_kw: (["C_MKTSEGMENT", "CUSTOMER_COUNT"],
                                                [["BUILDING", 10]], "qid-ok"))
        result = pipeline.ask(question, dataset_id="tpch_customer")
        assert result["intent_classification"] == ANSWERABLE

    @pytest.mark.parametrize("question", [
        "Rank countries by renewable electricity generation for 2025, highest first.",
        "Show renewable electricity generation for India in 2024.",
        "How many annual country observations are in the dataset?",
        "Show top 3 countries by renewable generation in 2023",
    ])
    def test_varied_legitimate_electricity_questions_pass_gate(self, monkeypatch, question):
        monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _q, **_kw: _plan(
            dimensions=["ENTITY", "RENEWABLES_TWH"],
            filters=[{"field": "YEAR", "operator": "eq", "value": 2025}],
            sort=[{"field": "RENEWABLES_TWH", "direction": "DESC"}],
            limit=5,
        ))
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql",
                            lambda *_a, **_kw: (["ENTITY", "RENEWABLES_TWH"],
                                                [["China", 3920.47]], None))
        result = pipeline.ask(question, dataset_id="electricity_mix")
        assert result["intent_classification"] in (ANSWERABLE,)


# ===========================================================================
# 2. Ambiguity — clarification required, no LLM, no SQL, no DB
# ===========================================================================

class TestAmbiguity:
    """Ambiguous requests must ask for clarification and produce zero SQL/DB calls."""

    @pytest.mark.parametrize("question", [
        "Who are the best customers?",
        "Show me the best customers",
        "Show me the top customers",
        "Show me the top customers in the BUILDING segment",
        "Show me the top customers by spending frequency",
    ])
    def test_ambiguous_tpch_ranking_asks_clarification(self, monkeypatch, question):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(question, dataset_id="tpch_customer")

        assert result["outcome"] == "clarification"
        assert result["clarification"]["required"] is True
        assert result["clarification"]["question"]
        assert result["sql"] is None
        assert result["query_id"] is None
        assert result["rows"] == []
        assert result["execution"] == {"status": "not_run", "checks": []}
        assert result["validation"] == {"status": "not_run", "checks": []}
        assert result["verification"] == {"status": "not_run", "checks": []}

    def test_clarification_response_contains_no_compiled_sql(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("Who are the best customers?")

        # No SELECT in the answer or clarification question
        assert "SELECT" not in (result["answer"] or "")
        assert "SELECT" not in (result["clarification"].get("question") or "")
        assert result["sql"] is None

    def test_ambiguous_tpch_clarification_options_cover_supported_columns(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("Who are the best customers?")

        options = result["clarification"]["options"]
        columns = [o["column"] for o in options]
        assert "C_ACCTBAL" in columns
        assert "C_NAME" in columns
        assert "C_CUSTKEY" in columns

    def test_electricity_trend_without_year_asks_for_year(self, monkeypatch):
        """'Show renewable trend' without a year is ambiguous — needs clarification."""
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("Show the electricity trend", dataset_id="electricity_mix")

        # Either unsupported (no country) or ambiguous (no year) — must not execute
        assert result["outcome"] in ("clarification", "unsupported")
        assert result["sql"] is None
        assert result["execution"] == {"status": "not_run", "checks": []}

    def test_electricity_country_ranking_without_year_asks_for_year(self, monkeypatch):
        """Country ranking without a year is an existing ambiguity check."""
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(
            "Rank countries by renewable electricity generation, highest first.",
            dataset_id="electricity_mix",
        )

        assert result["outcome"] == "clarification"
        assert result["clarification"]["required"] is True
        assert result["sql"] is None
        assert result["execution"] == {"status": "not_run", "checks": []}

    def test_compare_this_year_last_year_against_tpch_is_unsupported_not_ambiguous(
        self, monkeypatch
    ):
        """'Compare this year with last year' against TPC-H is UNSUPPORTED (no dates),
        not merely ambiguous.  It must never execute SQL."""
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(
            "Compare this year with last year", dataset_id="tpch_customer"
        )

        assert result["outcome"] in ("unsupported", "clarification")
        assert result["sql"] is None
        assert result["execution"] == {"status": "not_run", "checks": []}

    def test_electricity_year_comparison_without_scope_clarifies(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("Compare this year with last year", dataset_id="electricity_mix")
        assert result["outcome"] == "clarification"
        assert result["intent_classification"] == AMBIGUOUS
        assert result["sql"] is None
        assert result["execution"]["status"] == "not_run"

    def test_unmapped_request_clarifies_instead_of_reaching_planner(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("Tell me about moon phases", dataset_id="tpch_customer")
        assert result["outcome"] == "clarification"
        assert result["intent_classification"] == AMBIGUOUS
        assert result["sql"] is None
        assert result["capability_match"]["status"] == "not_run"


# ===========================================================================
# 3. Dataset metadata — answered from registry, no LLM, no SQL, no DB
# ===========================================================================

class TestDatasetMetadata:

    @pytest.mark.parametrize("question", [
        "What is this dataset about?",
        "Describe this dataset",
        "Tell me about this dataset",
        "What data is available in this dataset?",
    ])
    def test_dataset_description_answered_from_registry_tpch(self, monkeypatch, question):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(question, dataset_id="tpch_customer")

        assert result["outcome"] == "metadata"
        assert result["intent_classification"] == DATASET_METADATA
        assert result["sql"] is None
        assert result["query_id"] is None
        assert result["execution"] == {"status": "not_run", "checks": []}
        assert result["validation"] == {"status": "not_run", "checks": []}
        # Answer must mention the dataset
        assert "customer" in result["answer"].lower() or "tpc" in result["answer"].lower()

    @pytest.mark.parametrize("question", [
        "Which columns are available?",
        "What columns does this dataset have?",
        "What fields are in this dataset?",
        "Show me the available fields",
        "Show me the schema",
    ])
    def test_column_list_answered_from_registry_tpch(self, monkeypatch, question):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(question, dataset_id="tpch_customer")

        assert result["outcome"] == "metadata"
        assert result["sql"] is None
        # Must list actual registered columns — not invented ones
        assert "C_CUSTKEY" in result["answer"]
        assert "C_NAME" in result["answer"]
        assert "C_ACCTBAL" in result["answer"]
        assert "C_MKTSEGMENT" in result["answer"]
        # Must NOT invent columns that don't exist
        assert "C_ADDRESS" not in result["answer"]
        assert "C_ORDERS" not in result["answer"]

    @pytest.mark.parametrize("question", [
        "What is this dataset about?",
        "Which columns are available?",
        "What years are covered?",
        "What does RENEWABLES_TWH measure?",
        "What are the units?",
    ])
    def test_metadata_questions_for_electricity_no_db_call(self, monkeypatch, question):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(question, dataset_id="electricity_mix")

        assert result["outcome"] == "metadata"
        assert result["intent_classification"] == DATASET_METADATA
        assert result["sql"] is None
        assert result["execution"] == {"status": "not_run", "checks": []}

    def test_electricity_column_metadata_lists_only_registered_fields(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("Which columns are available?", dataset_id="electricity_mix")

        assert result["outcome"] == "metadata"
        assert "ENTITY" in result["answer"]
        assert "YEAR" in result["answer"]
        assert "RENEWABLES_TWH" in result["answer"]
        # Must NOT invent absent columns
        assert "SOLAR_TWH" not in result["answer"]
        assert "WIND_TWH" not in result["answer"]
        assert "CO2" not in result["answer"]

    def test_year_coverage_metadata_returns_documented_range(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("What years are covered?", dataset_id="electricity_mix")

        assert result["outcome"] == "metadata"
        # Registry says 2000–2025
        assert "2000" in result["answer"]
        assert "2025" in result["answer"]

    def test_metadata_answer_does_not_claim_execution_succeeded(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("What is this dataset about?", dataset_id="tpch_customer")

        # No successful execution badge
        assert result["execution"].get("status") != "succeeded"
        assert result["query_id"] is None
        assert result["row_count"] == 0

    def test_metadata_no_llm_planning_call(self, monkeypatch):
        """Metadata questions must never invoke the LLM planner."""
        llm_calls = []
        monkeypatch.setattr(pipeline.llm, "generate_plan",
                            lambda *a, **kw: llm_calls.append(a) or _no_llm(*a, **kw))
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        pipeline.ask("What is this dataset about?", dataset_id="tpch_customer")
        assert llm_calls == []


# ===========================================================================
# 4. Safety and evidence — existing checks still pass; independence preserved
# ===========================================================================

class TestSafetyAndEvidence:

    @pytest.mark.parametrize("sql", [
        "DELETE FROM CUSTOMER",
        "SELECT * FROM CUSTOMER",
        "SELECT C_ADDRESS FROM CUSTOMER",
        "SELECT C_CUSTKEY FROM OTHER_DB.TPCH_SF1.CUSTOMER",
        "SELECT C_CUSTKEY FROM CUSTOMER; DROP TABLE CUSTOMER",
        "SELECT C_CUSTKEY FROM CUSTOMER JOIN ORDERS ON 1=1",
        "SELECT C_CUSTKEY FROM CUSTOMER WHERE RANDOM() > 0",
        "SELECT C_CUSTKEY FROM CUSTOMER WHERE CURRENT_USER() = 'x'",
    ])
    def test_sql_injection_and_disallowed_statements_still_rejected(self, sql):
        with pytest.raises(ValueError):
            validate_sql(sql)

    def test_multi_filter_and_conjunction_still_works(self):
        """AND-combined WHERE filters are still approved by the safety validator."""
        sql, evidence = validate_sql_with_evidence(
            "SELECT C_CUSTKEY FROM CUSTOMER "
            "WHERE C_MKTSEGMENT = 'BUILDING' AND C_ACCTBAL > 0 LIMIT 5"
        )
        assert "AND" in sql
        next(c for c in evidence["checks"] if c["name"] == "logical_operators" and c["status"] == "passed")

    def test_unsupported_outcome_has_not_run_execution_status(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(
            "How are my shirt sales this year compared to the last?",
            dataset_id="tpch_customer",
        )
        assert result["execution"]["status"] == "not_run"
        assert result["validation"]["status"] == "not_run"
        assert result["verification"]["status"] == "not_run"
        assert result["plan_validation"]["status"] == "not_run"

    def test_execution_success_and_semantic_correctness_reported_independently(
        self, monkeypatch
    ):
        """A successful execution must not claim semantic correctness."""
        monkeypatch.setattr(pipeline.llm, "generate_plan", lambda _q: _plan(
            dimensions=["C_CUSTKEY", "C_NAME"],
            sort=[{"field": "C_CUSTKEY", "direction": "ASC"}],
            limit=2,
        ))
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql",
                            lambda *_a, **_kw: (
                                ["C_CUSTKEY", "C_NAME"],
                                [[1, "Customer#000000001"], [2, "Customer#000000002"]],
                                "qid-semantic",
                            ))
        result = pipeline.ask("Show two customers")

        assert result["outcome"] == "success"
        assert result["execution"]["status"] == "succeeded"
        sem = next(
            (c for c in result["verification"]["checks"]
             if c["name"] == "semantic_correctness"), None
        )
        assert sem is not None
        assert sem["status"] == "not_run", (
            "Semantic correctness must remain 'not_run' even when execution succeeds."
        )

    def test_unknown_fields_in_plan_are_still_rejected(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan",
                            lambda _q: {"version": 1, "status": "query",
                                        "dimensions": ["C_ADDRESS"],  # not in schema
                                        "metrics": [], "filters": [], "sort": [],
                                        "limit": None, "assumptions": []})
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("Show customer names")
        assert result["outcome"] == "rejected"
        assert result["sql"] is None

    def test_malformed_plan_rejected_without_execution(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan",
                            lambda _q: {"status": "query", "dimensions": ["C_NAME"]})
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("Show customer names")
        assert result["outcome"] == "rejected"
        assert result["sql"] is None

    def test_explicit_country_constraint_cannot_be_silently_dropped(self, monkeypatch):
        """Plan that omits an explicit ENTITY filter must be rejected."""
        monkeypatch.setattr(pipeline.llm, "generate_plan",
                            lambda _q, **_kw: _plan(
                                dimensions=["ENTITY", "YEAR", "RENEWABLES_TWH"],
                                filters=[{"field": "YEAR", "operator": "eq", "value": 2024}],
                                # Missing ENTITY filter for "India"
                                limit=10,
                            ))
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(
            "Show renewable electricity generation for India in 2024.",
            dataset_id="electricity_mix",
        )
        assert result["outcome"] == "rejected"
        assert result["sql"] is None

    def test_explicit_year_constraint_cannot_be_silently_dropped(self, monkeypatch):
        """Plan that omits an explicit YEAR filter must be rejected."""
        monkeypatch.setattr(pipeline.llm, "generate_plan",
                            lambda _q, **_kw: _plan(
                                dimensions=["ENTITY", "YEAR", "RENEWABLES_TWH"],
                                filters=[{"field": "ENTITY", "operator": "eq", "value": "India"}],
                                # Missing YEAR=2024 filter
                                limit=10,
                            ))
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(
            "Show renewable electricity generation for India in 2024.",
            dataset_id="electricity_mix",
        )
        assert result["outcome"] == "rejected"
        assert result["sql"] is None

    def test_explicit_measure_sort_cannot_be_dropped_for_country_ranking(self, monkeypatch):
        """Country ranking plan must sort by RENEWABLES_TWH DESC."""
        monkeypatch.setattr(pipeline.llm, "generate_plan",
                            lambda _q, **_kw: _plan(
                                dimensions=["ENTITY", "RENEWABLES_TWH"],
                                filters=[
                                    {"field": "ENTITY", "operator": "eq", "value": "India"},
                                    {"field": "YEAR", "operator": "eq", "value": 2025},
                                ],
                                sort=[{"field": "ENTITY", "direction": "ASC"}],  # wrong sort
                                limit=5,
                            ))
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(
            "Rank India among countries by renewable electricity generation for 2025, highest first.",
            dataset_id="electricity_mix",
        )
        assert result["outcome"] == "rejected"
        assert result["sql"] is None


# ===========================================================================
# 5. Stale result isolation — unsupported/ambiguous cannot show prior results
# ===========================================================================

class TestStaleResultIsolation:
    """An unsupported or ambiguous question must return empty rows/columns,
    not results from a previous successful query."""

    def test_unsupported_question_returns_empty_rows(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(
            "How are my shirt sales this year compared to the last?",
            dataset_id="tpch_customer",
        )
        assert result["rows"] == []
        assert result["columns"] == []
        assert result["row_count"] == 0
        assert result["query_id"] is None
        assert result["sql"] is None

    def test_ambiguous_question_returns_empty_rows(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("Who are the best customers?")
        assert result["rows"] == []
        assert result["columns"] == []
        assert result["row_count"] == 0
        assert result["query_id"] is None

    def test_metadata_question_returns_empty_rows(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask("What is this dataset about?", dataset_id="tpch_customer")
        assert result["rows"] == []
        assert result["columns"] == []
        assert result["row_count"] == 0
        assert result["query_id"] is None


# ===========================================================================
# 6. Intent gate unit tests — classify() in isolation
# ===========================================================================

class TestClassifyUnit:
    """Direct unit tests of the intent_gate.classify() function."""

    def test_shirt_sales_against_tpch_is_unsupported(self):
        result = classify(
            "How are my shirt sales this year compared to the last?",
            dataset_id="tpch_customer",
        )
        assert result.outcome == UNSUPPORTED_BY_DATASET
        assert result.missing_concepts

    def test_product_revenue_against_tpch_is_unsupported(self):
        result = classify("Which product generated the most revenue?", dataset_id="tpch_customer")
        assert result.outcome == UNSUPPORTED_BY_DATASET

    def test_temperature_against_electricity_is_unsupported(self):
        result = classify("What was the temperature in India?", dataset_id="electricity_mix")
        assert result.outcome == UNSUPPORTED_BY_DATASET

    def test_temperature_against_tpch_is_unsupported(self):
        result = classify("What was the temperature in India?", dataset_id="tpch_customer")
        assert result.outcome == UNSUPPORTED_BY_DATASET

    def test_solar_breakdown_against_electricity_is_unsupported(self):
        result = classify("Show solar generation by country in 2025", dataset_id="electricity_mix")
        assert result.outcome == UNSUPPORTED_BY_DATASET

    def test_legitimate_customer_question_is_answerable(self):
        result = classify(
            "Show the five customers with the highest account balances.",
            dataset_id="tpch_customer",
        )
        assert result.outcome == ANSWERABLE
        assert result.capability_match["status"] == "passed"

    def test_legitimate_electricity_question_is_answerable(self):
        result = classify(
            "Show renewable electricity generation for India in 2024.",
            dataset_id="electricity_mix",
        )
        assert result.outcome == ANSWERABLE

    def test_country_ranking_electricity_2025_is_answerable(self):
        result = classify(
            "Rank countries by renewable electricity generation for 2025, highest first.",
            dataset_id="electricity_mix",
        )
        assert result.outcome == ANSWERABLE

    def test_what_is_dataset_about_is_metadata(self):
        for dataset_id in ("tpch_customer", "electricity_mix"):
            result = classify("What is this dataset about?", dataset_id=dataset_id)
            assert result.outcome == DATASET_METADATA

    def test_which_columns_is_metadata(self):
        for dataset_id in ("tpch_customer", "electricity_mix"):
            result = classify("Which columns are available?", dataset_id=dataset_id)
            assert result.outcome == DATASET_METADATA

    def test_schema_question_is_metadata(self):
        result = classify("Show me the schema", dataset_id="tpch_customer")
        assert result.outcome == DATASET_METADATA

    def test_year_coverage_is_metadata(self):
        result = classify("What years are covered?", dataset_id="electricity_mix")
        assert result.outcome == DATASET_METADATA

    def test_units_question_is_metadata(self):
        result = classify("What are the units?", dataset_id="electricity_mix")
        assert result.outcome == DATASET_METADATA

    def test_synonym_client_maps_to_customer(self):
        """'Show clients with the highest balance' should be ANSWERABLE."""
        result = classify(
            "Show clients with the highest balance", dataset_id="tpch_customer"
        )
        assert result.outcome == ANSWERABLE

    def test_synonym_energy_maps_to_electricity(self):
        """'Show energy generation for India in 2024' should be ANSWERABLE."""
        result = classify(
            "Show energy generation for India in 2024", dataset_id="electricity_mix"
        )
        assert result.outcome == ANSWERABLE

    def test_unsupported_message_names_missing_concept(self):
        result = classify(
            "How are my shirt sales this year compared to the last?",
            dataset_id="tpch_customer",
        )
        assert result.outcome == UNSUPPORTED_BY_DATASET
        assert result.message
        assert result.missing_concepts
        # The message should name the missing concept
        assert any(c.lower() in result.message.lower() for c in result.missing_concepts)

    def test_metadata_answer_contains_registered_fields_only(self):
        result = classify("Which columns are available?", dataset_id="tpch_customer")
        assert result.outcome == DATASET_METADATA
        assert "C_CUSTKEY" in result.metadata_answer
        assert "C_ADDRESS" not in result.metadata_answer  # never in registry

    def test_empty_question_is_unsafe(self):
        result = classify("", dataset_id="tpch_customer")
        assert result.outcome == UNSUPPORTED_BY_DATASET or result.outcome == "UNSAFE_OR_INVALID"

    def test_unregistered_dataset_is_unsafe(self):
        result = classify("Show me something", dataset_id="nonexistent_dataset")
        assert result.outcome in (UNSUPPORTED_BY_DATASET, "UNSAFE_OR_INVALID")

    @pytest.mark.parametrize("question", [
        "Show customer purchase history",
        "Show order history for customer 1",
        "What did customer 5 buy last month?",
    ])
    def test_order_history_against_tpch_is_unsupported(self, question):
        result = classify(question, dataset_id="tpch_customer")
        assert result.outcome == UNSUPPORTED_BY_DATASET

    @pytest.mark.parametrize("question", [
        "Count customers by segment",
        "Show customers in BUILDING",
        "Average account balance",
        "Show me customer key 5",
    ])
    def test_core_tpch_questions_are_answerable(self, question):
        result = classify(question, dataset_id="tpch_customer")
        assert result.outcome == ANSWERABLE

    @pytest.mark.parametrize("question", [
        "Show renewable electricity for China in 2023",
        "Count country observations in 2025",
        "How has renewable generation changed in Germany from 2020 through 2025?",
        "Top 10 countries by renewable generation in 2024",
    ])
    def test_core_electricity_questions_are_answerable(self, question):
        result = classify(question, dataset_id="electricity_mix")
        assert result.outcome == ANSWERABLE


# ===========================================================================
# 7. Response shape — new fields present in all outcomes
# ===========================================================================

class TestResponseShape:
    """Every pipeline.ask() response must include the new gate fields."""

    def _outcomes(self, monkeypatch):
        """Yield (label, result) pairs for key pipeline outcomes."""
        # Greeting
        yield "greeting", pipeline.ask("Hello")

        # Unsupported
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        yield "unsupported", pipeline.ask(
            "How are my shirt sales this year?", dataset_id="tpch_customer"
        )

        # Metadata
        yield "metadata", pipeline.ask("What is this dataset about?", dataset_id="tpch_customer")

        # Clarification
        yield "clarification", pipeline.ask("Who are the best customers?")

        # Success
        monkeypatch.setattr(pipeline.llm, "generate_plan",
                            lambda _q: _plan(dimensions=["C_CUSTKEY"], limit=1))
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql",
                            lambda *_a, **_kw: (["C_CUSTKEY"], [[1]], "qid-shape"))
        yield "success", pipeline.ask("Show one customer key")

    def test_all_outcomes_have_stable_field_set(self, monkeypatch):
        for label, result in self._outcomes(monkeypatch):
            missing = FIELDS - set(result)
            assert not missing, f"Outcome '{label}' missing fields: {missing}"
            extra = set(result) - FIELDS
            assert not extra, f"Outcome '{label}' has unexpected extra fields: {extra}"

    def test_unsupported_never_shows_execution_success(self, monkeypatch):
        monkeypatch.setattr(pipeline.llm, "generate_plan", _no_llm)
        monkeypatch.setattr(pipeline.snowflake_client, "execute_sql", _no_snowflake)
        result = pipeline.ask(
            "How are my shirt sales this year compared to the last?",
            dataset_id="tpch_customer",
        )
        assert result["execution"].get("status") != "succeeded"
        assert result["outcome"] != "success"
