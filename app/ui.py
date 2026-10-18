
import streamlit as st

st.set_page_config(
    page_title="DataMind",
    page_icon="📊",
    layout="wide",
)

st.title("📊 DataMind")
st.caption("Talk to your data. Verify every answer.")

st.markdown(
    "Ask questions about the Snowflake sample dataset "
    "using natural language."
)

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
        st.info(
            "UI skeleton ready. The live DataMind backend "
            "will be connected in the next checkpoint."
        )
