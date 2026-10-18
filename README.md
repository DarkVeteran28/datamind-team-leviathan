# Problem Statement

**The challenge.** Organizations hold large amounts of information in databases, spreadsheets, documents and other sources. Getting a useful answer often takes technical skills, specialised queries or hours of manual searching, so the people who understand the questions best are often the least able to reach the data.

**Your mission.** Create an AI-powered data experience that lets people ask questions in everyday language and get useful answers grounded in the available data, with enough explanation that users trust the response reflects the information actually examined.

**Keep in mind.** The goal is not fluent text. The system must meaningfully work with data (retrieve, query, analyse) and make its answers understandable and trustworthy. Think broadly about data types, industries and users: business intelligence, operations, research, education, finance and decision-making are all fair game. Unlike a chatbot that produces plausible text, a data agent computes answers from the real data, shows the query, rows or sources, flags gaps, and changes its answer when the data changes.

---

[README.md](https://github.com/user-attachments/files/33623777/README.md)<div align="center">

# 🐉 DataMind: Talk to Your Data

### Ask questions in plain English. Get answers computed from the selected data source, with query evidence.

**ZeroDay OSS Hacktoberfest 2026 · IIIT Dharwad · Track PS1**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-yellow)
![Snowflake](https://img.shields.io/badge/data%20platform-Snowflake-29B5E8)
![Gemma](https://img.shields.io/badge/model-Gemma%203%204B-4285F4)
![Inference](https://img.shields.io/badge/inference-local%20Ollama-black)
![Tests](https://img.shields.io/badge/tests-pytest-green)

[Overview](#-overview) · [Architecture](#-architecture) · [Quick start](#-quick-start) · [Safety](#-safety-model) · [Testing](#-testing-and-evaluation) · [Limitations](#-limitations)

</div>

---

## 📌 Overview

Organizations hold large amounts of information in databases, but getting a useful answer usually takes SQL skills, specialised queries or hours of manual searching. The people who understand the questions best are often the least able to reach the data.

**DataMind** is a natural-language interface to two explicitly registered datasets:

1. You ask a question in everyday language.
2. **Gemma 3 4B**, running locally through **Ollama**, proposes a typed query plan. A narrow, deterministic plan rule handles explicit country rankings by renewable generation; its source is shown in the response evidence.
3. Trusted Python validates the plan for the selected catalog, compiles deterministic SQL, and binds filter values; the **SQLGlot validator** checks the compiled SQL.
4. `tpch_customer` routes to Snowflake TPC-H CUSTOMER; `electricity_mix` routes to `DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX`. TPC-H remains the default when no dataset is selected.
5. The answer is composed **directly from returned rows**. Both datasets return Snowflake query IDs when Snowflake supplies one.

> **Design principle: Gemma interprets, trusted Python compiles, the validator decides, the selected engine computes.**
> The model returns no executable SQL and never narrates results, so it cannot inject SQL identifiers or invent answer values.

### What every answer contains

| Output | Meaning |
|---|---|
| `answer` | Plain-language answer built from returned column names and row values |
| `sql` | Deterministically compiled SQL with bind placeholders |
| `sql_parameters` | Filter values bound separately to the selected database engine |
| `query_plan`, `plan_validation` | Typed intent proposal and the checks that accepted or rejected it |
| `plan_source` | `ollama`, `deterministic_rule`, or `not_run` |
| `columns`, `rows`, `row_count` | The complete result set |
| `query_id` | Snowflake query ID, when returned by the connector |
| `dataset_id` | Dataset selected and used for the request |
| `assumptions` | Interpretations the model made |
| `warnings` | Failures, rejections or anything the user should know |

### Example questions

```text
Show five customers with the highest account balances.
Count customers by market segment.
Who are the best customers?      →  asks a clarifying question before querying
How did renewable electricity generation change in India from 2023 to 2025?
Rank countries by renewable electricity generation for 2025, highest first.
```

Electricity questions are limited to combined renewable generation in terawatt-hours. The bundled view has no individual solar/wind breakdown, renewable share, or per-capita measure.

---

## ✅ Requirement checklist

### Core requirements

| ID | Requirement | How DataMind meets it |
|---|---|---|
| M1 | Everyday-language questions | Natural-language input handled by Gemma 3 4B |
| M2 | Answers from real querying at question time | Each data answer queries the selected Snowflake table |
| M3 | Grounded answers, no unsupported model claims | Answer text is composed from returned rows; the LLM does not narrate results |
| M4 | Plain-language explanation of how the answer was obtained | Answer, assumptions and warnings returned with every response |
| M5 | Inspectable evidence | Selected dataset, SQL, returned rows; Snowflake query ID when using Snowflake |
| M6 | Handling of ambiguity, empty results, unsupported requests | See [Behaviour on hard cases](#-behaviour-on-hard-cases) |
| M7 | Meaningful Snowflake and Gemma integration | See [Technology usage](#-how-the-required-technologies-are-used) |
| M8 | Working, reproducible, open source | This repository, MIT licensed, with setup and tests |

### Compliance gates

| Gate | Requirement | Status |
|---|---|---|
| G1 | Open-source repository with licence | ✅ MIT, see [`LICENSE`](LICENSE) |
| G2 | Reproducible setup and feasible evaluation path | ✅ Offline mocked tests/evaluation; live data queries require configured Ollama and Snowflake access |
| G3 | Real system, not mock-ups | ✅ Both registered datasets route to Snowflake; deterministic offline tests remain separate |
| G4 | Datasets and licences disclosed | ✅ Sources, attribution and licensing caveat documented in [`DATASETS.md`](DATASETS.md) |
| G5 | No secrets in the repository | ✅ `.env` is git-ignored; only `.env.example` is committed |
| P1 | Snowflake used meaningfully | ✅ TPC-H CUSTOMER and OWID electricity tables execute through Snowflake |
| P2 | Gemma used meaningfully | ✅ Gemma interprets questions into typed query plans |
| P3 | Answers derived from queries run at question time | ✅ |

---

## 🧩 How the required technologies are used

### Snowflake

| Aspect | Implementation |
|---|---|
| Role | Executes approved queries for both registered datasets |
| Data | `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER` and `DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX` |
| Client | `src/datamind/snowflake_client.py`: credential check, connection, **30-second statement timeout**, result retrieval |
| Evidence | The **query ID** is returned with every successful answer |
| Failure handling | Execution failures return a warning and never claim a successful query |

Electricity queries require access to `DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX` through the configured Snowflake account. The bundled `data/electricity_mix.csv` remains the reproducible source used to prepare and independently evaluate the uploaded table; it is not a query fallback.

### Gemma

| Aspect | Implementation |
|---|---|
| Model | **Gemma 3 4B** (`gemma3:4b`), configurable through `DATAMIND_MODEL` |
| Runtime | Local **Ollama**, configurable through `OLLAMA_URL` (default `http://localhost:11434/api/chat`) |
| Task | Translates a natural-language question into a versioned typed query plan returned as JSON, including its assumptions |
| Output handling | `src/datamind/llm.py` parses the JSON response; unusable output is reported as a failure |
| Not delegated to Gemma | SQL validation, query execution, row handling and answer composition |

**Separation of concerns:** Gemma proposes intent only. Trusted Python validates the plan and compiles SQL; nothing from the model is executed as SQL.

---

## 🏆 Use of Sponsored Technologies

DataMind uses **Snowflake** as its cloud data warehouse and SQL execution layer for structured analytics. The `tpch_customer` dataset queries the Snowflake sample table `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER`; `electricity_mix` queries `DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX`.

### Snowflake

`src/datamind/pipeline.py` routes the selected dataset to `src/datamind/snowflake_client.py`. The client reads `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, and `SNOWFLAKE_WAREHOUSE` from environment variables; credentials must never be hardcoded or committed. DataMind validates the query plan, compiles parameterized SQL, applies SQL safety checks, then executes it against the registered table. Returned rows and the Snowflake query ID are included as evidence in the interface.

### Gemma 3

Gemma 3 4B (`gemma3:4b`) runs locally through Ollama. `src/datamind/llm.py` uses `DATAMIND_MODEL` and `OLLAMA_URL` to ask it to interpret a natural-language question and propose a structured JSON `QueryPlan`. The plan is checked by deterministic schema and semantic validation, compiled by trusted Python, and checked by the SQL safety validator before execution. Gemma does not produce executable SQL, access Snowflake, or independently determine whether returned results are correct. A narrow deterministic rule handles explicit electricity country rankings without calling Gemma.

### End-to-end workflow

**User question → semantic intent gate → Gemma 3 via Ollama (or the deterministic ranking rule) → structured query plan → typed-plan validation and SQL compilation → SQL safety validation → Snowflake execution → returned results and evidence in the DataMind interface.** Answer text is composed from the returned columns and rows; the model does not see query results.

---

## 🏗️ Architecture

```mermaid
flowchart TD
    Q[User question] --> P{Greeting, identity<br/>or ambiguous?}
    P -->|yes| R[Reply or ask for clarification<br/>no data query]
    P -->|no| D{Explicit supported<br/>electricity ranking?}
    D -->|yes| DP[Trusted deterministic<br/>typed-plan rule]
    D -->|no| L[Gemma 3 4B via Ollama<br/>proposes typed plan as JSON]
    DP --> T
    L --> T{Strict schema and<br/>semantic validation}
    T -->|clarification or unsupported| W[Respond without SQL or execution]
    T -->|query plan| C[Trusted deterministic compiler<br/>bound filter values]
    C --> V{SQLGlot validator<br/>single SELECT, allowlists, 100-row cap}
    V -->|rejected| W[Warning: query not executed]
    V -->|approved| S{Selected dataset engine}
    S -->|tpch_customer| SF[Snowflake · 30 s timeout]
    S -->|electricity_mix| ESF[Snowflake DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX · 30 s timeout]
    SF -->|error| W
    ESF -->|error| W
    SF -->|rows| A[Answer composed from returned rows<br/>no LLM narration]
    ESF -->|rows| A
    A --> U[UI: answer, SQL, rows, query ID,<br/>assumptions, warnings]
    W --> U
```

### Project structure

| Path | Responsibility |
|---|---|
| `src/datamind/llm.py` | Ollama chat request and query-plan JSON parsing |
| `src/datamind/dataset_registry.py` | Dataset metadata, catalogs, default, provenance and availability |
| `src/datamind/electricity_client.py` | CSV-backed entity-name matching for explicit-question-scope checks |
| `src/datamind/semantic_query.py` | Strict plan schema, typed semantic checks, and deterministic parameterized SQL compiler |
| `src/datamind/validator.py` | Dataset-specific single-`SELECT` parsing; table, column, function and clause restrictions; 100-row cap |
| `src/datamind/snowflake_client.py` | Credential check, connection, 30 s statement timeout, result retrieval |
| `src/datamind/pipeline.py` | `ask(question, dataset_id)` orchestration and explicit backend routing |
| `src/datamind/api.py` | Local FastAPI adapter, `GET /api/datasets`, and backward-compatible default routing |
| `app/ui.py` | Streamlit interface showing answers, SQL, rows, query IDs, assumptions and warnings |
| `frontend/` | React, TypeScript and Vite Trust Console; session-only query history |
| `datamind_demo.py` | Interactive terminal interface |
| `eval/` | Deterministic evaluation runner and cases (`run_evaluation.py`, `cases.json`) |
| `snowflake_test.py` | Live Snowflake connection diagnostic |
| `DATASETS.md` | Dataset sources and attribution |

`ask(question, dataset_id="tpch_customer")` preserves `answer`, `sql`, `columns`, `rows`, `query_id`, `assumptions`, `warnings` and `row_count`, and includes `dataset_id`, `query_plan`, `plan_validation`, `sql_parameters` and `outcome`. SQL filter placeholders correspond positionally to `sql_parameters`. For multi-row results the answer text shows up to three rows, and the complete result remains in `rows`.

---

## 🛡️ Safety model

The model returns a declarative query plan, never executable SQL. Trusted code compiles only approved catalog entries and binds filter values. Compiled SQL still runs only if it passes every SQL safety check.

| Layer | What it enforces |
|---|---|
| Single statement | Exactly one `SELECT` |
| Table allowlist | TPC-H: `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER`; electricity: `DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX` |
| Column allowlist | Dataset-specific: four approved customer fields or `ENTITY`, `CODE`, `YEAR`, `RENEWABLES_TWH` |
| Function and clause restrictions | Joins, subqueries, window functions, wildcard selection and arbitrary functions are rejected |
| Plan and type restrictions | Unknown fields and operations are rejected; filters must use approved operators and values matching configured field types |
| Parameter binding | User filter values are passed separately from the compiled statement |
| Row cap | `LIMIT 100` is enforced |
| Statement timeout | 30 seconds on Snowflake |
| Pre-query routing | Greetings, identity questions and detected ambiguity return without contacting Snowflake |
| Secret hygiene | Credentials are never printed by the CLI; `.env` is git-ignored |

---

## 🧭 Behaviour on hard cases

| Situation | Behaviour | Calls Snowflake? |
|---|---|:---:|
| Greeting or "what can you do?" | Friendly capabilities reply | No |
| Ambiguous question (e.g. "best customers") | Asks a clarifying question before querying | No |
| Model returns an unusable plan | Rejected before SQL compilation; no query claimed | No |
| Unsupported request | Explicit unsupported response before SQL compilation | No |
| SQL fails validation (unknown column, join, `DROP`, …) | Rejected with a warning; **not executed** | No |
| Snowflake error or timeout | Warning reported; success is never claimed; electricity is not redirected to local CSV | Yes, if execution begins |
| Missing local CSV | Snowflake query routing remains unchanged; entity-name scope matching may be less specific | No |
| Valid query, zero rows | States that the query succeeded and returned no rows | Yes |
| Valid query, many rows | Answer shows up to three rows; full result stays in `rows` | Yes |

---

## 🚀 Quick start

### Prerequisites

| Item | Detail |
|---|---|
| Python | 3.10 or newer |
| Ollama | Installed and running ([ollama.com](https://ollama.com)) |
| Snowflake | Required for both datasets; the configured role must read TPC-H CUSTOMER and `DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX` |
| Memory and disk | Enough to run `gemma3:4b` locally (a download of a few GB) |

### Install

```bash
git clone https://github.com/ZERODAY-2026/Leviathan.git
cd Leviathan

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

ollama pull gemma3:4b
ollama list                        # confirm the model is available

cp .env.example .env               # then fill in your values; never commit .env
```

### Configuration

| Variable | Required | Meaning |
|---|:---:|---|
| `SNOWFLAKE_ACCOUNT` | Yes | Snowflake account identifier |
| `SNOWFLAKE_USER` | Yes | Snowflake user |
| `SNOWFLAKE_PASSWORD` | Yes | Snowflake password |
| `SNOWFLAKE_WAREHOUSE` | Yes | Warehouse used to run queries |
| `DATAMIND_MODEL` | optional | Ollama model name, default `gemma3:4b` |
| `OLLAMA_URL` | optional | Default `http://localhost:11434/api/chat` |

Database, schema and table names are fixed in the trusted dataset registry: `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER` and `DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX`. The default dataset is `tpch_customer`; selecting `electricity_mix` changes the Snowflake execution context and never falls back to the local CSV.

### Run

#### React Trust Console (primary web interface)

Start the local backend from the repository root after activating the Python environment and configuring `.env`:

```bash
uvicorn datamind.api:app --app-dir src --host 127.0.0.1 --port 8000
```

Use a single current API on port **8000**. Uvicorn does not reload changed Python unless you pass `--reload`, so an older DataMind process on 8000 will keep serving stale routes (no `/api/datasets`, no electricity dataset). Confirm with `curl http://127.0.0.1:8000/api/datasets` — the response must list `tpch_customer` and `electricity_mix`. If port 8000 is already taken by that older process, stop it and start the current API there. Do not start a second copy on 8001 unless you also point the frontend at that port.

In another terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open <http://127.0.0.1:5173> (Vite may choose 5174 if 5173 is busy). The optional `frontend/.env.local` can set `VITE_DATAMIND_API_URL` (default `http://127.0.0.1:8000`). Restart Vite after changing that value. The API health indicator reports only whether the API process responds; it does not probe Ollama or Snowflake. The API has no authentication and is intended for local use; keep it bound to loopback. Browser access allows only the Vite localhost origins by default. Additional explicit HTTP(S) origins can be set in `DATAMIND_CORS_ORIGINS`.

#### Streamlit fallback and terminal demo

```bash
streamlit run app/ui.py        # Streamlit fallback
python datamind_demo.py        # terminal demo
```

### Frontend checks

```bash
cd frontend
npm test
npm run build
```

Frontend tests mock the API. The production build checks TypeScript and bundles the UI; neither demonstrates a live Snowflake or Ollama connection.

---

## 🎬 Reproduce the demo

1. Start Ollama and confirm the model with `ollama list`.
2. Set the four Snowflake variables for a role and warehouse that can read both registered tables. Confirm the electricity target table is loaded using the checks in [`DATASETS.md`](DATASETS.md).
3. Run `streamlit run app/ui.py`.
4. Select TPC-H and ask **"Show five customers with the highest account balances."** Note the SQL, rows and query ID.
5. Select Electricity and ask **"What was renewable electricity generation in India in 2024?"** The Snowflake SQL, returned rows, and query ID appear.
6. Try **"Rank countries by renewable electricity generation for 2025, highest first."** to see a bounded, data-backed ranking.
7. For a Snowflake answer, open Snowsight → *Monitoring → Query History*, find the displayed query ID, and confirm it matches the SQL shown in the app.

---

## 🧪 Testing and evaluation

### Unit tests

```bash
python -m pytest -q
```

Model and Snowflake calls are mocked, so unit tests need no credentials or network access.

### Deterministic behaviour evaluation

```bash
python eval/run_evaluation.py
```

The runner reports pass/fail case by case and separates `tpch_customer` from `electricity_mix`. Electricity expected values are independently calculated from the bundled CSV; the pipeline's model and execution boundaries remain mocked in this runner.

> **What this does and does not show.** This offline evaluation does **not** measure Gemma's SQL accuracy or live Snowflake correctness. TPC-H rows are fixtures; electricity expected rows are derived from the bundled data, but the evaluator still mocks execution.

### Live connection check

```bash
python snowflake_test.py
```

A standalone diagnostic against your real Snowflake account. It is not part of the automated unit suite.

---

## 🔍 Evidence and traceability

- Every successful answer includes the selected dataset, executed SQL and returned rows. Both dataset routes use Snowflake and include its query ID when available.
- Answer text is built from returned column names and row values, not from model narration.
- Failed generation, validation or execution returns warnings and **never claims a successful query**.
- To verify independently, copy a query ID into Snowsight → *Monitoring → Query History* and compare the query text and results.

---

## 📚 Dataset and attribution

| Dataset | Source | Terms | In this repo? |
|---|---|---|:---:|
| `tpch_customer` | `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER` through the user's Snowflake account | Snowflake sample-data terms; not redistributed | No |
| `electricity_mix` | Snowflake `DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX`; source subset documented in `DATASETS.md` | OWID-produced data is CC BY 4.0; original third-party data may have separate terms | Yes, compact reproducible CSV subset |

TPC-H is benchmark data, not real customer records. Electricity subset: ISO alpha-3-coded country/territory records for 2000–2025; 5,387 rows, 214 coded entities. `RENEWABLES_TWH` means combined renewable electricity generation in TWh; it is neither an individual fuel series, percentage share nor per-capita value. Blank numeric values load as SQL `NULL`; absent source rows are not synthesized as zero. See [`DATASETS.md`](DATASETS.md) for retrieval date, subset process and attribution.

**Gemma:** model weights are fetched by each user through Ollama under the licence of the variant used. They are not redistributed in this repository.

---

## 🔐 Security and secrets

- No keys, tokens or passwords are committed. `.env` is git-ignored and `.env.example` contains only safe placeholders.
- Credentials are never printed by the CLI.
- All generated SQL is validated before it reaches Snowflake.

---

## ⚠️ Limitations

We state these openly so you can judge the project on what it really does.

- **Narrow scope.** Each dataset has a conservative `SELECT` catalog and a 100-row result limit. Joins, subqueries, window functions, wildcard selection, arbitrary functions, and unregistered tables or columns are rejected.
- **Electricity measure scope.** Only combined renewable generation is bundled. It does not provide total generation, solar/wind breakdowns, renewable shares or per-capita measures. The compact snapshot ends in 2025 and is not refreshed automatically.
- **Bounded plan schema and rule-based ambiguity detection.** They cannot cover every natural-language phrasing. Review compiled SQL, bound values, and assumptions whenever intent matters.
- **No model-accuracy benchmark.** The deterministic evaluation measures expected behaviour on fixtures, not real Gemma accuracy or live Snowflake correctness.
- **Row cap is not a cost cap.** `LIMIT 100` bounds returned rows, not the work Snowflake performs. Both Snowflake routes use a 30-second statement timeout.
- **Small local model.** Gemma 3 4B can return a valid plan that does not fully match the user's intent. Schema checks and the SQL validator restrict executable behavior but cannot guarantee semantic correctness.
- **Live demo requirements.** A working local Ollama install is required for natural-language planning. Snowflake credentials and table access are required for both datasets; the bundled electricity CSV is not queried by the application.

---

## 💡 Main technical contribution

DataMind treats the language model as an **untrusted intent interpreter**. Trusted code validates a typed plan against the selected dataset's fixed catalog, compiles SQL, binds filter values, and applies SQLGlot checks before routing to the appropriate engine. The answer composer then uses only returned values. These controls restrict unsafe proposals, but they do not prove that a plan captures every user's intent; review the SQL, bound values, assumptions, rows, dataset ID and (for Snowflake) query ID. Inference stays local through Ollama.

---

## 🤝 Contributing

Issues and pull requests are welcome. Please run `python -m pytest -q` before submitting a change, and never commit credentials or dataset copies.

## 📄 Licence

Released under the **MIT License**. See [`LICENSE`](LICENSE).

---

<div align="center">

Built for **ZeroDay OSS Hacktoberfest 2026 · IIIT Dharwad**
Thanks to Snowflake, Google Gemma, Ollama and SQLGlot.

</div>
