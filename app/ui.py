"""Streamlit trust console for DataMind's existing question pipeline."""
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# `streamlit run app/ui.py` places app/ first on sys.path. Add src/ so the
# repository works from its root without requiring an editable installation.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from datamind import llm
from datamind.pipeline import ask


REPOSITORY = "https://github.com/ZERODAY-2026/Leviathan"
README = f"{REPOSITORY}/blob/main/README.md"
DATASETS = f"{REPOSITORY}/blob/main/DATASETS.md"
EVALUATION = f"{REPOSITORY}/blob/main/docs/EVALUATION_EVIDENCE.md"
SNOWFLAKE_HISTORY = "https://docs.snowflake.com/en/user-guide/ui-query-history"
SAMPLE_DATA = "https://docs.snowflake.com/en/user-guide/sample-data"
OLLAMA_DOCS = "https://docs.ollama.com/"
DATA_SOURCE = "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER"
EXAMPLES = [
    "Show the five customers with the highest account balances.",
    "Count customers by market segment.",
    "Show customers in the BUILDING market segment.",
    "Who are the best customers?",
]
STAGES = (
    ("validation", "SQL validation", "Passing establishes compliance with implemented policy checks; it does not prove that SQL answers the intended question."),
    ("execution", "Snowflake execution", "Success establishes that Snowflake ran the query; it does not prove that the interpretation is correct."),
    ("verification", "Answer consistency", "The current verifier checks result and answer consistency only, not semantic correctness."),
)


def _safe_display(value):
    """Redact configured credential and private configuration values."""
    text = str(value)
    sensitive_names = {
        "SNOWFLAKE_PASSWORD", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER",
        "SNOWFLAKE_WAREHOUSE", "OLLAMA_URL",
    }
    for name, secret in sorted(os.environ.items(), key=lambda item: len(item[1]), reverse=True):
        if secret and (name in sensitive_names or any(
            marker in name.upper() for marker in ("PASSWORD", "TOKEN", "SECRET", "PRIVATE_KEY")
        )):
            text = text.replace(secret, "[redacted]")
    return text


def _status(value):
    if not isinstance(value, dict):
        return "Unknown"
    raw = value.get("status")
    if not isinstance(raw, str) or not raw.strip():
        return "Unknown"
    return raw.replace("_", " ").title()


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _show_state(label, status, detail=None):
    status_text = _status({"status": status})
    line = f"**{label}: {status_text}**"
    if detail:
        line += " — " + _safe_display(detail)
    if status == "passed" or status == "succeeded":
        st.success(line)
    elif status == "failed" or status == "rejected":
        st.error(line)
    elif status == "skipped" or status == "not_run":
        st.info(line)
    else:
        st.warning(line)


def _render_evidence(result):
    st.subheader("Trust Mode evidence")
    for key, title, caveat in STAGES:
        evidence = result.get(key)
        with st.container(border=True):
            st.markdown(f"#### {title}")
            if not isinstance(evidence, dict):
                st.info("Not available")
                st.caption(caveat)
                continue
            _show_state(title, evidence.get("status", "unknown"))
            checks = evidence.get("checks")
            if isinstance(checks, list) and checks:
                for check in checks:
                    if not isinstance(check, dict):
                        st.info("Not available")
                        continue
                    check_name = _safe_display(check.get("name", "Unnamed check"))
                    check_status = check.get("status", "unknown")
                    check_detail = _safe_display(check.get("detail", ""))
                    _show_state(check_name, check_status, check_detail)
                    if check.get("name") == "semantic_correctness" and check_status == "not_run":
                        st.caption("Semantic correctness: Not run by this deterministic consistency verifier.")
            else:
                st.info("Not available" if checks is None else "No checks were recorded.")
            st.caption(caveat)


def _make_frame(columns, rows):
    if not isinstance(columns, (list, tuple)) or not isinstance(rows, (list, tuple)):
        return None
    if not columns or not rows:
        return None
    if any(not isinstance(row, (list, tuple)) or len(row) != len(columns) for row in rows):
        return None
    try:
        return pd.DataFrame(rows, columns=columns)
    except (TypeError, ValueError):
        return None


