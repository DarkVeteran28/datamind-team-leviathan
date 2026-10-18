"""Small HTTP adapter around DataMind's existing question pipeline."""
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, constr

from .pipeline import ask
from .dataset_registry import DEFAULT_DATASET_ID, list_datasets


class QueryRequest(BaseModel):
    question: constr(strip_whitespace=True, min_length=1, max_length=2000)
    dataset_id: str = DEFAULT_DATASET_ID


class StageEvidence(BaseModel):
    status: Optional[str] = "not_run"
    checks: List[Dict[str, Any]] = Field(default_factory=list)


class Clarification(BaseModel):
    required: bool = False
    question: Optional[str] = None
    options: List[Dict[str, Any]] = Field(default_factory=list)


class QueryResponse(BaseModel):
    answer: str
    dataset_id: str = DEFAULT_DATASET_ID
    plan_source: str = "not_run"
    sql: Optional[str] = None
    sql_parameters: List[Any] = Field(default_factory=list)
    query_plan: Optional[Dict[str, Any]] = None
    plan_validation: Dict[str, Any] = Field(default_factory=dict)
    outcome: str = "no_query"
    columns: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    query_id: Optional[str] = None
    assumptions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    row_count: int = 0
    validation: Dict[str, Any] = Field(default_factory=dict)
    execution: Dict[str, Any] = Field(default_factory=dict)
    verification: Dict[str, Any] = Field(default_factory=dict)
    clarification: Dict[str, Any] = Field(default_factory=dict)
    # Intent gate fields (Phase 2)
    intent_classification: str = "not_run"
    missing_concepts: List[str] = Field(default_factory=list)
    capability_match: Dict[str, Any] = Field(default_factory=dict)


def _json_safe(value):
    """Convert connector values to JSON without rounding Decimal values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _redact_configured_secrets(value):
    sensitive = {
        "SNOWFLAKE_PASSWORD", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER",
        "SNOWFLAKE_WAREHOUSE", "OLLAMA_URL",
    }
    secrets = [
        secret for name, secret in os.environ.items()
        if secret and (name in sensitive or any(
            marker in name.upper() for marker in ("PASSWORD", "TOKEN", "SECRET", "PRIVATE_KEY")
        ))
    ]
    secrets.sort(key=len, reverse=True)
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {key: _redact_configured_secrets(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_configured_secrets(item) for item in value]
    return value


def _configured_origins():
    origins = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    }
    configured = os.getenv("DATAMIND_CORS_ORIGINS", "")
    for origin in configured.split(","):
        origin = origin.strip().rstrip("/")
        if origin:
            if origin == "*" or not origin.startswith(("https://", "http://")):
                raise ValueError("DATAMIND_CORS_ORIGINS must contain explicit HTTP(S) origins.")
            origins.add(origin)
    return sorted(origins)


app = FastAPI(title="DataMind API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_configured_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(RequestValidationError)
async def safe_validation_error(_request: Request, _exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Invalid query request."})


@app.get("/api/health")
def health():
    """Report only API process health; external services are not probed."""
    return {"status": "ready", "ollama": "not_checked", "snowflake": "not_checked"}


@app.get("/api/datasets")
def datasets():
    """Return the supported dataset catalog and runtime-independent availability."""
    return {"default_dataset_id": DEFAULT_DATASET_ID, "datasets": list_datasets()}


@app.post("/api/query", response_model=QueryResponse)
def query(request: QueryRequest):
    """Call the existing synchronous pipeline in FastAPI's worker pool."""
    try:
        result = (ask(request.question) if request.dataset_id == DEFAULT_DATASET_ID
                  else ask(request.question, dataset_id=request.dataset_id))
        return _json_safe(_redact_configured_secrets(result))
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"detail": "DataMind could not process this request. Check the local model and backend configuration."},
        )
