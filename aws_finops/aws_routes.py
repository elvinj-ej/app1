"""
aws_routes.py
-------------
Flask Blueprint for the AWS FinOps tracker.
Mount in app.py with:

    from aws_finops.aws_routes import aws_bp
    app.register_blueprint(aws_bp)

All routes are under /PlatformTCO/aws/...
Authentication reuses the login_required decorator from app.py.
"""

import os
import uuid
import logging
from flask import Blueprint, request, jsonify, render_template, session

from aws_db import init_db, get_conn
from aws_ingestor import ingest_cur
from aws_run_cost import (
    get_available_months,
    get_workloads,
    get_monthly_input,
    compute_run_cost,
    compute_multi_month,
)

log = logging.getLogger(__name__)

aws_bp = Blueprint(
    "aws",
    __name__,
    url_prefix="/PlatformTCO/aws",
    template_folder=os.path.dirname(os.path.abspath(__file__)),
)

# Temp folder for CUR uploads — reuse the same tmp/ next to app.py
_UPLOAD_TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tmp")

# Initialise DB when the blueprint is first imported
init_db()


# ── UI ─────────────────────────────────────────────────────────────────────────

@aws_bp.route("/", methods=["GET"])
@aws_bp.route("", methods=["GET"])
def index():
    """Serve the AWS FinOps dashboard."""
    # login_required is applied via before_request below
    return render_template("aws_index.html")


# ── CUR UPLOAD ─────────────────────────────────────────────────────────────────

@aws_bp.route("/upload-cur", methods=["POST"])
def upload_cur():
    """
    Accept a CUR file (.xlsx or .csv), ingest it into the DB.
    Returns JSON: { rows_upserted, months_found, months, errors }
    """
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file received."}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".xlsx", ".xlsm", ".xls", ".csv"):
        return jsonify({"error": f"Unsupported file type ({ext}). Upload .xlsx or .csv."}), 400

    os.makedirs(_UPLOAD_TMP, exist_ok=True)
    tmp_name = f"{uuid.uuid4().hex}{ext}"
    tmp_path = os.path.join(_UPLOAD_TMP, tmp_name)

    try:
        f.save(tmp_path)
        result = ingest_cur(tmp_path, uploaded_by=session.get("username", ""))
        if result["errors"]:
            log.warning(f"CUR ingest warnings for {f.filename}: {result['errors']}")
        return jsonify(result)
    except Exception as e:
        log.error(f"CUR upload error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


# ── MONTHS ─────────────────────────────────────────────────────────────────────

@aws_bp.route("/months", methods=["GET"])
def months():
    """Return all months that have CUR data."""
    return jsonify({"months": get_available_months()})


# ── RUN COST ───────────────────────────────────────────────────────────────────

@aws_bp.route("/run-cost", methods=["GET"])
def run_cost():
    """
    Compute run cost for one or more months.
    Query params:
      month  = YYYY-MM-01  (single month)
      months = YYYY-MM-01,YYYY-MM-01,...  (multi-month matrix)
    """
    single = request.args.get("month", "").strip()
    multi  = request.args.get("months", "").strip()

    if multi:
        month_list = [m.strip() for m in multi.split(",") if m.strip()]
        return jsonify(compute_multi_month(month_list))

    if single:
        return jsonify(compute_run_cost(single))

    # Default: return last 6 months with data
    all_months = get_available_months()
    recent = all_months[-6:] if len(all_months) > 6 else all_months
    return jsonify(compute_multi_month(recent))


# ── MONTHLY INPUTS ─────────────────────────────────────────────────────────────

@aws_bp.route("/monthly-inputs/<month>", methods=["GET"])
def get_inputs(month):
    return jsonify(get_monthly_input(month))


@aws_bp.route("/monthly-inputs/<month>", methods=["POST"])
def save_inputs(month):
    """
    Save Telstra invoice + forecast for a month.
    Body: { telstra_invoice: float, forecast: float }
    """
    data = request.get_json(force=True)
    try:
        telstra = float(data.get("telstra_invoice") or 0) or None
        forecast = float(data.get("forecast") or 0) or None
    except (TypeError, ValueError) as e:
        return jsonify({"error": f"Invalid number: {e}"}), 400

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO monthly_inputs (month, telstra_invoice, forecast)
            VALUES (?, ?, ?)
            ON CONFLICT(month) DO UPDATE SET
                telstra_invoice = excluded.telstra_invoice,
                forecast        = excluded.forecast
        """, (month, telstra, forecast))

    log.info(f"Monthly inputs saved: {month} invoice={telstra} forecast={forecast}")
    return jsonify({"ok": True})


# ── WORKLOAD CONFIG ─────────────────────────────────────────────────────────────

@aws_bp.route("/workloads", methods=["GET"])
def list_workloads():
    return jsonify({"workloads": get_workloads()})


@aws_bp.route("/workloads", methods=["POST"])
def create_workload():
    """Add a new named workload to the exclusion list."""
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Workload name is required."}), 400

    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO workloads (name, domain, department, budget_manager, description, budget_monthly)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                name,
                (data.get("domain") or "").strip() or None,
                (data.get("department") or "").strip() or None,
                (data.get("budget_manager") or "").strip() or None,
                (data.get("description") or "").strip() or None,
                float(data.get("budget_monthly") or 0) or None,
            ))
        log.info(f"Workload created: {name}")
        return jsonify({"ok": True})
    except Exception as e:
        if "UNIQUE" in str(e):
            return jsonify({"error": f"Workload '{name}' already exists."}), 409
        return jsonify({"error": str(e)}), 500


@aws_bp.route("/workloads/<name>", methods=["PUT"])
def update_workload(name):
    data = request.get_json(force=True)
    try:
        with get_conn() as conn:
            conn.execute("""
                UPDATE workloads
                SET domain=?, department=?, budget_manager=?, description=?, budget_monthly=?
                WHERE name=?
            """, (
                (data.get("domain") or "").strip() or None,
                (data.get("department") or "").strip() or None,
                (data.get("budget_manager") or "").strip() or None,
                (data.get("description") or "").strip() or None,
                float(data.get("budget_monthly") or 0) or None,
                name,
            ))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@aws_bp.route("/workloads/<name>", methods=["DELETE"])
def delete_workload(name):
    with get_conn() as conn:
        conn.execute("DELETE FROM workloads WHERE name=?", (name,))
    log.info(f"Workload deleted: {name}")
    return jsonify({"ok": True})


# ── CUR TAG DISCOVERY ──────────────────────────────────────────────────────────

@aws_bp.route("/cur-tags", methods=["GET"])
def cur_tags():
    """Return all distinct workloads_tag values found in CUR data (for workload setup)."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT workloads_tag
            FROM cur_data
            WHERE workloads_tag IS NOT NULL
            ORDER BY workloads_tag
        """).fetchall()
    return jsonify({"tags": [r["workloads_tag"] for r in rows]})


# ── AUTH GUARD ─────────────────────────────────────────────────────────────────
# Applied to all routes in this blueprint.

@aws_bp.before_request
def _require_login():
    """Reuse the session-based auth already established by app.py."""
    # Import here to avoid circular import (app.py registers this blueprint)
    try:
        from flask import current_app
        ad_enabled = current_app.config.get("AD_ENABLED", True)
    except Exception:
        ad_enabled = True

    if ad_enabled and "username" not in session:
        from flask import redirect, url_for
        session["next"] = request.url
        return redirect(url_for("login_page"))
