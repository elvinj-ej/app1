"""
Parse AWS CUR file (CSV or Excel) and upsert into cur_data.

CSV/Excel format (pivoted):
  Col A: account_id   (may have leading \\t prefix in exports)
  Col B: account_name
  Col C: workloads_tag
  Col D: outcomegroup_tag
  Col E: category     ('monthly_expense' | 'marketplace')
  Col F+: month columns

Summary rows (blank account_id) are skipped.
Re-uploading the same period is safe — rows are upserted.
"""
import os
import re
import logging
from datetime import datetime
from aws_db import get_conn

log = logging.getLogger(__name__)

VALID_CATEGORIES = {"monthly_expense", "marketplace"}


def _clean_account_id(raw):
    s = str(raw).strip()
    # Strip literal \t prefix (two characters: backslash + t)
    s = s.lstrip("\\t").strip()
    # Strip real whitespace/tab characters
    return re.sub(r"[\t\s]+", "", s)


def _parse_date(val):
    """Try multiple date formats. Return datetime or None."""
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y/%m/%d", "%Y/%m", "%b-%Y", "%B-%Y", "%b %Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _parse_excel(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    month_dates, month_cols, data_rows = [], [], []

    for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
        if row_idx == 0:
            for col_idx, val in enumerate(row):
                if col_idx >= 5:
                    dt = _parse_date(val) if val is not None else None
                    if dt:
                        month_dates.append(dt)
                        month_cols.append(col_idx)
            continue

        if row[0] is None or str(row[0]).strip() in ("", "None"):
            continue
        account_id = _clean_account_id(row[0])
        if not account_id:
            continue

        category = (row[4] or "").strip().lower()
        if category not in VALID_CATEGORIES:
            continue

        amounts = {}
        for col_idx, dt in zip(month_cols, month_dates):
            val = row[col_idx] if col_idx < len(row) else None
            if val is not None:
                try:
                    amounts[dt.strftime("%Y-%m-01")] = float(val)
                except (TypeError, ValueError):
                    pass

        if amounts:
            data_rows.append({
                "account_id":    account_id,
                "account_name":  (row[1] or "").strip(),
                "workloads_tag": (row[2] or "").strip(),
                "outcomegroup":  (row[3] or "").strip() or None,
                "category":      category,
                "amounts":       amounts,
            })

    wb.close()
    return month_dates, data_rows


def _parse_csv(path):
    import csv

    month_dates, month_cols, data_rows = [], [], []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row_idx, row in enumerate(reader):
            if row_idx == 0:
                for col_idx, val in enumerate(row):
                    if col_idx >= 5:
                        dt = _parse_date(val)
                        if dt:
                            month_dates.append(dt)
                            month_cols.append(col_idx)
                continue

            raw_id = row[0].strip() if row else ""
            account_id = _clean_account_id(raw_id)
            if not account_id:
                continue

            category = row[4].strip().lower() if len(row) > 4 else ""
            if category not in VALID_CATEGORIES:
                continue

            amounts = {}
            for col_idx, dt in zip(month_cols, month_dates):
                val = row[col_idx].strip() if col_idx < len(row) else ""
                if val:
                    try:
                        amounts[dt.strftime("%Y-%m-01")] = float(val.replace(",", ""))
                    except ValueError:
                        pass

            if amounts:
                data_rows.append({
                    "account_id":    account_id,
                    "account_name":  row[1].strip() if len(row) > 1 else "",
                    "workloads_tag": row[2].strip() if len(row) > 2 else "",
                    "outcomegroup":  row[3].strip() if len(row) > 3 else None,
                    "category":      category,
                    "amounts":       amounts,
                })

    return month_dates, data_rows


def ingest_cur(path, uploaded_by=""):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".xlsx", ".xlsm", ".xls"):
            month_dates, data_rows = _parse_excel(path)
        elif ext == ".csv":
            month_dates, data_rows = _parse_csv(path)
        else:
            return {"rows_upserted": 0, "months_found": 0, "errors": [f"Unsupported file type: {ext}"]}
    except Exception as e:
        log.error(f"CUR parse error: {e}")
        return {"rows_upserted": 0, "months_found": 0, "errors": [str(e)]}

    if not data_rows:
        return {
            "rows_upserted": 0,
            "months_found": len(month_dates),
            "errors": ["No data rows found — check file format. Expected columns: account_id, account_name, workloads_tag, outcomegroup_tag, category, then month columns."],
        }

    rows_upserted = 0
    with get_conn() as conn:
        for row in data_rows:
            for month_str, amount in row["amounts"].items():
                conn.execute(
                    "INSERT INTO cur_data "
                    "(account_id, account_name, workloads_tag, outcomegroup, category, month, amount) "
                    "VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT(account_id, workloads_tag, category, month) "
                    "DO UPDATE SET amount=excluded.amount, account_name=excluded.account_name, outcomegroup=excluded.outcomegroup",
                    (row["account_id"], row["account_name"], row["workloads_tag"],
                     row["outcomegroup"], row["category"], month_str, amount),
                )
                rows_upserted += 1

        conn.execute(
            "INSERT INTO upload_log (filename, rows_upserted, months_found, uploaded_by) VALUES (?,?,?,?)",
            (os.path.basename(path), rows_upserted, len(month_dates), uploaded_by),
        )

    log.info(f"CUR ingest: {rows_upserted} rows, {len(month_dates)} months — {path}")
    return {
        "rows_upserted":  rows_upserted,
        "months_found":   len(month_dates),
        "months":         [dt.strftime("%Y-%m-01") for dt in month_dates],
        "errors":         [],
    }
