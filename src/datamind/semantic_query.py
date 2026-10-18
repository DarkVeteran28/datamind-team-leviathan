"""Strict query-plan validation and deterministic CUSTOMER SQL compilation."""
import math
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from .validator import ALLOWED_COLUMNS, MAX_ROWS, TABLE

FieldName = Literal["C_CUSTKEY", "C_NAME", "C_ACCTBAL", "C_MKTSEGMENT"]
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


def _metric_expression(metric: Metric) -> str:
    if metric.operation == "count" and metric.field is None:
        return "COUNT(*)"
    if metric.field is None:
        raise ValueError("Metric field is required.")
    return f"{metric.operation.upper()}({metric.field})"


def _check_filter_value(item: Filter) -> bool:
    value = item.value
    if isinstance(value, bool):
        return False
    if item.field in {"C_CUSTKEY", "C_ACCTBAL"}:
        if not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
            return False
        if item.field == "C_CUSTKEY" and not isinstance(value, int):
            return False
        return True
    return isinstance(value, str) and len(value) <= 200 and item.operator in {"eq", "ne"}


def validate_query_plan(raw: Any) -> Tuple[QueryPlan, Dict[str, Any]]:
    """Parse the strict schema, then apply dataset-specific semantic checks."""
    checks: List[Dict[str, str]] = []
    if not isinstance(raw, dict) or type(raw.get("version")) is not int:
        _error("The generated query plan does not match the supported schema.", checks, "plan_schema")
    try:
        plan = QueryPlan.model_validate(raw)
    except (ValidationError, TypeError, ValueError):
        _error("The generated query plan does not match the supported schema.", checks, "plan_schema")
    checks.append({"name": "plan_schema", "status": "passed", "detail": "Plan matches version 1 and contains no unknown fields."})

    # FieldName literals and Metric/Sort operation literals are also checked
    # explicitly here so evidence describes the allowlist check that ran.
    if any(field not in ALLOWED_COLUMNS for field in plan.dimensions):
        _error("A dimension is not approved for the CUSTOMER dataset.", checks, "approved_catalog")
    if len(set(plan.dimensions)) != len(plan.dimensions):
        _error("Dimensions must not be repeated.", checks, "semantic_rules")
    if len(plan.dimensions) > 4 or len(plan.metrics) > 4 or len(plan.filters) > 8 or len(plan.sort) > 4:
        _error("The query plan exceeds supported complexity limits.", checks, "semantic_rules")

    numeric_fields = {"C_CUSTKEY", "C_ACCTBAL"}
    for metric in plan.metrics:
        if metric.operation == "count":
            continue
        if metric.field is None or metric.field not in ALLOWED_COLUMNS:
            _error("Each non-count metric requires an approved field.", checks, "approved_catalog")
        if metric.operation in {"sum", "avg"} and metric.field != "C_ACCTBAL":
            _error("SUM and AVG are supported only for account balance.", checks, "semantic_rules")
        if metric.operation in {"min", "max"} and metric.field not in numeric_fields:
            _error("MIN and MAX require a numeric field.", checks, "semantic_rules")

    for item in plan.filters:
        if not _check_filter_value(item):
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
    checks.append({"name": "approved_catalog", "status": "passed", "detail": "Plan fields and metric expressions use the approved CUSTOMER catalog."})
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


def compile_query_plan(plan: QueryPlan) -> Tuple[str, List[Any]]:
    """Compile a validated plan; all values are bound separately from SQL."""
    if plan.status != "query":
        raise ValueError("Only query plans can be compiled.")
    selections = list(plan.dimensions)
    for metric in plan.metrics:
        expression = _metric_expression(metric)
        alias = "CUSTOMER_COUNT" if metric.operation == "count" and metric.field is None else f"{metric.field}_{metric.operation.upper()}"
        selections.append(f"{expression} AS {alias}")
    sql = f"SELECT {', '.join(selections)} FROM {TABLE}"

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
