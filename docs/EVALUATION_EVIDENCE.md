# DataMind Evaluation Evidence

This document is a short guide for reproducing checks and recording evidence. It supplements the [README](../README.md), which has setup, architecture, configuration, and the full limitations section. Do not treat mocked results as live model or database evidence.

## Evidence categories

| Category | What it establishes | How to run |
|---|---|---|
| Automated unit tests | Core behavior, validation, mocked service failures, answer consistency, and UI tests | `python -m pytest -q` |
| Mocked evaluation cases | Expected pipeline behavior against fixed model and database fixtures | `python eval/run_evaluation.py` |
| Live Ollama and Snowflake checks | Whether this local model/runtime and configured Snowflake account work together | Follow [Live demo](#live-ollama-and-snowflake-checks) |
| Independent result comparison | Whether a query ID, SQL text, columns, and rows agree with a direct Snowflake worksheet execution | Follow [Independent comparison](#independent-result-comparison) |

The first two categories do not contact Ollama or Snowflake. The evaluation cases replace the model and database calls with fixtures; they are not an accuracy benchmark. The live categories require local Ollama and valid Snowflake access and must be recorded separately.

## Reproduce automated checks

From the repository root, create and activate the project environment, then install the repository dependencies (see [README setup](../README.md#-quick-start)):

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q
python eval/run_evaluation.py
```

The evaluation runner prints its mocked mode, each case result, total cases, passes, failures, and overall status. It does not need `.env`, Ollama, Snowflake credentials, or network access.

### Results record

Fill this in with the output from the run being submitted. Do not copy an earlier run as if it were reproduced now.

| Run date and timezone | Command | Total | Passed | Failed | Status | Environment / notes |
|---|---|---:|---:|---:|---|---|
| `YYYY-MM-DD, TZ` | `python -m pytest -q` | `___` | `___` | `___` | `PASS/FAIL` | `Python ___; dependencies installed from requirements.txt` |
| `YYYY-MM-DD, TZ` | `python eval/run_evaluation.py` | `___` | `___` | `___` | `PASS/FAIL` | `Mocked Ollama and Snowflake; offline` |

**Fresh reproduction during Phase 5 (2026-10-18, Asia/Calcutta):** base-interpreter `python -m pytest -q` failed collection because `sqlglot` and `snowflake.connector` were not installed; plain `python eval/run_evaluation.py` also failed because `sqlglot` was unavailable. With `PYTHONPATH=.venv/lib/python3.12/site-packages`, the tests completed with **52 passed**, and the evaluation reported **16 total, 16 passed, 0 failed**. No live Ollama or Snowflake check was run in this phase. These results record this environment and do not imply a clean environment can omit dependency installation.

## Phase 6 observed release checks

The following live and direct-validator observations were supplied for this evidence update. No timestamp, raw result values, or independent worksheet comparison was supplied.

### Live Ollama and Snowflake

- Question: `Show me the top 5 customers by account balance.`
- Outcome: SQL validation and Snowflake execution succeeded; five rows were returned and answer-consistency checks passed.
- Snowflake query ID: `01c7cf3a-0002-358f-000f-e7c2000108a6`.
- Ambiguous question: `Show me the best customers.` Clarification was requested; SQL and query ID were null; validation, execution, and verification were `not_run`.

These observations document the supplied run only. They do not establish semantic correctness for every question or prove universal SQL safety.

### Direct validator checks

Four supplied adversarial checks were rejected: unauthorized table, multiple SQL statements, nested subquery, and negative `LIMIT`. These are direct validator observations and are separate from the live query above and the mocked evaluation cases below.

### Previously observed automated results

The Phase 5 run recorded above remains **52 tests passed** and **16/16 offline mocked evaluation cases passed**. These are previously observed results, not tests rerun for Phase 6; mocked cases do not demonstrate live model accuracy.

## Safety controls and limits

The implementation in [`validator.py`](../src/datamind/validator.py), [`snowflake_client.py`](../src/datamind/snowflake_client.py), and [`pipeline.py`](../src/datamind/pipeline.py) currently applies these controls:

- SQLGlot must parse exactly one read-only `SELECT`; multiple statements are rejected.
- The only approved table is `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER`.
- Approved columns are `C_CUSTKEY`, `C_NAME`, `C_ACCTBAL`, and `C_MKTSEGMENT`; arbitrary functions, joins, subqueries, window constructs, and wildcard selection are rejected (except `COUNT(*)`).
- The validator adds or caps `LIMIT` at 100. Snowflake execution sets a 30-second statement timeout and fetches at most 101 rows to detect overflow.
- The client does not include connector exception text in its safe execution error. Do not publish environment values or exception dumps from local runs.

The model now returns a versioned typed plan; trusted Python validates it, compiles SQL from the fixed catalog, and sends filter values separately as bind parameters. The compiled statement still passes through SQLGlot validation. These controls bound the supported query surface; they do not prove that the plan expresses the user’s intent, prevent all expensive query plans, or substitute for least-privilege Snowflake permissions. `LIMIT 100` bounds returned rows, not all server-side work. Review the typed plan, compiled SQL, bound values, assumptions, warnings, result rows, and query ID.

Trust Mode validation evidence reports checks actually performed. Answer verification compares the result row count and deterministic displayed values with returned data, and checks empty-result wording. Ranking-order verification is skipped because the answer composer makes no explicit ranking claim; semantic correctness is not run. Passing consistency checks does not prove query intent or model accuracy.

## Live Ollama and Snowflake checks

Use the setup and `.env` configuration instructions in the [README](../README.md#-quick-start). Keep `.env` local and do not copy it into evidence. Confirm Ollama is running and `gemma3:4b` is available, then run:

```bash
python datamind_demo.py
```

At the prompt, use a narrow supported question such as:

```text
Show five customers with the highest account balances.
```

For a successful live query, record the typed plan, displayed parameterized SQL and bound values, returned columns and rows, row count, query ID, assumptions, warnings, and the local model name. Treat filter values according to their sensitivity when sharing records. A successful-looking response without a query ID and returned result evidence is not evidence of successful live execution. Record failures as failures; never fill in expected values or query IDs.

### Compact demo sequence

1. **Supported question:** `Show five customers with the highest account balances.` Verify the actual returned rows and query ID.
2. **Ambiguous question:** `Who are the best customers?` The current intent handler should ask whether “best” means highest account balance, customer name A–Z, or customer key ascending, without generating SQL or calling Snowflake.
3. **Unsafe SQL rejection:** the interactive CLI accepts natural-language questions, not raw SQL. Demonstrate the validator rejection in the mocked test instead:

   ```bash
   python -m pytest -q tests/test_core_pipeline.py -k model_supplied_sql_field_is_rejected_before_compilation
   ```

   That test supplies an unexpected `sql` field in the mocked model plan and verifies the strict plan schema rejects it before SQL compilation or database execution. Direct SQL validator adversarial cases are tested separately. Do not try to make the live model emit unsafe SQL as a demo step.

The separate `python snowflake_test.py` command in the README is a connection diagnostic, not an end-to-end natural-language query demonstration.

## Independent result comparison

For a live successful answer:

1. Copy the displayed SQL, columns, rows, row count, and query ID into a local evidence note. Keep credentials out of that note.
2. In Snowsight, locate the query ID in **Monitoring → Query History**. Compare the query text with the SQL shown by DataMind.
3. In a worksheet using the same Snowflake role, warehouse, database, and schema, execute the displayed read-only query directly. Compare the result columns and values with DataMind’s result. Keep the same filters and ordering; use an `ORDER BY` if comparing row order.
4. Record both the DataMind query ID and the worksheet query ID, plus when each ran. If the table changes between executions or the query has no ordering, rows or their order can differ; state that instead of claiming a mismatch or a match.

This confirms the observed query and result for the recorded run. It is not a general correctness proof.

## Evidence capture and redaction

For each live run, keep a record with: date/time and timezone, code revision, local model name, question, typed plan, parameterized SQL and bound values, result columns/rows/count, DataMind query ID, direct worksheet query ID if compared, warnings, and outcome. Capture the app/terminal result and the matching Query History entry only if needed.

Before sharing screenshots or logs, remove passwords, tokens, account identifiers if private, usernames, connection strings, `.env` paths/content, and unrelated query history. Do not include raw environment dumps, stack traces, or credential-manager screens. Query IDs are useful trace evidence; share them only with people allowed to access that Snowflake account.

## Limitations

- The offline cases use hand-authored typed plans and fixture results; they measure checked behavior, not natural-language-to-plan accuracy.
- No automated check in this package proves live Gemma output quality, live Snowflake correctness, or semantic alignment with every user question.
- Intent and ambiguity detection are rule-based and cover only selected patterns.
- Ranking and semantic correctness are not established by the current deterministic answer verifier.
- A live run requires working local Ollama, the configured model, valid Snowflake credentials, and read access to the configured sample table.
- The Phase 6 live observations include a query ID and row count, but no returned row values or direct worksheet comparison were supplied. Collect those separately before claiming an independent result comparison.
