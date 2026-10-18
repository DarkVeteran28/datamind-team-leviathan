"""Run deterministic, mocked pipeline evaluation cases."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from datamind import pipeline

FIELDS = {"answer", "sql", "columns", "rows", "query_id", "assumptions", "warnings", "row_count"}


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
    pipeline.llm.generate_sql = generate
    pipeline.snowflake_client.execute_sql = execute
    try:
        result = pipeline.ask(case["question"])
    finally:
        pipeline.llm.generate_sql = original_generate
        pipeline.snowflake_client.execute_sql = original_execute

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
    return failures


def main():
    cases = json.loads((ROOT / "eval" / "cases.json").read_text())
    failed = 0
    for case in cases:
        errors = run_case(case)
        if errors:
            failed += 1
            print(f"FAIL {case['name']}: " + "; ".join(errors))
        else:
            print(f"PASS {case['name']}")
    print(f"Evaluation cases: {len(cases) - failed}/{len(cases)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
