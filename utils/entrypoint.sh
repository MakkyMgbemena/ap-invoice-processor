#!/bin/bash
set -e

# ── GCP credentials ───────────────────────────────────────────────────────────
# Mount your service account JSON at runtime and set this variable:
# docker run -v /path/to/key.json:/secrets/gcp-key.json \
#            -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp-key.json ...

# ── FastAPI backend ───────────────────────────────────────────────────────────
echo "[entrypoint] Starting FastAPI on port 8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &

# ── Streamlit frontend ────────────────────────────────────────────────────────
echo "[entrypoint] Starting Streamlit on port 8501..."
exec streamlit run ui/streamlit_app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true
