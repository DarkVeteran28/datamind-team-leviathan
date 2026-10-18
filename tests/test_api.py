"""Offline contract tests for the local HTTP adapter."""
import sys
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datamind import api


def test_health_does_not_claim_external_services_were_checked():
    response = TestClient(api.app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready", "ollama": "not_checked", "snowflake": "not_checked"
    }


def test_query_preflight_allows_configured_vite_5174_origin():
    response = TestClient(api.app).options(
        "/api/query",
        headers={
            "Origin": "http://127.0.0.1:5174",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_query_delegates_and_preserves_pipeline_evidence(monkeypatch):
    expected = {
        "answer": "One customer was returned.",
        "sql": "SELECT C_CUSTKEY FROM CUSTOMER LIMIT 1",
        "columns": ["C_CUSTKEY", "AS_OF"],
        "rows": [[42, date(2026, 10, 18)]],
        "query_id": "query-123",
        "assumptions": [], "warnings": [], "row_count": 1,
        "validation": {"status": "passed", "checks": []},
        "execution": {"status": "succeeded", "checks": []},
        "verification": {"status": "passed", "checks": []},
        "clarification": {"required": False},
    }
    calls = []
    monkeypatch.setattr(api, "ask", lambda question: calls.append(question) or expected)

    response = TestClient(api.app).post("/api/query", json={"question": "  Who is first?  "})
    assert response.status_code == 200
    assert calls == ["Who is first?"]
    body = response.json()
    assert body["query_id"] == "query-123"
    assert body["rows"] == [[42, "2026-10-18"]]
    assert body["validation"]["status"] == "passed"
    assert body["execution"]["status"] == "succeeded"
    assert body["verification"]["status"] == "passed"


def test_query_rejects_empty_input_without_calling_pipeline(monkeypatch):
    monkeypatch.setattr(api, "ask", lambda _: pytest.fail("pipeline must not run"))
    response = TestClient(api.app).post("/api/query", json={"question": "  "})
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid query request."}


def test_query_returns_safe_error_without_exception_details(monkeypatch):
    monkeypatch.setattr(api, "ask", lambda _: (_ for _ in ()).throw(RuntimeError("private-password")))
    response = TestClient(api.app).post("/api/query", json={"question": "count customers"})
    assert response.status_code == 500
    assert "private-password" not in response.text
    assert "Traceback" not in response.text


def test_configured_secret_values_are_redacted(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "unique-private-value")
    sanitized = api._redact_configured_secrets({"answer": "value unique-private-value seen"})
    assert sanitized == {"answer": "value [redacted] seen"}


# pytest is imported after the API path is prepared to keep this module isolated
import pytest
