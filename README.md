# AP Invoice Processor

Automated invoice intake pipeline: PDF upload -> OCR -> extraction -> validation -> email approval -> QuickBooks bill submission.

The project is containerized for local development with a FastAPI backend and a Streamlit dashboard.

## Features

- PDF invoice ingestion through the API and Streamlit dashboard
- OCR using Google Document AI
- Regex-first extraction with OpenAI fallback for vendor, amount, line items, and dates
- Validation engine for missing fields, amount mismatches, date issues, and anomalies
- Email approval workflow with one-click approve/reject links
- QuickBooks Online bill submission after approval
- Google Sheets audit logging service
- Streamlit dashboard for invoice status and QuickBooks sync visibility
- Docker Compose setup for consistent local development

## Architecture

Streamlit UI (8502)
        |
        v
FastAPI backend (host 8082, container 8080)
        |
        +--> Google Document AI OCR
        +--> Field extraction
        +--> Validation
        +--> Email approval
        +--> QuickBooks sync
        +--> Google Sheets audit logging
