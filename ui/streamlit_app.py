"""
ui.streamlit_app
----------------
Streamlit front-end for the OCR Invoice Processor.

Upload a PDF invoice, track processing status, and view
extracted + validated results — all in the browser.

Sources:
- Streamlit documentation:
  https://docs.streamlit.io/
- Streamlit file uploader:
  https://docs.streamlit.io/library/api-reference/widgets/st.file_uploader
- Python requests library:
  https://docs.python-requests.org/
"""

import time
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="OCR Invoice Processor",
    page_icon="🧾",
    layout="wide",
)

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🧾 OCR Invoice Processor")
st.caption("Powered by Google Document AI + GPT-4o")
st.divider()

# ── Sidebar — Invoice History ─────────────────────────────────────────────────
with st.sidebar:
    st.header("📋 Invoice History")
    status_filter = st.selectbox(
        "Filter by status",
        ["All", "ingested", "ocr_start", "ocr_done",
         "extracting", "validating", "completed", "failed"],
    )
    if st.button("🔄 Refresh"):
        st.rerun()

    try:
        params = {} if status_filter == "All" else {"status": status_filter}
        resp   = requests.get(f"{API_BASE}/invoices/", params=params, timeout=5)
        if resp.status_code == 200:
            data     = resp.json()
            invoices = data.get("invoices", [])
            st.caption(f"{data.get('count', 0)} invoice(s)")
            for inv in invoices:
                flag  = inv.get("flag") or "—"
                emoji = {"pass": "✅", "warning": "⚠️", "fail": "❌"}.get(flag, "⏳")
                with st.expander(f"{emoji} {inv['file_name']} — {inv['status']}"):
                    st.write(f"**ID:** `{inv['document_id']}`")
                    st.write(f"**Vendor:** {inv.get('vendor') or '—'}")
                    st.write(f"**Total:** {inv.get('total_amount') or '—'}")
                    st.write(f"**Uploaded:** {inv.get('uploaded') or '—'}")
        else:
            st.warning("Could not reach API.")
    except requests.exceptions.ConnectionError:
        st.error("API is not running. Start it with: uvicorn app.main:app --reload")

# ── Main — Upload ─────────────────────────────────────────────────────────────
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📤 Upload Invoice")
    uploaded_file = st.file_uploader(
        "Choose a PDF invoice (max 20 MB)",
        type=["pdf"],
        accept_multiple_files=False,
    )

    if uploaded_file:
        if st.button("🚀 Process Invoice", type="primary"):
            with st.spinner("Uploading and starting pipeline..."):
                try:
                    resp = requests.post(
                        f"{API_BASE}/invoices/upload",
                        files={"file": (uploaded_file.name, uploaded_file, "application/pdf")},
                        timeout=30,
                    )
                    if resp.status_code == 202:
                        result = resp.json()
                        doc_id = result["document_id"]
                        st.success(f"✅ Accepted! Document ID: `{doc_id}`")
                        st.session_state["active_doc_id"] = doc_id
                    else:
                        st.error(f"Upload failed: {resp.json().get('detail', resp.text)}")
                except requests.exceptions.ConnectionError:
                    st.error("Cannot connect to API. Is it running?")

with col2:
    st.subheader("📊 Processing Status")

    doc_id_input = st.text_input(
        "Document ID",
        value=st.session_state.get("active_doc_id", ""),
        placeholder="Paste document_id here or upload above",
    )

    if doc_id_input:
        # ── Status polling ────────────────────────────────────────────────────
        try:
            status_resp = requests.get(
                f"{API_BASE}/invoices/{doc_id_input}", timeout=5
            )
            if status_resp.status_code == 200:
                status_data    = status_resp.json()
                current_status = status_data["status"]

                STATUS_STEPS = [
                    "ingested", "ocr_start", "ocr_done",
                    "extracting", "validating", "completed",
                ]
                step_idx = (
                    STATUS_STEPS.index(current_status)
                    if current_status in STATUS_STEPS else -1
                )

                st.progress(
                    max(0, step_idx) / (len(STATUS_STEPS) - 1),
                    text=f"Status: **{current_status.upper()}**",
                )

                if current_status == "failed":
                    err = status_data.get("error", {})
                    st.error(
                        f"❌ Failed at stage: **{err.get('stage', 'unknown')}**\n\n"
                        f"{err.get('message', '')}"
                    )

                ts = status_data.get("timestamps", {})
                with st.expander("⏱ Timestamps"):
                    for k, v in ts.items():
                        if v:
                            st.write(f"**{k}:** {v}")

                # ── Auto-refresh while processing ─────────────────────────────
                if current_status not in ("completed", "failed"):
                    time.sleep(3)
                    st.rerun()

            elif status_resp.status_code == 404:
                st.warning("Invoice not found. Check the document ID.")
            else:
                st.error(f"API error: {status_resp.status_code}")

        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to API.")

# ── Results ───────────────────────────────────────────────────────────────────
st.divider()
st.subheader("📋 Extracted Results")

result_doc_id = st.text_input(
    "Document ID for results",
    value=st.session_state.get("active_doc_id", ""),
    placeholder="Paste document_id",
    key="results_input",
)

if result_doc_id and st.button("📥 Load Results"):
    try:
        res = requests.get(
            f"{API_BASE}/invoices/{result_doc_id}/results", timeout=10
        )
        if res.status_code == 200:
            data = res.json()

            # ── Header fields ─────────────────────────────────────────────────
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Vendor",         data.get("vendor")         or "—")
            r2.metric("Invoice #",      data.get("invoice_number") or "—")
            r3.metric("Invoice Date",   data.get("invoice_date")   or "—")
            r4.metric("Due Date",       data.get("due_date")       or "—")

            r5, r6, r7, r8 = st.columns(4)
            r5.metric("Subtotal",    f"${data.get('subtotal')     or 0:.2f}")
            r6.metric("Tax",         f"${data.get('tax')          or 0:.2f}")
            r7.metric("Total",       f"${data.get('total_amount') or 0:.2f}")
            r8.metric("Currency",    data.get("currency")          or "USD")

            # ── Line items ────────────────────────────────────────────────────
            st.subheader("📦 Line Items")
            line_items = data.get("line_items", [])
            if line_items:
                st.dataframe(line_items, use_container_width=True)
            else:
                st.info("No line items extracted.")

            # ── Validation ────────────────────────────────────────────────────
            st.subheader("🔍 Validation")
            v = data.get("validation")
            if v:
                flag  = v.get("flag", "—")
                score = v.get("score", 0)
                color = {"pass": "✅", "warning": "⚠️", "fail": "❌"}.get(flag, "❓")
                st.write(f"{color} **Flag:** {flag.upper()}  |  **Score:** {score:.0%}")
                issues = v.get("issues", [])
                if issues:
                    for issue in issues:
                        st.warning(issue)
                else:
                    st.success("All validation checks passed.")
            else:
                st.info("Validation not yet complete.")

        elif res.status_code == 409:
            st.info(f"Still processing: {res.json().get('detail')}")
        elif res.status_code == 404:
            st.warning("Invoice not found.")
        else:
            st.error(f"Error: {res.json().get('detail', res.text)}")

    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to API.")
