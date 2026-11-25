"""
AWS FinOps Agent — configuration.
Edit this file before running the agent for the first time.
"""
import os

# ── Anthropic ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_ANTHROPIC_API_KEY")
CLAUDE_MODEL      = "claude-sonnet-4-6"   # swap to "claude-haiku-4-5-20251001" to cut costs

# ── CUR file ───────────────────────────────────────────────────────────────────
CUR_DIR = r"C:\Apps\FinOps-AWS\CUR"      # folder watched for new CUR files
# Agent picks the newest .xlsx / .csv in this folder each run.
# If the same file is re-uploaded it is safe — ingestor upserts.

# ── SQLite DB ──────────────────────────────────────────────────────────────────
# Defaults to aws_finops.db next to this file's parent (aws_finops_standalone/).
# Override with an absolute path if the DB lives elsewhere.
DB_PATH = os.environ.get("AWS_DB_PATH", "")

# ── Teams notification ─────────────────────────────────────────────────────────
TEAMS_EMAIL       = "28cedabb.CochlearLtd.onmicrosoft.com@emea.teams.ms"
SMTP_HOST         = "smtp.cochlear.com"
SMTP_PORT         = 25
SMTP_FROM         = "aws-finops-agent@cochlear.com"   # adjust if relay requires a valid sender
SMTP_USE_TLS      = False
SMTP_USER         = ""   # leave blank — internal relay, no auth
SMTP_PASSWORD     = ""

# ── Agent behaviour ────────────────────────────────────────────────────────────
ANOMALY_THRESHOLD_PCT  = 15   # flag workload if week-on-week change exceeds this %
DASHBOARD_URL          = "http://your-server/AWSFinOps"   # link in Teams message
