"""Streamlit UI behavior tests with the DataMind pipeline mocked."""
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datamind import pipeline


def _successful_result(**overrides):
    result = {
        "answer": "Snowflake returned 1 row: C_CUSTKEY=17.",
        "sql": "SELECT C_CUSTKEY FROM CUSTOMER LIMIT 1",
        "columns": ["C_CUSTKEY"],
        "rows": [[17]],
        "query_id": "qid-ui-test",
        "assumptions": [],
        "warnings": [],
        "row_count": 1,
        "validation": {"status": "passed", "checks": []},
        "execution": {"status": "succeeded", "checks": []},
        "verification": {"status": "passed", "checks": []},
        "clarification": {"required": False, "question": None, "options": []},
    }
    result.update(overrides)
    return result


def _submit(monkeypatch, response, question="Show one customer key"):
    monkeypatch.setattr(pipeline, "ask", lambda _: response)
    app = AppTest.from_file(str(ROOT / "app" / "ui.py")).run()
    app.text_area[0].set_value(question)
    app.button[0].click().run()
    return app


def _visible_text(app):
    parts = []
    def visit(element):
        for attribute in ("value", "label"):
            value = getattr(element, attribute, None)
            if value is not None:
                parts.append(str(value))
        children = getattr(element, "children", None)
        if isinstance(children, dict):
            for child in children.values():
                visit(child)
    visit(app.main)
    for container in app.get("container"):
        visit(container)
    return "\n".join(parts)


def test_ui_displays_pipeline_answer_and_result_evidence(monkeypatch):
    called = []
    def fake_ask(question):
        called.append(question)
        return {
            "answer": "Snowflake returned 1 row: C_CUSTKEY=17.",
            "sql": "SELECT C_CUSTKEY FROM CUSTOMER LIMIT 1",
            "columns": ["C_CUSTKEY"],
            "rows": [[17]],
            "query_id": "qid-ui-test",
            "assumptions": ["requested one row"],
            "warnings": [],
            "row_count": 1,
        }
    monkeypatch.setattr(pipeline, "ask", fake_ask)
    app = AppTest.from_file(str(ROOT / "app" / "ui.py")).run()
    app.text_area[0].set_value("Show one customer key")
    app.button[0].click().run()

    assert called == ["Show one customer key"]
    assert "Snowflake returned 1 row" in app.success[0].value
    assert len(app.dataframe) == 1
    assert any("qid-ui-test" in item.value for item in app.caption)
    assert not app.exception


def test_ui_shows_clarification_and_warnings_without_fake_results(monkeypatch):
    monkeypatch.setattr(pipeline, "ask", lambda _: {
        "answer": "How should I define best customers?",
        "sql": None,
        "columns": [],
        "rows": [],
        "query_id": None,
        "assumptions": [],
        "warnings": ["Clarification required before querying."],
        "row_count": 0,
    })
    app = AppTest.from_file(str(ROOT / "app" / "ui.py")).run()
    app.text_area[0].set_value("Who are the best customers?")
    app.button[0].click().run()

    assert "Clarification needed" in app.info[0].value
    assert any("Clarification required" in item.value for item in app.warning)
    assert len(app.dataframe) == 0
    assert not app.exception


def test_trust_mode_renders_passed_failed_skipped_and_not_run(monkeypatch):
    response = _successful_result(
        validation={"status": "passed", "checks": [
            {"name": "single_statement", "status": "passed", "detail": "One statement."},
            {"name": "approved_table", "status": "failed", "detail": "Table is not allowed."},
        ]},
        execution={"status": "not_run", "checks": []},
        verification={"status": "passed", "checks": [
            {"name": "ranking_order", "status": "skipped", "detail": "No ranking claim."},
            {"name": "semantic_correctness", "status": "not_run", "detail": "Not evaluated."},
        ]},
    )
    app = _submit(monkeypatch, response)
    rendered = _visible_text(app)
    for text in ("Trust Mode evidence", "SQL validation", "Snowflake execution",
                 "Answer consistency", "single_statement: Passed", "approved_table: Failed",
                 "ranking_order: Skipped", "semantic_correctness: Not Run",
                 "Semantic correctness: Not run"):
        assert text.casefold() in rendered.casefold()
    assert not app.exception


