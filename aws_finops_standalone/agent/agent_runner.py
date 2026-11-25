"""
AWS FinOps Agent — weekly runner.

Usage:
    python agent_runner.py              # normal weekly run
    python agent_runner.py --dry-run    # analyse + print report, no email sent
    python agent_runner.py --no-ingest  # skip CUR ingest, re-analyse existing data

Schedule via Windows Task Scheduler (see README below).
"""
import argparse
import glob
import os
import sys
import json
from datetime import date, datetime

# ── Path setup ────────────────────────────────────────────────────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.join(_HERE, "..")
sys.path.insert(0, _PARENT)
sys.path.insert(0, _HERE)

import config

if config.DB_PATH:
    os.environ["AWS_DB_PATH"] = config.DB_PATH

import anthropic
import memory as _mem
import finops_tools as _tools
import teams_notify


# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are the AWS FinOps Agent for Cochlear Ltd.

Your job each week:
1. Use get_available_months to find the most recent month with data.
2. Use get_workload_data for the latest month AND the month before it.
3. For any workload with a significant change (>15% week-on-week or vs budget),
   use get_account_level_spend to identify which AWS accounts drove it.
4. Use get_ytd_trend for any workload showing a multi-week pattern.
5. Read relevant memory keys (e.g. 'prior_week_actuals', 'anomaly_history',
   'forecast_errors') to inform your analysis.
6. Write updated memory at the end of your analysis so next week's run is smarter.
7. Produce a clear, opinionated weekly report in markdown.

Report structure:
# AWS FinOps Weekly — {date}

## Summary
One paragraph: overall spend health, biggest story this week.

## Workload Breakdown
For each of MES, CNA, ADA (and Run Cost overall):
- Actual vs budget ($ and %)
- Week-on-week change with the reason (run cost / marketplace / account spike)
- Status: ✅ on track / ⚠️ over budget / 🔴 critical

## Anomalies & Flags
Bullet list of anything that needs attention, with account-level detail.

## Month-to-Date Position
Days remaining in month, projected end-of-month spend per workload.

## Claude's Take
2–4 sentences of genuine insight — patterns, risks, recommendations.
Reference prior weeks from memory when relevant.
Do not pad. Only say something if it is genuinely useful.

## What I Updated in Memory
One line per memory key written, so the user can see the agent learning.

Tone: direct, specific, no fluff. Use $ amounts everywhere, not percentages alone.
"""


# ── CUR ingest ────────────────────────────────────────────────────────────────

def _ingest_latest_cur() -> str | None:
    """Find the newest CUR file in CUR_DIR and ingest it. Returns filename or None."""
    patterns = [
        os.path.join(config.CUR_DIR, "*.xlsx"),
        os.path.join(config.CUR_DIR, "*.xlsm"),
        os.path.join(config.CUR_DIR, "*.csv"),
    ]
    candidates = []
    for pat in patterns:
        candidates.extend(glob.glob(pat))

    if not candidates:
        print(f"[agent] No CUR files found in {config.CUR_DIR}")
        return None

    latest = max(candidates, key=os.path.getmtime)
    print(f"[agent] Ingesting CUR: {latest}")

    from aws_ingestor import ingest_cur
    from aws_db import get_conn

    with get_conn() as conn:
        result = ingest_cur(latest, conn, uploaded_by="agent")

    print(f"[agent] Ingest complete: {result}")
    return os.path.basename(latest)


# ── Agent loop ────────────────────────────────────────────────────────────────

def run_agent(dry_run: bool = False, skip_ingest: bool = False) -> str:
    # 1. Ingest latest CUR
    if not skip_ingest:
        _ingest_latest_cur()

    # 2. Load all memory for context
    all_memory = _mem.read_all()
    memory_summary = json.dumps(all_memory, indent=2) if all_memory else "(no prior memory)"

    # 3. Build initial user message
    today = date.today().strftime("%d %b %Y")
    user_message = (
        f"Today is {today}. Run the weekly AWS FinOps analysis. "
        f"Use your tools to get the data, then produce the full weekly report.\n\n"
        f"Agent memory from prior runs:\n{memory_summary}"
    )

    # 4. Claude agentic loop
    client   = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_message}]

    print(f"[agent] Starting Claude reasoning loop ({config.CLAUDE_MODEL})...")
    final_report = ""

    for iteration in range(20):   # safety cap — should finish in 8–12 tool calls
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT.format(date=today),
            tools=_tools.TOOLS,
            messages=messages,
        )

        # Accumulate text
        for block in response.content:
            if hasattr(block, "text"):
                final_report = block.text   # last text block is the final report

        # If Claude is done, break
        if response.stop_reason == "end_turn":
            print(f"[agent] Claude finished after {iteration + 1} iterations.")
            break

        # Process tool calls
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"[agent] Tool call: {block.name}({json.dumps(block.input)[:120]})")
                    result = _tools.run_tool(block.name, block.input)
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result,
                    })

            # Append assistant turn + tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user",      "content": tool_results})
        else:
            break   # unexpected stop reason

    # 5. Send to Teams (unless dry-run)
    if final_report:
        if dry_run:
            print("\n" + "=" * 60)
            print("DRY RUN — report that would be sent to Teams:")
            print("=" * 60)
            print(final_report)
        else:
            teams_notify.send_weekly_report(final_report)
    else:
        print("[agent] Warning: no report text produced.")

    return final_report


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AWS FinOps Agent weekly runner")
    parser.add_argument("--dry-run",   action="store_true", help="Print report, do not send email")
    parser.add_argument("--no-ingest", action="store_true", help="Skip CUR ingest, re-analyse existing data")
    args = parser.parse_args()

    run_agent(dry_run=args.dry_run, skip_ingest=args.no_ingest)


# ── Windows Task Scheduler setup ──────────────────────────────────────────────
# 1. Open Task Scheduler → Create Basic Task
# 2. Name: "AWS FinOps Agent"
# 3. Trigger: Weekly → Monday → 08:00 AM
# 4. Action: Start a program
#      Program:  C:\Apps\FinOps-AWS\venv\Scripts\python.exe
#      Arguments: C:\Apps\FinOps-AWS\aws_finops_standalone\agent\agent_runner.py
#      Start in:  C:\Apps\FinOps-AWS\aws_finops_standalone\agent
# 5. Set environment variable ANTHROPIC_API_KEY in System Properties → Environment Variables
#    (never store the key in config.py directly)
