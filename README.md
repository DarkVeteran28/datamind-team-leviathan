# DataMind: Talk to Your Data

DataMind is a local natural language interface for the Snowflake sample TPC-H `CUSTOMER` table. Gemma 3 4B (through Ollama) proposes SQL; a strict SQLGlot validator checks it; only then does the Snowflake client execute it. Results and the Snowflake query ID are returned with the answer.

## Setup

1. Install Python 3.10+ and create/activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`.
3. Install and start Ollama, then fetch the configured model: `ollama pull gemma3:4b`.
4. Copy `.env.example` to `.env` and fill in Snowflake account, user, password, and warehouse values. Keep `.env` private; it is ignored by Git.
5. Run `python datamind_demo.py`.

Optional Ollama configuration: `DATAMIND_MODEL` (default `gemma3:4b`) and `OLLAMA_URL` (default `http://localhost:11434/api/chat`).

## Configuration

Required environment variables are `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, and `SNOWFLAKE_WAREHOUSE`. The database and schema are fixed to `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1`; the allowed columns are `C_CUSTKEY`, `C_NAME`, `C_ACCTBAL`, and `C_MKTSEGMENT`. Credentials are never printed by the CLI.

## Architecture

- `src/datamind/llm.py`: Ollama chat request and JSON response parsing.
- `src/datamind/validator.py`: single SELECT parsing, table/column/function/clause restrictions, and 100-row cap.
- `src/datamind/snowflake_client.py`: credential check, connection, 30-second statement timeout, and result retrieval.
- `src/datamind/pipeline.py`: `ask(question)` orchestration, greetings/capabilities, ambiguity clarification, evidence-based answer, and failure reporting.
- `datamind_demo.py`: interactive terminal interface.

`ask(question)` returns a dictionary with `answer`, `sql`, `columns`, `rows`, `query_id`, `assumptions`, `warnings`, and `row_count`. Greetings, identity questions, and detected ambiguous questions return without contacting Snowflake. For database errors the validated SQL remains available, while the result and query ID remain empty and the answer reports failure.

## Tests

Run `pytest -q tests`. Unit tests mock the model and Snowflake calls, so they need no credentials or network access. The standalone `snowflake_test.py` is a live connection diagnostic and is not part of the automated unit suite.

## Reproducible demo flow

1. Start Ollama and confirm the configured model is available (`ollama list`).
2. Configure the four Snowflake environment variables for an account that can read the sample CUSTOMER table.
3. Run `python datamind_demo.py`.
4. Try `hello` (no query), `Who are the best customers?` (clarification), then `Show 5 customers in the BUILDING segment` (validated query and actual results).
5. Record the displayed SQL and Snowflake query ID; enter `exit` to finish.

## Limitations

This milestone supports only a conservative subset of SELECT against the one configured table and four columns. Joins, subqueries, window functions, wildcard selection, arbitrary functions, and additional tables/columns are rejected. Ambiguity detection is intentionally basic and cannot cover every natural-language phrasing. `LIMIT 100` bounds returned rows, not the amount of work a Snowflake query may perform; a 30-second Snowflake statement timeout is configured. A live demo requires working local Ollama and Snowflake credentials.