def test_clarification_has_no_sql_or_query_receipt(monkeypatch):
    response = _successful_result(
        answer="How should I define best customers?",
        sql=None, query_id=None, rows=[], columns=[], row_count=0,
        warnings=["Clarification required before querying."],
        validation={"status": "not_run", "checks": []},
        execution={"status": "not_run", "checks": []},
        verification={"status": "not_run", "checks": []},
        clarification={"required": True, "question": "Which metric?", "options": [
            {"label": "Highest account balance"}, {"label": "Customer key ascending"}
        ]},
    )
    app = _submit(monkeypatch, response, "Who are the best customers?")
    rendered = _visible_text(app)
    assert "Clarification needed" in rendered
    assert "No SQL was executed and no Snowflake query ID was created" in rendered
    assert "Highest account balance" in rendered
    assert "No receipt: clarification was requested" in rendered
    assert not app.exception


def test_rejected_sql_is_labelled_as_proposal_not_executed(monkeypatch):
    response = _successful_result(
        answer="SQL validation rejected the query.",
        sql="SELECT C_ADDRESS FROM CUSTOMER", query_id=None, columns=[], rows=[], row_count=0,
        validation={"status": "rejected", "checks": [
            {"name": "approved_columns", "status": "failed", "detail": "Unapproved column."}
        ]},
        execution={"status": "not_run", "checks": []},
        verification={"status": "not_run", "checks": []},
    )
    app = _submit(monkeypatch, response)
    rendered = _visible_text(app)
    assert "rejected before execution" in rendered
    assert "No receipt: SQL validation rejected" in rendered
    assert not app.exception


def test_database_failure_and_empty_results_are_honest(monkeypatch):
    failure = _successful_result(
        answer="The Snowflake query failed; no result values are available.",
        sql="SELECT C_CUSTKEY FROM CUSTOMER LIMIT 1", query_id=None, rows=[], columns=[], row_count=0,
        execution={"status": "failed", "checks": [
            {"name": "snowflake_execution", "status": "failed", "detail": "No complete result."}
        ]},
        verification={"status": "not_run", "checks": []},
    )
    failed_app = _submit(monkeypatch, failure)
    assert any("Snowflake query failed" in item.value for item in failed_app.error)
    assert "No successful execution receipt" in _visible_text(failed_app)
    assert not failed_app.get("download_button")
    assert not failed_app.exception

    empty = _successful_result(
        answer="The query completed successfully and returned no rows.",
        query_id="qid-empty", columns=["C_CUSTKEY"], rows=[], row_count=0,
    )
    empty_app = _submit(monkeypatch, empty)
    assert "query succeeded and returned no rows" in _visible_text(empty_app).casefold()
    assert not empty_app.get("download_button")
    assert not empty_app.exception


def test_csv_is_available_only_for_real_returned_rows(monkeypatch):
    with_rows = _submit(monkeypatch, _successful_result())
    assert len(with_rows.get("download_button")) == 1
    assert not with_rows.exception


def test_missing_optional_response_fields_are_handled(monkeypatch):
    app = _submit(monkeypatch, {"answer": "A response with no optional fields."})
    assert "A response with no optional fields." in _visible_text(app)
    assert "Unknown" in _visible_text(app)
    assert not app.exception


def test_session_history_review_does_not_repeat_pipeline_call(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "ask", lambda question: calls.append(question) or _successful_result())
    app = AppTest.from_file(str(ROOT / "app" / "ui.py")).run()
    app.text_area[0].set_value("Show one customer key")
    app.button[0].click().run()
    assert calls == ["Show one customer key"]
    previous_question = app.selectbox[1].options[1]
    app.selectbox[1].select(previous_question).run()
    app.button[2].click().run()
    assert calls == ["Show one customer key"]
    assert "Session history" in _visible_text(app)
    assert not app.exception


def test_example_selection_populates_input_without_submitting(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "ask", lambda question: calls.append(question) or _successful_result())
    app = AppTest.from_file(str(ROOT / "app" / "ui.py")).run()
    example = "Count customers by market segment."
    app.selectbox[0].select(example).run()
    app.button[1].click().run()
    assert app.text_area[0].value == example
    assert calls == []
    assert not app.exception
