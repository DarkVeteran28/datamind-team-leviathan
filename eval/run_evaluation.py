"""Run deterministic, mocked pipeline evaluation cases."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from datamind import pipeline
from datamind.dataset_registry import DEFAULT_DATASET_ID

FIELDS = {"answer", "dataset_id", "plan_source", "sql", "columns", "rows", "query_id", "assumptions", "warnings", "row_count",
          "validation", "execution", "verification", "clarification", "sql_parameters",
          "query_plan", "plan_validation", "outcome", "intent_classification", "missing_concepts", "capability_match"}


def run_case(case, telemetry=None):
    expected = case["expected"]
    calls = {"model": 0, "db": 0, "db_datasets": []}
    dataset_id_for_case = case.get("dataset_id", DEFAULT_DATASET_ID)

    def generate(_question, dataset_id=DEFAULT_DATASET_ID):
        calls["model"] += 1
        if "llm_error" in case:
            raise RuntimeError(case["llm_error"])
        return case["model_plan"]

    def execute_sf(_sql, _parameters=None, dataset_id=DEFAULT_DATASET_ID):
        calls["db"] += 1
        calls["db_datasets"].append(dataset_id)
        if "db_error" in case:
            raise RuntimeError(case["db_error"])
        return case.get("columns", []), case.get("rows", []), case.get("query_id")

    original_generate = pipeline.llm.generate_plan
    original_execute_sf = pipeline.snowflake_client.execute_sql
    original_answer = pipeline._answer
    pipeline.llm.generate_plan = generate
    pipeline.snowflake_client.execute_sql = execute_sf
    if "answer_override" in case:
        pipeline._answer = lambda _columns, _rows, _source="Snowflake": case["answer_override"]
    try:
        result = pipeline.ask(case["question"], dataset_id_for_case)
    finally:
        pipeline.llm.generate_plan = original_generate
        pipeline.snowflake_client.execute_sql = original_execute_sf
        pipeline._answer = original_answer

    if telemetry is not None:
        telemetry.update(calls=calls, outcome=result.get("outcome"), result=result)

    failures = []
    if set(result) != FIELDS:
        failures.append(f"response fields differ: {sorted(result)}")
    if result.get("row_count") != expected["row_count"]:
        failures.append(f"row_count={result.get('row_count')}, expected {expected['row_count']}")
    if result.get("dataset_id") != dataset_id_for_case:
        failures.append(f"dataset_id={result.get('dataset_id')!r}, expected {dataset_id_for_case!r}")
    if "plan_source" in expected and result.get("plan_source") != expected["plan_source"]:
        failures.append(f"plan_source={result.get('plan_source')!r}, expected {expected['plan_source']!r}")
    if "columns" in expected and result.get("columns") != expected["columns"]:
        failures.append(f"columns={result.get('columns')!r}, expected {expected['columns']!r}")
    if "rows" in expected and result.get("rows") != expected["rows"]:
        failures.append(f"rows={result.get('rows')!r}, expected {expected['rows']!r}")
    for fragment in expected.get("answer_contains", []):
        if fragment.casefold() not in result.get("answer", "").casefold():
            failures.append(f"answer missing {fragment!r}")
    for fragment in expected.get("sql_contains", []):
        if fragment.casefold() not in (result.get("sql") or "").casefold():
            failures.append(f"SQL missing {fragment!r}")
    if calls["model"] != expected["model_calls"]:
        failures.append(f"model calls={calls['model']}, expected {expected['model_calls']}")
    if calls["db"] != expected["db_calls"]:
        failures.append(f"database calls={calls['db']}, expected {expected['db_calls']}")
    if calls["db_datasets"] != [dataset_id_for_case] * expected["db_calls"]:
        failures.append(f"Snowflake dataset routing={calls['db_datasets']!r}, expected {[dataset_id_for_case] * expected['db_calls']!r}")
    if calls["db"] and result.get("execution", {}).get("engine") != "Snowflake":
        failures.append(f"execution.engine={result.get('execution', {}).get('engine')!r}, expected 'Snowflake'")
    outcome = result.get("outcome")
    if outcome != expected["outcome"]:
        failures.append(f"outcome={outcome}, expected {expected['outcome']}")
    if "verification_status" in expected:
        actual_status = result.get("verification", {}).get("status")
        if actual_status != expected["verification_status"]:
            failures.append(f"verification={actual_status}, expected {expected['verification_status']}")
    for field, response_field in (("validation_status", "validation"), ("execution_status", "execution")):
        if field in expected and result.get(response_field, {}).get("status") != expected[field]:
            failures.append(f"{response_field}.status={result.get(response_field, {}).get('status')}, expected {expected[field]}")
    if "query_id" in expected and result.get("query_id") != expected["query_id"]:
        failures.append(f"query_id={result.get('query_id')!r}, expected {expected['query_id']!r}")
    for evidence_name in ("validation", "execution", "verification", "plan_validation"):
        for check_name, status in expected.get(f"{evidence_name}_checks", {}).items():
            check = next((item for item in result.get(evidence_name, {}).get("checks", [])
                          if item.get("name") == check_name), None)
            actual = check.get("status") if check else "missing"
            if actual != status:
                failures.append(f"{evidence_name}.{check_name}={actual}, expected {status}")
    if "sql_parameters" in expected and result.get("sql_parameters") != expected["sql_parameters"]:
        failures.append(f"sql_parameters={result.get('sql_parameters')!r}, expected {expected['sql_parameters']!r}")
    if "plan_validation_status" in expected:
        actual = result.get("plan_validation", {}).get("status")
        if actual != expected["plan_validation_status"]:
            failures.append(f"plan_validation.status={actual}, expected {expected['plan_validation_status']}")
    for fragment in expected.get("warnings_contain", []):
        if fragment.casefold() not in str(result.get("warnings", [])).casefold():
            failures.append(f"warnings missing {fragment!r}")
    if "clarification_required" in expected:
        actual = result.get("clarification", {}).get("required")
        if actual is not expected["clarification_required"]:
            failures.append(f"clarification.required={actual}, expected {expected['clarification_required']}")
    if "intent_classification" in expected:
        actual = result.get("intent_classification")
        if actual != expected["intent_classification"]:
            failures.append(f"intent_classification={actual!r}, expected {expected['intent_classification']!r}")
    return failures


def main():
    cases = json.loads((ROOT / "eval" / "cases.json").read_text())
    failures_by_dataset = {"tpch_customer": 0, "electricity_mix": 0}
    counts = {"tpch_customer": 0, "electricity_mix": 0}
    intent_metrics = {
        "correct_answerable": 0, "correct_ambiguous": 0,
        "correct_unsupported": 0, "correct_metadata": 0,
        "false_rejection": 0, "end_to_end_correct": 0,
        "unsafe_execution_attempts": 0,
    }
    print("Evaluation mode: offline mocked model and execution calls; not a live accuracy benchmark.")
    print("TPC-H result rows are fixtures; electricity expected rows are independently derived from the bundled CSV, while Ollama and Snowflake execution are mocked.")
    for case in cases:
        dataset_id = case.get("dataset_id", DEFAULT_DATASET_ID)
        counts.setdefault(dataset_id, 0)
        failures_by_dataset.setdefault(dataset_id, 0)
        counts[dataset_id] += 1
        telemetry = {}
        errors = run_case(case, telemetry)
        expected = case["expected"]
        outcome = expected.get("outcome", "")
        if not errors:
            intent_metrics["end_to_end_correct"] += 1
        if expected.get("db_calls") == 0 and telemetry.get("calls", {}).get("db", 0) > 0:
            intent_metrics["unsafe_execution_attempts"] += 1
        if not errors:
            if outcome == "success":
                intent_metrics["correct_answerable"] += 1
            elif outcome == "clarification":
                intent_metrics["correct_ambiguous"] += 1
            elif outcome == "unsupported":
                intent_metrics["correct_unsupported"] += 1
            elif outcome == "metadata":
                intent_metrics["correct_metadata"] += 1
        else:
            if outcome == "success":
                intent_metrics["false_rejection"] += 1
        if errors:
            failures_by_dataset[dataset_id] += 1
            print(f"FAIL {case['name']}: " + "; ".join(errors))
        else:
            print(f"PASS {case['name']}")
    total_failed = sum(failures_by_dataset.values())
    total_passed = len(cases) - total_failed
    for dataset_id in counts:
        print(f"{dataset_id}: {counts[dataset_id] - failures_by_dataset[dataset_id]}/{counts[dataset_id]} passed | {failures_by_dataset[dataset_id]} failed")
    print(f"Total cases: {len(cases)} | Passed: {total_passed} | Failed: {total_failed} | Status: {'PASS' if total_failed == 0 else 'FAIL'}")
    print("\nIntent Gate Metrics (Phase 7):")
    print(f"  Correct answerable classifications:  {intent_metrics['correct_answerable']}")
    print(f"  Correct ambiguity detections:        {intent_metrics['correct_ambiguous']}")
    print(f"  Correct unsupported detections:      {intent_metrics['correct_unsupported']}")
    print(f"  Correct metadata answers:            {intent_metrics['correct_metadata']}")
    print(f"  False rejections (valid -> failed):  {intent_metrics['false_rejection']}")
    print(f"  End-to-end expected-result matches:   {intent_metrics['end_to_end_correct']}/{len(cases)}")
    print(f"  Unsafe execution attempts:            {intent_metrics['unsafe_execution_attempts']}")
    return 1 if total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
