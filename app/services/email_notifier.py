"""
app.services.email_notifier
---------------------------
Sends an HTML invoice review email with one-click Approve / Reject links.
Links point back to FastAPI GET endpoints — no POST required from the inbox.
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone

from app.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, NOTIFY_EMAIL, BASE_URL

logger = logging.getLogger(__name__)


def send_invoice_notification(invoice) -> None:
    if not all([SMTP_USER, SMTP_PASSWORD, NOTIFY_EMAIL]):
        logger.warning("[EmailNotifier] SMTP credentials not set — skipping.")
        return

    approve_url = f"{BASE_URL}/invoices/{invoice.document_id}/approve"
    reject_url  = f"{BASE_URL}/invoices/{invoice.document_id}/reject"

    flag        = getattr(invoice.validation, "flag",   "unknown") if invoice.validation else "unknown"
    score       = getattr(invoice.validation, "score",  0.0)       if invoice.validation else 0.0
    issues      = getattr(invoice.validation, "issues", [])        if invoice.validation else []
    issues_html = "".join(f"<li>{i}</li>" for i in issues) or "<li>None</li>"
    flag_color  = {"pass": "#16a34a", "warning": "#d97706", "fail": "#dc2626"}.get(str(flag), "#6b7280")

    rows_html = ""
    for item in (invoice.line_items or []):
        rows_html += (
            f"<tr>"
            f"<td style='padding:6px;border-bottom:1px solid #eee;'>{item.name}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #eee;text-align:center;'>{item.quantity}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #eee;text-align:right;'>${item.unit_price}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #eee;text-align:right;'>${item.total}</td>"
            f"</tr>"
        )

    html = f"""
<html><body style='font-family:Arial,sans-serif;background:#f9fafb;padding:24px;'>
<div style='max-width:620px;margin:auto;background:#fff;border-radius:8px;padding:32px;box-shadow:0 2px 8px rgba(0,0,0,0.08);'>

  <h2 style='color:#1e293b;margin-top:0;'>📄 Invoice Review Required</h2>
  <p style='color:#64748b;'>A new invoice has been processed and is awaiting your approval.</p>

  <table style='width:100%;border-collapse:collapse;margin-bottom:24px;'>
    <tr><td style='padding:8px;color:#64748b;width:40%;'>Vendor</td>        <td style='padding:8px;font-weight:bold;'>{invoice.vendor or "—"}</td></tr>
    <tr style='background:#f8fafc;'><td style='padding:8px;color:#64748b;'>Invoice #</td><td style='padding:8px;font-weight:bold;'>{invoice.invoice_number or "—"}</td></tr>
    <tr><td style='padding:8px;color:#64748b;'>Invoice Date</td>            <td style='padding:8px;'>{invoice.invoice_date or "—"}</td></tr>
    <tr style='background:#f8fafc;'><td style='padding:8px;color:#64748b;'>Due Date</td><td style='padding:8px;'>{invoice.due_date or "—"}</td></tr>
    <tr><td style='padding:8px;color:#64748b;'>Subtotal</td>                <td style='padding:8px;'>${invoice.subtotal or "—"}</td></tr>
    <tr style='background:#f8fafc;'><td style='padding:8px;color:#64748b;'>Tax</td><td style='padding:8px;'>${invoice.tax or "—"}</td></tr>
    <tr><td style='padding:8px;color:#64748b;font-weight:bold;'>Total</td>  <td style='padding:8px;font-weight:bold;font-size:1.1em;'>${invoice.total_amount or "—"} {invoice.currency or ""}</td></tr>
  </table>

  <h3 style='color:#1e293b;'>Line Items</h3>
  <table style='width:100%;border-collapse:collapse;margin-bottom:24px;font-size:0.9em;'>
    <thead><tr style='background:#f1f5f9;'>
      <th style='padding:8px;text-align:left;'>Item</th>
      <th style='padding:8px;text-align:center;'>Qty</th>
      <th style='padding:8px;text-align:right;'>Unit Price</th>
      <th style='padding:8px;text-align:right;'>Total</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>

  <h3 style='color:#1e293b;'>Validation</h3>
  <p>Status: <span style='color:{flag_color};font-weight:bold;text-transform:uppercase;'>{flag}</span>
     &nbsp;|&nbsp; Score: <strong>{score:.0%}</strong></p>
  <ul style='color:#64748b;'>{issues_html}</ul>

  <div style='margin-top:32px;text-align:center;'>
    <a href='{approve_url}'
       style='background:#16a34a;color:#fff;padding:14px 32px;border-radius:6px;
              text-decoration:none;font-weight:bold;font-size:1em;margin-right:16px;display:inline-block;'>
      ✅ Approve
    </a>
    <a href='{reject_url}'
       style='background:#dc2626;color:#fff;padding:14px 32px;border-radius:6px;
              text-decoration:none;font-weight:bold;font-size:1em;display:inline-block;'>
      ❌ Reject
    </a>
  </div>

  <p style='color:#94a3b8;font-size:0.8em;margin-top:24px;text-align:center;'>
    Document ID: {invoice.document_id}<br>
    Processed: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
  </p>
</div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"[AP Review] Invoice #{invoice.invoice_number or 'Unknown'} — "
        f"{invoice.vendor or 'Unknown Vendor'} — "
        f"${invoice.total_amount or '0.00'}"
    )
    msg["From"] = SMTP_USER
    msg["To"]   = NOTIFY_EMAIL
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())
        logger.info(f"[EmailNotifier] Sent notification for {invoice.document_id}")
    except Exception as exc:
        logger.error(f"[EmailNotifier] Failed: {exc}")
