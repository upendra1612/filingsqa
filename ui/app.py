"""FilingsQA demo page (Streamlit). Calls the FilingsQA API.

Local:   API_URL=http://localhost:8000 streamlit run ui/app.py
Cloud:   Streamlit Community Cloud, with API_URL set in the app's secrets.
"""

import os

import requests
import streamlit as st

REPO = "https://github.com/upendra1612/filingsqa"
# Questions the baseline answered correctly on the smoke set (evals/results), plus one
# the filings can't answer, to show the system declining instead of guessing.
EXAMPLES = [
    "What were net sales of Apple's Greater China segment in fiscal 2025?",
    "In which business segments does Goldman Sachs manage and report its activities "
    "in its 2025 10-K?",
    "By what percentage did Coca-Cola's net income attributable to shareowners change "
    "in 2025 compared with 2024?",
    "What was Coca-Cola's market share in India in 2025?",
]


def api_url() -> str:
    try:
        return st.secrets["API_URL"].rstrip("/")
    except (KeyError, FileNotFoundError):
        return os.environ.get("API_URL", "http://localhost:8000").rstrip("/")


st.set_page_config(page_title="FilingsQA", page_icon="📄", layout="centered")
st.title("FilingsQA")
st.caption(
    "Ask a question about the 10-K filings of 25 US banks, insurers and large companies "
    "(fiscal 2024–2026). Answers cite the filing passages they come from, and the system "
    "says so when the filings don't contain the answer. Not investment advice."
)

if "question" not in st.session_state:
    st.session_state.question = ""

cols = st.columns(2)
for i, example in enumerate(EXAMPLES):
    if cols[i % 2].button(example, key=f"ex{i}", use_container_width=True):
        st.session_state.question = example

question = st.text_input("Your question", key="question", max_chars=300)

if st.button("Ask", type="primary", disabled=len(question.strip()) < 8):
    with st.spinner("Searching the filings… the free server can take up to a minute to wake up."):
        try:
            r = requests.post(f"{api_url()}/ask", json={"question": question}, timeout=180)
        except requests.RequestException:
            st.error("The API could not be reached. Try again in a minute.")
            st.stop()
    if r.status_code != 200:
        detail = (
            r.json().get("detail", r.text)
            if "json" in r.headers.get("content-type", "")
            else r.text
        )
        st.error(f"{detail}" if r.status_code in (429, 503) else f"Error {r.status_code}: {detail}")
        st.stop()
    data = r.json()
    if data["abstained"]:
        st.warning(
            "**Not found in the filings.** The retrieved passages don't contain the answer, "
            "so the system declines rather than guessing."
        )
    else:
        st.markdown(f"### Answer\n{data['answer']}")
    cited = set(data["cited"])
    st.markdown("### Sources")
    for s in data["sources"]:
        mark = "✅ cited" if s["n"] in cited else "retrieved"
        title = (
            f"[{s['n']}] {s['company']} · {s['doc_type']} · fiscal year ending "
            f"{s['period_end']} ({mark})"
        )
        with st.expander(title, expanded=s["n"] in cited):
            st.write(s["excerpt"] + " …")
            if s["url"]:
                st.markdown(f"[Open the filing on sec.gov]({s['url']})")
    st.caption(f"Model: {data['model']} · {data['latency_ms'] / 1000:.1f} s")

st.divider()
st.caption(
    f"How it's measured: a 416-question benchmark built from the SEC's own XBRL data. "
    f"Results, method and failures: [GitHub]({REPO})."
)
