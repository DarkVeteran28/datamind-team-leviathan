# PS1 — DataMind: Talk to Your Data

## Problem Statement

Organizations hold large amounts of information in databases, spreadsheets, documents and other sources. Getting a useful answer often takes technical skills, specialised queries or hours of manual searching, so the people who understand the questions best are often the least able to reach the data.

**The challenge:** Create an AI-powered data experience that lets people ask questions in everyday language and get useful answers grounded in the available data, with enough explanation that users trust the response reflects the information actually examined.

**Our approach:** DataMind uses Gemma 3 4B through local Ollama inference to generate SQL, validates the generated SQL with SQLGlot, and executes approved queries against Snowflake. Answers are constructed from the actual returned rows, with the SQL and Snowflake query ID available for verification.

---

# DataMind: Talk to Your Data

DataMind is a local natural-language interface for the Snowflake sample TPC-H `CUSTOMER` table. Gemma 3 4B proposes SQL; a strict SQLGlot validator checks it; only then does the Snowflake client execute it. Results and the Snowflake query ID are returned with the answer.

## Setup

1. Install Python 3.10+ and create/activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`.
3. Install and start Ollama, then fetch the configured model: `ollama pull gemma3:4b`.
4. Copy `.env.example` to `.env` and fill in Snowflake account, user, password, and warehouse values. Keep `.env` private; it is ignored by Git.
5. Run `python datamind_demo.py` for the terminal demo, or `streamlit run app/ui.py` for the web interface.

Optional Ollama configuration: `DATAMIND_MODEL` (default `gemma3:4b`) and `OLLAMA_URL` (default `http://localhost:11434/api/chat`).

## Configuration

Required environment variables are `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, and `SNOWFLAKE_WAREHOUSE`. The database and schema are fixed to `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1`; the allowed columns are `C_CUSTKEY`, `C_NAME`, `C_ACCTBAL`, and `C_MKTSEGMENT`. Credentials are never printed by the CLI.

## Architecture

- `src/datamind/llm.py`: Ollama chat request and JSON response parsing.
- `src/datamind/validator.py`: single SELECT parsing, table/column/function/clause restrictions, and 100-row cap.
- `src/datamind/snowflake_client.py`: credential check, connection, 30-second statement timeout, and result retrieval.
- `src/datamind/pipeline.py`: `ask(question)` orchestration, greetings/capabilities, ambiguity clarification, evidence-based answer, and failure reporting.
- `app/ui.py`: Streamlit interface displaying answers, SQL, rows, query IDs, assumptions and warnings.
- `datamind_demo.py`: interactive terminal interface.

`ask(question)` returns `answer`, `sql`, `columns`, `rows`, `query_id`, `assumptions`, `warnings`, and `row_count`. The answer text is composed from Snowflake-returned columns and row values (or states that the successful query returned no rows); it does not ask the LLM to narrate results. Multi-row answers show up to three returned rows, and the complete result remains in `rows`. SQL and query ID are kept as evidence. Failed SQL generation/validation and failed database execution return warnings and do not claim a successful query. Greetings, identity questions, and detected ambiguous questions return without contacting Snowflake.

## Tests and Evaluation

Run the automated tests:

```bash
python -m pytest -q
```

Run the deterministic mocked evaluation:

```bash
python eval/run_evaluation.py
```

Unit tests mock model and Snowflake calls, so they need no credentials or network access. The evaluation runner reports case-by-case pass/fail for the checked-in mocked examples. These checks measure expected behavior on fixtures, not model accuracy or live Snowflake correctness. The standalone `snowflake_test.py` is a live connection diagnostic and is not part of the automated unit suite.

## Reproducible Demo

1. Start Ollama and confirm the configured model is available with `ollama list`.
2. Configure the four Snowflake environment variables for an account that can read the sample CUSTOMER table.
3. Run `streamlit run app/ui.py`.
4. Ask: `Show five customers with the highest account balances.`
5. Ask: `Count customers by market segment.`
6. Ask: `Who are the best customers?` to demonstrate clarification before querying.
7. Record the displayed SQL and Snowflake query IDs.

The checked-in evaluation examples in `eval/cases.json` include representative returned rows, a `COUNT(*)` aggregate, a segment filter, ambiguity, rejected SQL, an empty result, model/database failures, and a greeting. The results in this fixture are deliberately mocked and must not be mistaken for live CUSTOMER table values.

## Dataset and Attribution

DataMind uses `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER`, accessed through the user's Snowflake account. See [`DATASETS.md`](DATASETS.md) and the [official Snowflake sample-data documentation](https://docs.snowflake.com/en/user-guide/sample-data). The repository does not contain a copy of the dataset.

## Limitations

This milestone supports only a conservative subset of SELECT against one configured table and four columns. Joins, subqueries, window functions, wildcard selection, arbitrary functions, and additional tables/columns are rejected. Ambiguity detection is rule-based and cannot cover every natural-language phrasing; review generated SQL and assumptions where user intent is important. The deterministic evaluation does not measure real model accuracy. `LIMIT 100` bounds returned rows, not the amount of work a Snowflake query may perform; a 30-second Snowflake statement timeout is configured. A live demo requires working local Ollama and Snowflake credentials.

## License

This project is licensed under the MIT License. See `LICENSE`.
