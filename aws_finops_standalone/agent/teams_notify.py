"""Send a weekly FinOps summary to a Microsoft Teams channel via email."""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date

import config


def send_weekly_report(markdown_summary: str, subject: str | None = None) -> None:
    """
    Convert Claude's markdown summary to an HTML email and send it
    to the Teams channel email address.
    """
    if subject is None:
        subject = f"AWS FinOps Weekly Report — {date.today().strftime('%d %b %Y')}"

    html = _markdown_to_html(markdown_summary)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = config.SMTP_FROM
    msg["To"]      = config.TEAMS_EMAIL

    msg.attach(MIMEText(markdown_summary, "plain", "utf-8"))
    msg.attach(MIMEText(html,             "html",  "utf-8"))

    password = config.SMTP_PASSWORD or os.environ.get("SMTP_PASSWORD", "")
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
        smtp.ehlo()
        if config.SMTP_USE_TLS:
            smtp.starttls()
            smtp.ehlo()
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, password)
        smtp.sendmail(config.SMTP_FROM, [config.TEAMS_EMAIL], msg.as_string())

    print(f"[teams_notify] Report sent to {config.TEAMS_EMAIL}")


def _markdown_to_html(text: str) -> str:
    """Minimal markdown → HTML for Teams email rendering."""
    import re

    lines   = text.split("\n")
    out     = []
    in_list = False
    in_code = False

    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                if in_list:
                    out.append("</ul>")
                    in_list = False
                out.append('<pre style="background:#f4f4f4;padding:10px;border-radius:4px;'
                           'font-family:monospace;font-size:13px;overflow-x:auto">')
                in_code = True
            continue

        if in_code:
            out.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            continue

        stripped = line.strip()
        if in_list and not stripped.startswith(("- ", "* ", "• ")):
            out.append("</ul>")
            in_list = False

        if stripped.startswith("### "):
            out.append(f'<h3 style="color:#2B3752;margin:16px 0 6px">{_inline(stripped[4:])}</h3>')
        elif stripped.startswith("## "):
            out.append(f'<h2 style="color:#2B3752;border-bottom:2px solid #F0A500;'
                       f'padding-bottom:4px;margin:20px 0 8px">{_inline(stripped[3:])}</h2>')
        elif stripped.startswith("# "):
            out.append(f'<h1 style="color:#2B3752;margin:0 0 12px">{_inline(stripped[2:])}</h1>')
        elif stripped in ("---", "***", "___"):
            out.append('<hr style="border:none;border-top:1px solid #ddd;margin:12px 0"/>')
        elif stripped.startswith(("- ", "* ", "• ")):
            if not in_list:
                out.append('<ul style="margin:6px 0 6px 20px;padding:0">')
                in_list = True
            item = stripped.lstrip("-*• ").strip()
            out.append(f'<li style="margin:3px 0">{_inline(item)}</li>')
        elif stripped == "":
            out.append("<br/>")
        else:
            out.append(f'<p style="margin:4px 0">{_inline(stripped)}</p>')

    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</pre>")

    body = "\n".join(out)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"/></head>
<body style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1C2333;
             max-width:680px;margin:0 auto;padding:20px">
{body}
<br/>
<p style="font-size:11px;color:#888;border-top:1px solid #eee;padding-top:8px;margin-top:16px">
  AWS FinOps Agent · <a href="{config.DASHBOARD_URL}" style="color:#2B3752">Open dashboard</a>
</p>
</body>
</html>"""


def _inline(text: str) -> str:
    """Apply inline markdown: **bold**, `code`, URLs."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r'<code style="background:#f4f4f4;padding:1px 4px;border-radius:3px">\1</code>', text)
    text = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', text)
    return text
