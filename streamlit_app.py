import os
import streamlit as st
import requests
import pandas as pd
from datetime import datetime

API_URL = os.environ.get("API_URL", "http://api:8080")

st.set_page_config(
    page_title="AP Invoice Processor",
    page_icon="📄",
    layout="wide",
)

import os

API_URL = os.environ.get("API_URL", "http://api:8080")

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stat-card {
        background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;
        padding: 20px; text-align: center;
    }
    .stat-num { font-size: 2.2rem; font-weight: 700; margin: 0; }
    .stat-label { color: #64748b; font-size: 0.85rem; margin: 0; }
    .approved { color: #16a34a; }
    .rejected { color: #dc2626; }
    .pending  { color: #d97706; }
    .synced   { color: #2563eb; }
    div[data-testid="stHorizontalBlock"] > div { padding: 4px 8px; }
</style>
""", unsafe_allow_html=True)

st.title("📄 AP Invoice Processor")
st.caption("Automated invoice intake · validation · approval · QuickBooks sync")

# ── Fetch invoices ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=10)
def fetch_invoices():
    try:
        r = requests.get(f"{API_URL}/invoices/", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Cannot reach API: {e}")
        return []

invoices = fetch_invoices()

# ── Stats row ─────────────────────────────────────────────────────────────────
total     = len(invoices)
pending   = sum(1 for i in invoices if i.get("status") == "pending")
approved  = sum(1 for i in invoices if i.get("status") == "approved")
rejected  = sum(1 for i in invoices if i.get("status") == "rejected")
synced    = sum(1 for i in invoices if i.get("qb_bill_id") and not str(i.get("qb_bill_id","")).startswith("MOCK"))
total_amt = sum(float(i.get("total_amount", 0) or 0) for i in invoices)

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1:
    st.markdown(f'<div class="stat-card"><p class="stat-num">{total}</p><p class="stat-label">Total Invoices</p></div>', unsafe_allow_html=True)
with c2:
    st.markdown(f'<div class="stat-card"><p class="stat-num pending">{pending}</p><p class="stat-label">Pending</p></div>', unsafe_allow_html=True)
with c3:
    st.markdown(f'<div class="stat-card"><p class="stat-num approved">{approved}</p><p class="stat-label">Approved</p></div>', unsafe_allow_html=True)
with c4:
    st.markdown(f'<div class="stat-card"><p class="stat-num rejected">{rejected}</p><p class="stat-label">Rejected</p></div>', unsafe_allow_html=True)
with c5:
    st.markdown(f'<div class="stat-card"><p class="stat-num synced">{synced}</p><p class="stat-label">QB Synced</p></div>', unsafe_allow_html=True)
with c6:
    st.markdown(f'<div class="stat-card"><p class="stat-num">${total_amt:,.2f}</p><p class="stat-label">Total Value</p></div>', unsafe_allow_html=True)

st.markdown("---")

# ── Upload ─────────────────────────────────────────────────────────────────────
with st.expander("📤 Upload New Invoice", expanded=not invoices):
    uploaded = st.file_uploader("Drop a PDF or image invoice", type=["pdf", "png", "jpg", "jpeg"])
    if uploaded:
        if st.button("Process Invoice", type="primary"):
            with st.spinner("Extracting data & validating..."):
                try:
                    r = requests.post(
                        f"{API_URL}/upload",
                        files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                        timeout=60,
                    )
                    r.raise_for_status()
                    data = r.json()
                    st.success(f"✅ Invoice processed! ID: {data.get('id', '—')} · Vendor: {data.get('vendor_name', '—')} · Amount: ${data.get('total_amount', 0):,.2f}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Upload failed: {e}")

# ── Filters ────────────────────────────────────────────────────────────────────
col_f1, col_f2 = st.columns([2, 4])
with col_f1:
    status_filter = st.selectbox("Filter by status", ["All", "pending", "approved", "rejected"])
with col_f2:
    search = st.text_input("Search vendor / filename")

filtered = invoices
if status_filter != "All":
    filtered = [i for i in filtered if i.get("status") == status_filter]
if search:
    s = search.lower()
    filtered = [i for i in filtered if s in str(i.get("vendor_name","")).lower() or s in str(i.get("filename","")).lower()]

# ── Invoice table ──────────────────────────────────────────────────────────────
st.subheader(f"Invoices ({len(filtered)})")

if not filtered:
    st.info("No invoices found. Upload one above.")
else:
    for inv in sorted(filtered, key=lambda x: x.get("created_at",""), reverse=True):
        inv_id  = inv.get("id", "")
        vendor  = inv.get("vendor_name") or inv.get("vendor") or "Unknown Vendor"
        amount  = float(inv.get("total_amount", 0) or 0)
        curr    = inv.get("currency", "CAD")
        status  = inv.get("status", "pending")
        fname   = inv.get("filename", "")
        score   = inv.get("validation_score") or inv.get("score")
        qb_id   = inv.get("qb_bill_id", "")
        inv_num = inv.get("invoice_number") or inv.get("invoice_no") or "—"
        inv_dt  = inv.get("invoice_date") or inv.get("date") or "—"

        status_emoji = {"approved": "✅", "rejected": "❌", "pending": "⏳"}.get(status, "⏳")
        qb_badge = f"🔵 QB: {qb_id[:12]}..." if qb_id and not str(qb_id).startswith("MOCK") else ("🟡 Mock" if str(qb_id).startswith("MOCK") else "⬜ Not synced")

        with st.container(border=True):
            row1, row2 = st.columns([5, 3]), st.columns([5, 3])
            with row1[0]:
                st.markdown(f"**{vendor}** &nbsp;&nbsp; `{fname}`")
                st.caption(f"Invoice #{inv_num} · {inv_dt} · ID: {inv_id[:8]}...")
            with row1[1]:
                st.markdown(f"### {curr} {amount:,.2f}")

            with row2[0]:
                badge_col, score_col, qb_col = st.columns(3)
                with badge_col:
                    st.markdown(f"{status_emoji} **{status.upper()}**")
                with score_col:
                    if score is not None:
                        color = "green" if float(score) >= 80 else "orange" if float(score) >= 50 else "red"
                        st.markdown(f":{color}[Score: {score}%]")
                with qb_col:
                    st.markdown(qb_badge)

            with row2[1]:
                if status == "pending":
                    btn_a, btn_r = st.columns(2)
                    with btn_a:
                        if st.button("✅ Approve", key=f"a_{inv_id}", use_container_width=True):
                            try:
                                requests.get(f"{API_URL}/invoices/{inv_id}/approve", timeout=10)
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
                    with btn_r:
                        if st.button("❌ Reject", key=f"r_{inv_id}", use_container_width=True):
                            try:
                                requests.get(f"{API_URL}/invoices/{inv_id}/reject", timeout=10)
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
                else:
                    st.caption("Action complete")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("AP Invoice Processor · Powered by OpenAI + Google Document AI + QuickBooks Online")
if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()