def _render_result(result):
    if not isinstance(result, dict):
        st.error("DataMind returned an invalid response.")
        return

    answer = _safe_display(result.get("answer") or "No answer text was returned.")
    warnings = result.get("warnings")
    warnings = warnings if isinstance(warnings, (list, tuple)) else []
    clarification = _mapping(result.get("clarification"))
    clarification_required = clarification.get("required") is True or (
        "clarification" not in result and any(
            "clarification required" in str(item).casefold() for item in warnings
        )
    )
    if clarification_required:
        st.info("### Clarification needed\n\n" + answer)
        options = clarification.get("options")
        if isinstance(options, list) and options:
            st.markdown("**Available interpretations**")
            for option in options:
                label = option.get("label") if isinstance(option, dict) else option
                if label:
                    st.markdown("- " + _safe_display(label))
        if not result.get("sql") and not result.get("query_id"):
            st.caption("No SQL was executed and no Snowflake query ID was created for this response.")
    elif _mapping(result.get("verification")).get("status") == "failed":
        st.error("Answer consistency check failed. Inspect the evidence and returned rows before relying on the answer.")
        st.write(answer)
    elif _mapping(result.get("execution")).get("status") == "failed":
        st.error(answer)
    elif result.get("query_id"):
        st.success(answer)
    else:
        st.write(answer)

    rows = result.get("rows")
    columns = result.get("columns")
    rows = rows if isinstance(rows, (list, tuple)) else []
    row_count = result.get("row_count")
    if not isinstance(row_count, int) or isinstance(row_count, bool):
        row_count = len(rows) if "rows" in result else "Unknown"
    validation_status = _mapping(result.get("validation")).get("status", "unknown")
    execution_status = _mapping(result.get("execution")).get("status", "unknown")
    verification_status = _mapping(result.get("verification")).get("status", "unknown")
    metrics = st.columns(4)
    metrics[0].metric("Rows returned", row_count)
    metrics[1].metric("SQL validation", _status({"status": validation_status}))
    metrics[2].metric("Snowflake execution", _status({"status": execution_status}))
    metrics[3].metric("Answer consistency", _status({"status": verification_status}))

    st.subheader("Results explorer")
    frame = _make_frame(columns, rows)
    if frame is not None:
        display_frame = frame.copy()
        display_frame.columns = [_safe_display(column) for column in display_frame.columns]
        for column in display_frame.columns:
            display_frame[column] = display_frame[column].map(
                lambda value: _safe_display(value) if isinstance(value, str) else value
            )
        st.dataframe(display_frame, use_container_width=True, hide_index=True)
        csv_bytes = display_frame.to_csv(index=False).encode("utf-8")
        st.download_button("Download returned rows as CSV", csv_bytes,
                           file_name="datamind-results.csv", mime="text/csv",
                           key="download_results")
    elif rows and columns:
        st.warning("Returned rows do not match the column metadata; table and CSV are unavailable.")
    elif _mapping(result.get("execution")).get("status") == "succeeded":
        st.info("The query succeeded and returned no rows.")
    elif not result.get("columns") and not result.get("rows"):
        st.caption("No result rows are available for this response.")
    if isinstance(columns, (list, tuple)) and columns:
        st.caption(f"Returned row count: {row_count}")
    if _mapping(result.get("execution")).get("status") == "succeeded":
        st.caption("Results may be limited by the enforced maximum of 100 rows; this does not indicate the total number of matching records.")

    st.subheader("SQL inspection")
    sql = result.get("sql")
    validation = result.get("validation")
    if sql:
        if isinstance(validation, dict) and validation.get("status") == "rejected":
            st.warning("SQL proposal from the model — rejected before execution")
        elif isinstance(validation, dict) and validation.get("status") == "passed":
            st.caption("Validated SQL sent to Snowflake")
        else:
            st.caption("SQL proposal; execution status is not established")
        st.code(_safe_display(sql), language="sql")
    else:
        st.info("No SQL was generated for this response.")
        if isinstance(validation, dict) and validation.get("status") == "rejected":
            st.caption("SQL validation rejected the proposal before execution.")

    _render_evidence(result)

    st.subheader("Snowflake execution receipt")
    query_id = result.get("query_id")
    if query_id:
        st.code(_safe_display(query_id), language="text")
        st.markdown(
            f"Search this query ID in Snowsight → **Monitoring → Query History**. "
            f"[Snowflake Query History documentation]({SNOWFLAKE_HISTORY}). Query History is the independent place to verify the SQL recorded by Snowflake."
        )
    elif clarification_required:
        st.info("No receipt: clarification was requested before SQL generation or Snowflake execution.")
    elif isinstance(validation, dict) and validation.get("status") == "rejected":
        st.info("No receipt: SQL validation rejected the proposal before execution.")
    elif _mapping(result.get("execution")).get("status") == "failed":
        st.info("No successful execution receipt: Snowflake execution failed. A query ID may be unavailable.")
    elif result.get("warnings") and result.get("sql") is None:
        st.info("No receipt: SQL generation or request processing did not produce an executable query.")
    else:
        st.info("No Snowflake query ID is available for this response.")

    st.subheader("Assumptions and warnings")
    assumptions = result.get("assumptions")
    if isinstance(assumptions, (list, tuple)) and assumptions:
        st.markdown("**Assumptions**")
        for assumption in assumptions:
            st.markdown("- " + _safe_display(assumption))
    elif isinstance(assumptions, str) and assumptions:
        st.markdown("**Assumptions**\n\n- " + _safe_display(assumptions))
    else:
        st.caption("No assumptions were returned.")
    if warnings:
        for warning in warnings:
            warning_text = _safe_display(warning)
            if clarification_required and "clarification" in warning_text.casefold():
                st.warning(warning_text)
            else:
                st.warning(warning_text)
    else:
        st.caption("No warnings were returned.")


