"""Run deterministic, mocked pipeline evaluation cases."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from datamind import pipeline

FIELDS = {"answer", "sql", "columns", "rows", "query_id", "assumptions", "warnings", "row_count",
          "validation", "execution", "verification", "clarification"}


def run_case(case):
    expected = case["expected"]
    calls = {"model": 0, "db": 0}

    def generate(_question):
        calls["model"] += 1
        if "llm_error" in case:
            raise RuntimeError(case["llm_error"])
        return {"sql": case["model_sql"], "assumptions": case.get("assumptions", [])}

    def execute(_sql):
        calls["db"] += 1
        if "db_error" in case:
            raise RuntimeError(case["db_error"])
        return case.get("columns", []), case.get("rows", []), case.get("query_id")

    original_generate = pipeline.llm.generate_sql
    original_execute = pipeline.snowflake_client.execute_sql
    original_answer = pipeline._answer
    pipeline.llm.generate_sql = generate
    pipeline.snowflake_client.execute_sql = execute
    if "answer_override" in case:
        pipeline._answer = lambda _columns, _rows: case["answer_override"]
    try:
        result = pipeline.ask(case["question"])
    finally:
        pipeline.llm.generate_sql = original_generate
        pipeline.snowflake_client.execute_sql = original_execute
        pipeline._answer = original_answer

    failures = []
    if set(result) != FIELDS:
        failures.append(f"response fields differ: {sorted(result)}")
    if result.get("row_count") != expected["row_count"]:
        failures.append(f"row_count={result.get('row_count')}, expected {expected['row_count']}")
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
    outcome = "success" if result.get("query_id") else (
        "clarification" if result.get("warnings") and "Clarification required" in str(result["warnings"]) else
        "rejected" if result.get("sql") and not calls["db"] else
        "failed" if result.get("warnings") or calls["db"] else "no_query"
    )
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
    for evidence_name in ("validation", "execution", "verification"):
        for check_name, status in expected.get(f"{evidence_name}_checks", {}).items():
            check = next((item for item in result.get(evidence_name, {}).get("checks", [])
                          if item.get("name") == check_name), None)
            actual = check.get("status") if check else "missing"
            if actual != status:
                failures.append(f"{evidence_name}.{check_name}={actual}, expected {status}")
    for fragment in expected.get("warnings_contain", []):
        if fragment.casefold() not in str(result.get("warnings", [])).casefold():
            failures.append(f"warnings missing {fragment!r}")
    if "clarification_required" in expected:
        actual = result.get("clarification", {}).get("required")
        if actual is not expected["clarification_required"]:
            failures.append(f"clarification.required={actual}, expected {expected['clarification_required']}")
    return failures


def main():
    cases = json.loads((ROOT / "eval" / "cases.json").read_text())
    failed = 0
    print("Evaluation mode: offline mocked Ollama and Snowflake; not a live accuracy benchmark.")
    for case in cases:
        errors = run_case(case)
        if errors:
            failed += 1
            print(f"FAIL {case['name']}: " + "; ".join(errors))
        else:
            print(f"PASS {case['name']}")
    passed = len(cases) - failed
    print(f"Total cases: {len(cases)} | Passed: {passed} | Failed: {failed} | Status: {'PASS' if failed == 0 else 'FAIL'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
