"""Strict query-plan validation and deterministic CUSTOMER SQL compilation."""
import math
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from .dataset_registry import DATASETS, DEFAULT_DATASET_ID
from .validator import MAX_ROWS

FieldName = Literal[
    "C_CUSTKEY", "C_NAME", "C_ACCTBAL", "C_MKTSEGMENT",
    "ENTITY", "CODE", "YEAR", "RENEWABLES_TWH",
]
Operation = Literal["count", "sum", "avg", "min", "max"]
Operator = Literal["eq", "ne", "gt", "gte", "lt", "lte"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Metric(StrictModel):
    operation: Operation
    field: Optional[FieldName] = None


class Filter(StrictModel):
    field: FieldName
    operator: Operator
    value: Any


class Sort(StrictModel):
    field: Optional[FieldName] = None
    operation: Optional[Operation] = None
    direction: Literal["ASC", "DESC"]


class QueryPlan(StrictModel):
    version: Literal[1]
    status: Literal["query", "clarification", "unsupported"]
    dimensions: List[FieldName] = Field(default_factory=list)
    metrics: List[Metric] = Field(default_factory=list)
    filters: List[Filter] = Field(default_factory=list)
    sort: List[Sort] = Field(default_factory=list)
    limit: Optional[StrictInt] = None
    message: Optional[StrictStr] = None
    assumptions: List[StrictStr] = Field(default_factory=list)


class PlanValidationError(ValueError):
    """Safe plan rejection with checks that were actually performed."""

    def __init__(self, message: str, evidence: Dict[str, Any]):
        super().__init__(message)
        self.evidence = evidence


def _error(message: str, checks: List[Dict[str, str]], check: str) -> None:
    checks.append({"name": check, "status": "failed", "detail": message})
    raise PlanValidationError(message, {"status": "rejected", "checks": list(checks)})


_PLAN_FIELDS = {
    "version", "status", "dimensions", "metrics", "filters", "sort", "limit",
    "message", "assumptions", "operation", "field", "operator", "value", "direction",
}


def _safe_schema_error_detail(error: ValidationError) -> str:
    """Describe schema failures without echoing model-provided values or keys."""
    locations = []
    for item in error.errors(include_input=False, include_url=False)[:4]:
        path = []
        unknown = False
        for part in item.get("loc", ()):
            if isinstance(part, int):
                if path:
                    path[-1] += f"[{part}]"
            elif isinstance(part, str) and part in _PLAN_FIELDS:
                path.append(part)
            else:
                unknown = True
        if unknown:
            path.append("unrecognized field")
        label = ".".join(path) or "query plan"
        error_type = item.get("type", "")
        if error_type == "extra_forbidden":
            label = "unrecognized field"
        locations.append(f"{label} ({error_type})" if error_type else label)
    if not locations:
        return "The generated query plan does not match the supported schema."
    extra = " Additional schema errors omitted." if len(error.errors()) > 4 else ""
    return "Schema mismatch at " + "; ".join(locations) + "." + extra


def _metric_expression(metric: Metric) -> str:
    if metric.operation == "count" and metric.field is None:
        return "COUNT(*)"
    if metric.field is None:
        raise ValueError("Metric field is required.")
    return f"{metric.operation.upper()}({metric.field})"


def _catalog(dataset_id):
    dataset = DATASETS.get(dataset_id)
    if dataset is None:
        return None
    fields = set(dataset["fields"])
    numeric = {name for name, details in dataset["fields"].items()
               if details["type"] in {"integer", "number"}}
    return fields, numeric


def _check_filter_value(item: Filter, catalog) -> bool:
    value = item.value
    if isinstance(value, bool):
        return False
    _, numeric_fields = catalog
    if item.field in numeric_fields:
        if not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
            return False
        if item.field == "YEAR" or item.field == "C_CUSTKEY":
            if not isinstance(value, int):
                return False
        return True
    if isinstance(value, str) and len(value) <= 200:
        return item.operator in {"eq", "ne"}
    return False


def _normalize_numeric_filter_strings(raw: Any, dataset_id: str) -> Tuple[Any, List[str]]:
    """Normalize Gemma's canonical numeric-string YEAR for electricity only.

    Gemma sometimes serializes an integer year as a JSON string even though the
    field is numeric. Converting a strictly numeric string keeps the compiled
    bind value typed; all other fields and datasets retain strict type checks.
    """
    if (dataset_id != "electricity_mix" or not isinstance(raw, dict)
            or not isinstance(raw.get("filters"), list)):
        return raw, []
    normalized = dict(raw)
    filters = []
    converted = []
    for item in raw["filters"]:
        if not isinstance(item, dict):
            filters.append(item)
            continue
        value = item.get("value")
        field = item.get("field")
        if field == "YEAR" and isinstance(value, str) and re.fullmatch(r"(?:19|20)\d{2}", value):
            item = dict(item)
            item["value"] = int(value)
            converted.append(field)
        filters.append(item)
    normalized["filters"] = filters
    return normalized, converted


def validate_query_plan(raw: Any, dataset_id: str = DEFAULT_DATASET_ID) -> Tuple[QueryPlan, Dict[str, Any]]:
    """Parse the strict schema, then apply dataset-specific semantic checks."""
    checks: List[Dict[str, str]] = []
    catalog = _catalog(dataset_id)
    if catalog is None:
        _error("The selected dataset is not registered.", checks, "registered_dataset")
    raw, normalized_fields = _normalize_numeric_filter_strings(raw, dataset_id)
    if not isinstance(raw, dict) or type(raw.get("version")) is not int:
        _error("The generated query plan does not match the supported schema.", checks, "plan_schema")
    try:
        plan = QueryPlan.model_validate(raw)
    except ValidationError as exc:
        checks.append({
            "name": "plan_schema", "status": "failed",
            "detail": _safe_schema_error_detail(exc),
        })
        raise PlanValidationError(
            "The generated query plan does not match the supported schema.",
            {"status": "rejected", "checks": list(checks)},
        ) from None
    except (TypeError, ValueError):
        _error("The generated query plan does not match the supported schema.", checks, "plan_schema")
    checks.append({"name": "plan_schema", "status": "passed", "detail": "Plan matches version 1 and contains no unknown fields."})
    if normalized_fields:
        checks.append({
            "name": "numeric_filter_normalization", "status": "passed",
            "detail": "Canonical numeric strings were converted to typed values for numeric catalog fields.",
        })

    # FieldName literals and Metric/Sort operation literals are also checked
    # explicitly here so evidence describes the allowlist check that ran.
    allowed_fields, numeric_fields = catalog
    if any(field not in allowed_fields for field in plan.dimensions):
        _error("A dimension is not approved for the selected dataset.", checks, "approved_catalog")
    if len(set(plan.dimensions)) != len(plan.dimensions):
        _error("Dimensions must not be repeated.", checks, "semantic_rules")
    if len(plan.dimensions) > 4 or len(plan.metrics) > 4 or len(plan.filters) > 8 or len(plan.sort) > 4:
        _error("The query plan exceeds supported complexity limits.", checks, "semantic_rules")

    for metric in plan.metrics:
        if metric.operation == "count":
            if metric.field is not None and metric.field not in allowed_fields:
                _error("COUNT requires an approved field.", checks, "approved_catalog")
            continue
        if metric.field is None or metric.field not in allowed_fields:
            _error("Each non-count metric requires an approved field.", checks, "approved_catalog")
        additive_field = "RENEWABLES_TWH" if dataset_id == "electricity_mix" else "C_ACCTBAL"
        if metric.operation in {"sum", "avg"} and metric.field != additive_field:
            _error("SUM and AVG are supported only for the dataset's approved additive measure.", checks, "semantic_rules")
        if metric.operation in {"min", "max"} and metric.field not in numeric_fields:
            _error("MIN and MAX require a numeric field.", checks, "semantic_rules")

    for item in plan.filters:
        if item.field not in allowed_fields:
            _error("A filter references a field outside the selected dataset.", checks, "approved_catalog")
        if not _check_filter_value(item, catalog):
            _error("A filter value or operator is incompatible with its field type.", checks, "filter_types")
    checks.append({"name": "filter_types", "status": "passed", "detail": "Filter operators and values match configured field types."})

    if plan.status == "query":
        if not plan.dimensions and not plan.metrics:
            _error("A query plan must select at least one dimension or metric.", checks, "semantic_rules")
        if any(not item.field and item.operation != "count" for item in plan.metrics):
            _error("Every non-count metric must name a field.", checks, "semantic_rules")
        for item in plan.sort:
            if item.operation is None and item.field is None:
                _error("Sorting by a field requires an approved field.", checks, "sort_semantics")
            if item.operation is None and plan.metrics and item.field not in plan.dimensions:
                _error("Grouped metrics can sort only by a grouping dimension or a selected metric.", checks, "sort_semantics")
            if item.operation is not None and not any(
                metric.operation == item.operation and metric.field == item.field
                for metric in plan.metrics
            ):
                _error("Sorting by a metric requires that metric to be selected.", checks, "sort_semantics")
    else:
        if not plan.message or not plan.message.strip():
            _error("Clarification and unsupported plans require an explanatory message.", checks, "semantic_rules")
        if plan.dimensions or plan.metrics or plan.filters or plan.sort or plan.limit is not None:
            _error("Non-query plans cannot contain executable query operations.", checks, "semantic_rules")
    checks.append({"name": "approved_catalog", "status": "passed", "detail": f"Plan fields and metric expressions use the registered {dataset_id} catalog."})
    checks.append({"name": "semantic_rules", "status": "passed", "detail": "Plan operations are consistent with the supported query semantics."})

    if plan.status == "query":
        if plan.limit is not None and plan.limit < 1:
            _error("The result limit must be a positive integer.", checks, "result_limit")
        if plan.limit is None or plan.limit > MAX_ROWS:
            plan = plan.model_copy(update={"limit": MAX_ROWS})
            limit_detail = f"LIMIT {MAX_ROWS} was applied by trusted code."
        else:
            limit_detail = f"LIMIT {plan.limit} is within the {MAX_ROWS}-row maximum."
        checks.append({"name": "result_limit", "status": "passed", "detail": limit_detail})
    return plan, {"status": "passed", "checks": checks}


def compile_query_plan(plan: QueryPlan, dataset_id: str = DEFAULT_DATASET_ID) -> Tuple[str, List[Any]]:
    """Compile a validated plan; all values are bound separately from SQL."""
    if plan.status != "query":
        raise ValueError("Only query plans can be compiled.")
    if dataset_id not in DATASETS:
        raise ValueError("The selected dataset is not registered.")
    selections = list(plan.dimensions)
    for metric in plan.metrics:
        expression = _metric_expression(metric)
        alias = ("ROW_COUNT" if dataset_id == "electricity_mix" else "CUSTOMER_COUNT") if metric.operation == "count" and metric.field is None else f"{metric.field}_{metric.operation.upper()}"
        selections.append(f"{expression} AS {alias}")
    table = DATASETS[dataset_id]["table"]
    sql = f"SELECT {', '.join(selections)} FROM {table}"

    parameters: List[Any] = []
    if plan.filters:
        clauses = []
        sql_operator = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
        for item in plan.filters:
            clauses.append(f"{item.field} {sql_operator[item.operator]} ?")
            parameters.append(item.value)
        sql += " WHERE " + " AND ".join(clauses)

    if plan.metrics and plan.dimensions:
        sql += " GROUP BY " + ", ".join(plan.dimensions)
    if plan.sort:
        order_by = []
        for item in plan.sort:
            expression = item.field if item.operation is None else (
                "COUNT(*)" if item.operation == "count" and item.field is None
                else f"{item.operation.upper()}({item.field})"
            )
            order_by.append(f"{expression} {item.direction}")
        sql += " ORDER BY " + ", ".join(order_by)
    sql += f" LIMIT {plan.limit or MAX_ROWS}"
    return sql, parameters