def _record_history(question, result):
    history = st.session_state.get("history", [])
    entry = {
        "question": _safe_display(question),
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "row_count": result.get("row_count", "Unknown"),
        "execution_status": _mapping(result.get("execution")).get("status", "not_run"),
        "query_id": _safe_display(result.get("query_id")) if result.get("query_id") else None,
        "result": result,
    }
    st.session_state.history = [entry] + history[:19]


def _load_example():
    selected = st.session_state.get("example_choice")
    if selected in EXAMPLES:
        st.session_state.question_input = selected


st.set_page_config(page_title="DataMind Trust Console", page_icon="📊", layout="wide")
st.markdown("""
<style>
    .stApp { background: #0b1220; color: #e5eef7; }
    [data-testid="stSidebar"] { background: #101a2b; }
    [data-testid="stMetric"] { background: #111d30; border: 1px solid #21334b; padding: 14px; border-radius: 10px; }
    h1, h2, h3 { letter-spacing: -0.02em; }
    code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, monospace !important; }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-color: #253850; }
</style>
""", unsafe_allow_html=True)

if "question_input" not in st.session_state:
    st.session_state.question_input = ""
if "active_result" not in st.session_state:
    st.session_state.active_result = None
if "history" not in st.session_state:
    st.session_state.history = []

with st.sidebar:
    st.markdown("## 📊 DataMind")
    st.caption("Trust Console")
    st.markdown(f"**Data source**  \n`{DATA_SOURCE}`")
    st.markdown(f"**SQL model**  \n`{_safe_display(llm.MODEL)}` · local Ollama")
    st.markdown("**Row policy**  \nMaximum 100 returned rows")
    st.divider()
    st.markdown("### Project links")
    st.markdown(f"- [Repository]({REPOSITORY})\n- [README]({README})\n- [Dataset and attribution]({DATASETS})\n- [Evaluation evidence]({EVALUATION})\n- [Sample datasets]({SAMPLE_DATA})\n- [Ollama docs]({OLLAMA_DOCS})")
    st.divider()
    st.markdown("### Diagnostics")
    required_env = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_WAREHOUSE")
    present_count = sum(bool(os.getenv(name)) for name in required_env)
    st.caption(f"Snowflake configuration: {present_count}/{len(required_env)} required values present; connection not checked.")
    st.caption("Ollama: local runtime configured; connection not checked.")

st.title("📊 DataMind Trust Console")
st.caption("Ask in natural language. Inspect every result.")
st.markdown(f"Current configured data source: `{DATA_SOURCE}` · Gemma `{_safe_display(llm.MODEL)}` through local Ollama.")

st.subheader("Natural-language query composer")
with st.form("query_form", clear_on_submit=False):
    st.text_area(
        "Your question", key="question_input",
        placeholder="For example: Show the five customers with the highest account balances.",
        height=120,
    )
    submitted = st.form_submit_button("Analyze data", type="primary", use_container_width=True)

st.markdown("**Example questions**")
st.selectbox("Choose an example to load", ["Choose an example…"] + EXAMPLES,
             key="example_choice", label_visibility="collapsed")
st.button("Load example", key="load_example", on_click=_load_example)

if submitted:
    question = st.session_state.get("question_input", "")
    if not isinstance(question, str) or not question.strip():
        st.warning("Enter a question first.")
    else:
        try:
            with st.spinner("Generating SQL and waiting for Snowflake results…"):
                result = ask(question.strip())
        except Exception:
            st.error("DataMind could not process this request. Check local model and Snowflake setup, then try again.")
        else:
            st.session_state.active_result = result
            _record_history(question.strip(), result)

history = st.session_state.get("history", [])
if history:
    st.divider()
    st.subheader("Session history")
    history_labels = [
        f"{item['timestamp']} · {item['question'][:80]} · {_status({'status': item.get('execution_status')})} · {item.get('row_count', 'Unknown')} rows"
        for item in history
    ]
    history_selection = st.selectbox("Select a previous response to review", ["Current response"] + history_labels, key="history_selection")
    history_buttons = st.columns([1, 5])
    if history_buttons[0].button("Review selected", key="review_history") and history_selection != "Current response":
        index = history_labels.index(history_selection)
        st.session_state.active_result = history[index]["result"]
        st.rerun()
    if history_buttons[0].button("Clear history", key="clear_history"):
        st.session_state.history = []
        st.session_state.active_result = None
        st.rerun()
    for item in history:
        st.caption(f"{item['timestamp']} · {item['question']} · Rows: {item.get('row_count', 'Unknown')} · Execution: {_status({'status': item.get('execution_status')})} · Query ID: {item.get('query_id') or 'None'}")

if st.session_state.get("active_result") is not None:
    st.divider()
    st.subheader("Answer and result overview")
    _render_result(st.session_state.active_result)
