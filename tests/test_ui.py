"""Streamlit UI behavior tests with the DataMind pipeline mocked."""
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datamind import pipeline


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
