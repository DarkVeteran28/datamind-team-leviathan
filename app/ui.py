"""Streamlit interface for the DataMind question pipeline."""
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# `streamlit run app/ui.py` places app/ first on sys.path. Add src/ so the
# checkout works directly from its root without requiring an editable install.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from datamind.pipeline import ask


def _safe_display(value):
    """Hide configured credentials if an upstream warning echoes one."""
    text = str(value)
    for name in ("SNOWFLAKE_PASSWORD", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE"):
        secret = os.getenv(name)
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


st.set_page_config(
    page_title="DataMind",
    page_icon="📊",
    layout="wide",
)

st.title("📊 DataMind")
st.caption("Talk to your data. Verify every answer.")
st.markdown("Ask questions about the Snowflake sample dataset using natural language.")

question = st.text_area(
    "Your question",
    placeholder="e.g. Show the five customers with the highest account balances.",
    height=100,
)

st.markdown("**Try an example**")
examples = [
    "Show the five customers with the highest account balances.",
    "Show customers in the BUILDING market segment.",
    "Count customers by market segment.",
]

selected = st.pills(
    "Example questions",
    examples,
    selection_mode="single",
    label_visibility="collapsed",
)
if selected:
    question = selected

if st.button("Analyze data", type="primary", use_container_width=True):
    if not question.strip():
        st.warning("Enter a question first.")
    else:
        try:
            with st.spinner("Asking DataMind and querying Snowflake…"):
                result = ask(question.strip())
        except Exception:
            # Avoid displaying raw exception text that could contain secrets.
            st.error("DataMind could not process this request. Check the model and data connection, then try again.")
        else:
            clarification = any(
                "clarification required" in str(warning).lower()
                for warning in result.get("warnings", [])
            )
            if clarification:
                st.info("Clarification needed: " + _safe_display(result.get("answer", "Please clarify your question.")))
            elif result.get("query_id"):
                st.success(_safe_display(result.get("answer", "")))
            else:
                st.write(_safe_display(result.get("answer", "")))

            sql = result.get("sql")
            if sql:
                with st.expander("SQL", expanded=False):
                    st.code(_safe_display(sql), language="sql")

            columns = result.get("columns") or []
            rows = result.get("rows") or []
            st.metric("Rows returned", result.get("row_count", len(rows)))
            if columns and rows:
                st.dataframe(pd.DataFrame(rows, columns=columns), use_container_width=True, hide_index=True)
            elif columns:
                st.info("Snowflake returned no rows.")

            if result.get("query_id"):
                st.caption("Snowflake query ID: " + _safe_display(result["query_id"]))
            assumptions = result.get("assumptions") or []
            if assumptions:
                with st.expander("Model assumptions"):
                    for assumption in assumptions:
                        st.write("• " + _safe_display(assumption))
            for warning in result.get("warnings") or []:
                st.warning(_safe_display(warning))
