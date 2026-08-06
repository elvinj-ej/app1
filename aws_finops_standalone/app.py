"""
app.py — AWS FinOps Tracker (standalone)
-----------------------------------------
Serves at http://hostname:4020/AWSFinOps

Run:  python app.py
Uses Waitress (production-grade WSGI server for Windows).

Data folder: C:\\AWSFinOps\\Data\\
  db\\      aws_finops.db  — SQLite database
  tmp\\     transient upload staging

Active Directory auth mirrors the PlatformTCO app.
Set AD_ENABLED=False (env var) to bypass auth during local testing.
"""

import os
import re
import hmac
import hashlib
import uuid
import time
import logging
import calendar
import datetime
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for, make_response,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from waitress import serve

from aws_db import init_db, get_conn
from aws_ingestor import ingest_cur
from aws_run_cost import get_available_months, get_workloads, get_monthly_input, compute

# ── CONFIG ────────────────────────────────────────────────────────────────────

HOST    = "0.0.0.0"
PORT    = 4020
MAX_MB  = 50

DATA_ROOT  = os.environ.get("AWS_DATA_ROOT", r"C:\AWSFinOps\Data")
UPLOAD_TMP = os.path.join(DATA_ROOT, "tmp")

os.environ.setdefault(
    "AWS_DB_PATH",
    os.path.join(DATA_ROOT, "db", "aws_finops.db"),
)

# ── AUTH ──────────────────────────────────────────────────────────────────────

AD_ENABLED   = os.environ.get("AD_ENABLED", "true").lower() not in ("false", "0", "no")
AD_DOMAIN    = os.environ.get("AD_DOMAIN",  "COCHLEAR")
ALLOWED_GROUP= os.environ.get("AD_GROUP",   "Domain Users")
SECRET_KEY   = os.environ.get("SECRET_KEY", "change-this-aws-finops-secret")
SSO_SECRET   = os.environ.get("SSO_SECRET", "aws-finops-sso-change-in-prod")

# ── APP ───────────────────────────────────────────────────────────────────────

app = Flask(__name__, template_folder=os.path.dirname(os.path.abspath(__file__)))
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024
app.config["AD_ENABLED"] = AD_ENABLED
app.secret_key = SECRET_KEY
app.wsgi_app   = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

os.makedirs(UPLOAD_TMP, exist_ok=True)
os.makedirs(os.path.dirname(os.environ["AWS_DB_PATH"]), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "app.log")),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

init_db()
log.info(f"DB ready: {os.environ['AWS_DB_PATH']}")
log.info(f"AD auth: {'ENABLED' if AD_ENABLED else 'DISABLED'}")

# ── AD AUTH HELPERS ───────────────────────────────────────────────────────────

def _ldap_check(username: str, password: str | None = None):
    """
    Validate credentials and group membership via PowerShell + .NET DirectoryServices.
    Returns (ok: bool, display_name_or_error: str)
    """
    import subprocess, json

    safe_user = re.sub(r"[^a-zA-Z0-9.\-_@]", "", username)
    if not safe_user:
        return False, "Invalid username."

    if password:
        validate_script = f"""
$ErrorActionPreference = 'Stop'
try {{
    Add-Type -AssemblyName System.DirectoryServices.AccountManagement
    $ctx = New-Object System.DirectoryServices.AccountManagement.PrincipalContext(
        [System.DirectoryServices.AccountManagement.ContextType]::Domain
    )
    $valid = $ctx.ValidateCredentials('{safe_user}', '{password.replace("'", "''")}')
    if ($valid) {{ Write-Output 'OK' }} else {{ Write-Output 'WRONG_PASSWORD' }}
}} catch {{
    Write-Output "ERROR:$($_.Exception.Message)"
}}
"""
        r = subprocess.run(
            ["powershell", "-NonInteractive", "-NoProfile", "-Command", validate_script],
            capture_output=True, text=True, timeout=15,
        )
        result = (r.stdout.strip() or r.stderr.strip())
        if result == "WRONG_PASSWORD":
            return False, "Incorrect username or password."
        if result.startswith("ERROR:"):
            return False, f"Active Directory error: {result[6:]}"
        if result != "OK":
            return False, f"Authentication failed (unexpected response: {result})."

    if ALLOWED_GROUP.lower() in ("domain users", "domainusers"):
        name_script = f"""
$ErrorActionPreference = 'Stop'
try {{
    Add-Type -AssemblyName System.DirectoryServices
    $searcher = New-Object System.DirectoryServices.DirectorySearcher
    $searcher.Filter = "(&(objectClass=user)(sAMAccountName={safe_user}))"
    $searcher.PropertiesToLoad.Add("displayName") | Out-Null
    $entry = $searcher.FindOne()
    if ($null -eq $entry) {{ Write-Output "NOT_FOUND" }}
    else {{ Write-Output $entry.Properties["displayName"][0] }}
}} catch {{
    Write-Output "ERROR:$($_.Exception.Message)"
}}
"""
        r = subprocess.run(
            ["powershell", "-NonInteractive", "-NoProfile", "-Command", name_script],
            capture_output=True, text=True, timeout=15,
        )
        result = r.stdout.strip()
        if result == "NOT_FOUND":
            return False, f"User '{safe_user}' not found in Active Directory."
        if result.startswith("ERROR:"):
            return False, f"Active Directory error: {result[6:]}"
        display = result or safe_user
        log.info(f"AUTH OK (Domain Users): {safe_user} ({display})")
        return True, display

    group_script = f"""
$ErrorActionPreference = 'Stop'
try {{
    Add-Type -AssemblyName System.DirectoryServices
    $searcher = New-Object System.DirectoryServices.DirectorySearcher
    $searcher.Filter = "(&(objectClass=user)(sAMAccountName={safe_user}))"
    $searcher.PropertiesToLoad.Add("memberOf") | Out-Null
    $searcher.PropertiesToLoad.Add("displayName") | Out-Null
    $entry = $searcher.FindOne()
    if ($null -eq $entry) {{
        Write-Output "NOT_FOUND"
    }} else {{
        $display = $entry.Properties["displayName"][0]
        $groups  = $entry.Properties["memberOf"]
        $inGroup = $false
        foreach ($g in $groups) {{
            if ($g -match 'CN={ALLOWED_GROUP},') {{ $inGroup = $true; break }}
        }}
        Write-Output (@{{ display=$display; inGroup=$inGroup }} | ConvertTo-Json -Compress)
    }}
}} catch {{
    Write-Output "ERROR:$($_.Exception.Message)"
}}
"""
    r = subprocess.run(
        ["powershell", "-NonInteractive", "-NoProfile", "-Command", group_script],
        capture_output=True, text=True, timeout=15,
    )
    result = r.stdout.strip()
    if result == "NOT_FOUND":
        return False, f"User '{safe_user}' not found in Active Directory."
    if result.startswith("ERROR:"):
        return False, f"Active Directory error: {result[6:]}"

    try:
        data     = json.loads(result)
        display  = data.get("display") or safe_user
        in_group = bool(data.get("inGroup"))
    except Exception:
        return False, "Unexpected response from Active Directory."

    if not in_group:
        return False, f"{display} does not have access. Ask your manager to add you to AD group '{ALLOWED_GROUP}'."

    log.info(f"AUTH OK: {safe_user} ({display})")
    return True, display


_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Login — AWS FinOps Tracker</title>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Segoe UI',sans-serif;display:flex;align-items:center;
         justify-content:center;min-height:100vh;background:#f0f2f5}
    .card{background:#fff;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.1);
          padding:48px 52px;width:100%;max-width:400px}
    h2{font-size:1.2rem;color:#1a1a2e;margin-bottom:6px}
    .sub{font-size:.83rem;color:#888;margin-bottom:32px}
    label{display:block;font-size:.82rem;font-weight:600;color:#444;margin-bottom:6px}
    input{width:100%;padding:10px 12px;border:1px solid #ccd0d9;border-radius:5px;
          font-size:.92rem;margin-bottom:20px;outline:none}
    input:focus{border-color:#F0A500}
    button{width:100%;padding:11px;background:#F0A500;color:#2B3752;border:none;
           border-radius:5px;font-size:.95rem;font-weight:700;cursor:pointer}
    button:hover{background:#d99300}
    .err{color:#8b1a1a;background:#fdecea;border:1px solid #f3c9c9;border-radius:5px;
         padding:10px 14px;font-size:.85rem;margin-bottom:18px}
  </style>
</head>
<body>
  <div class="card">
    <h2>AWS FinOps Tracker</h2>
    <p class="sub">Login with your Cochlear account.</p>
    %%ERROR_BLOCK%%
    <label for="u">Username</label>
    <input id="u" name="username" type="text" autocomplete="username" placeholder="username" autofocus/>
    <label for="p">Password</label>
    <input id="p" name="password" type="password" autocomplete="current-password"/>
    <button onclick="doLogin()">Login</button>
  </div>
  <script>
    function showError(msg){
      let el=document.querySelector('.err');
      if(!el){el=document.createElement('div');el.className='err';
               document.querySelector('button').insertAdjacentElement('beforebegin',el)}
      el.textContent=msg;
    }
    function doLogin(){
      const u=document.getElementById('u').value.trim();
      const p=document.getElementById('p').value;
      if(!u||!p){showError('Enter username and password.');return}
      const btn=document.querySelector('button');
      btn.disabled=true;btn.textContent='Logging in…';
      fetch('/AWSFinOps/auth/login',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:u,password:p})})
      .then(r=>r.json())
      .then(d=>{
        if(d.ok){window.location.href=d.next||'/AWSFinOps/'}
        else{showError(d.error||'Login failed.');btn.disabled=false;btn.textContent='Login'}
      })
      .catch(()=>{showError('Connection error.');btn.disabled=false;btn.textContent='Login'});
    }
    document.addEventListener('keydown',e=>{if(e.key==='Enter')doLogin()});
  </script>
</body>
</html>"""

_ACCESS_DENIED_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/><title>Access Denied</title>
<style>body{font-family:'Segoe UI',sans-serif;display:flex;align-items:center;
justify-content:center;min-height:100vh;background:#f0f2f5}
.box{background:#fff;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.1);
padding:48px 56px;max-width:480px;text-align:center}
h2{color:#8b1a1a;margin-bottom:12px}p{color:#555;line-height:1.6}
a{color:#F0A500}</style></head>
<body><div class="box"><h2>&#128274; Access Denied</h2>
<p>{msg}</p>
<p style="margin-top:24px"><a href="/AWSFinOps/logout">Logout</a></p>
</div></body></html>"""


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not AD_ENABLED:
            return f(*args, **kwargs)

        remote_user = request.environ.get("REMOTE_USER", "")
        if remote_user and "username" not in session:
            username = remote_user.split("\\")[-1]
            ok, result = _ldap_check(username)
            if ok:
                session["username"]     = username
                session["display_name"] = result
            else:
                return make_response(_ACCESS_DENIED_HTML.format(msg=result), 403)

        if "username" not in session:
            session["next"] = request.url
            return redirect(url_for("login_page"))

        return f(*args, **kwargs)
    return decorated


# ── AUTH ROUTES ───────────────────────────────────────────────────────────────

@app.route("/AWSFinOps/login", methods=["GET"])
def login_page():
    error = session.pop("login_error", None)
    block = f'<div class="err">{error}</div>' if error else ""
    return _LOGIN_HTML.replace("%%ERROR_BLOCK%%", block)


@app.route("/AWSFinOps/auth/login", methods=["POST"])
def auth_login():
    data     = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"ok": False, "error": "Enter username and password."})

    username = username.split("\\")[-1].split("@")[0]
    ok, result = _ldap_check(username, password)

    if ok:
        session["username"]     = username
        session["display_name"] = result
        return jsonify({"ok": True, "next": session.pop("next", "/AWSFinOps/")})
    return jsonify({"ok": False, "error": result})


@app.route("/AWSFinOps/sso", methods=["GET"])
def sso_login():
    username  = request.args.get("user",  "").strip()
    timestamp = request.args.get("ts",    "").strip()
    token     = request.args.get("token", "").strip()

    if not username or not timestamp or not token:
        return redirect(url_for("login_page"))

    try:
        age = abs(time.time() - int(timestamp))
        if age > 60:
            return make_response("SSO token expired.", 403)
    except ValueError:
        return make_response("Invalid SSO token.", 403)

    expected = hmac.new(
        SSO_SECRET.encode(), f"{username}|{timestamp}".encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(token, expected):
        log.warning(f"SSO HMAC mismatch for {username}")
        return make_response("Invalid SSO token.", 403)

    if "username" in session and session["username"] == username:
        return redirect(url_for("index"))

    ok, result = _ldap_check(username)
    if ok:
        session["username"]     = username
        session["display_name"] = result
        return redirect(url_for("index"))
    return make_response(f"Access denied: {result}", 403)


@app.route("/AWSFinOps/logout")
def logout():
    display = session.get("display_name", "")
    session.clear()
    log.info(f"LOGOUT: {display}")
    return redirect(url_for("login_page"))


# ── UI ────────────────────────────────────────────────────────────────────────

@app.route("/AWSFinOps/", methods=["GET"])
@app.route("/AWSFinOps",  methods=["GET"])
@login_required
def index():
    resp = make_response(render_template(
        "index.html",
        display_name=session.get("display_name", session.get("username", "")),
    ))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


# ── API: months ───────────────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/months", methods=["GET"])
@login_required
def api_months():
    from datetime import timezone, timedelta
    months = get_available_months()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT uploaded_at FROM upload_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    last_upload_utc = None
    if row and row["uploaded_at"]:
        last_upload_utc = str(row["uploaded_at"]).split(".")[0]  # strip fractional seconds, keep "YYYY-MM-DD HH:MM:SS"
    return jsonify({"months": months, "last_upload_utc": last_upload_utc})


# ── API: run cost ─────────────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/run-cost", methods=["GET"])
@login_required
def api_run_cost():
    from datetime import datetime, timedelta
    month = request.args.get("month", "").strip()
    months = get_available_months()
    if not month:
        month = months[-1] if months else None
    if not month:
        return jsonify({"error": "No CUR data available."}), 404

    data = compute(month)

    # Previous month actuals for MoM movement indicators
    try:
        dt       = datetime.strptime(month, "%Y-%m-%d")
        prev_dt  = (dt.replace(day=1) - timedelta(days=1)).replace(day=1)
        prev_str = prev_dt.strftime("%Y-%m-%d")
        if prev_str in months:
            prev = compute(prev_str)
            data["prev_actuals"] = {
                r["workload"]: r["actual"]
                for r in prev["consumption_rows"] + prev["project_rows"] + prev["shared_rows"]
            }
        else:
            data["prev_actuals"] = {}
    except Exception:
        data["prev_actuals"] = {}

    return jsonify(data)


# ── API: monthly inputs ────────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/monthly-inputs/<month>", methods=["GET"])
@login_required
def api_get_inputs(month):
    return jsonify(get_monthly_input(month))


@app.route("/AWSFinOps/api/monthly-inputs/<month>", methods=["POST"])
@login_required
def api_save_inputs(month):
    data = request.get_json(force=True)
    try:
        telstra          = float(data.get("telstra_invoice")  or 0) or None
        forecast_run     = float(data.get("forecast_run")     or 0) or None
        forecast_project = float(data.get("forecast_project") or 0) or None
    except (TypeError, ValueError) as e:
        return jsonify({"error": str(e)}), 400

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO monthly_inputs (month, telstra_invoice, forecast_run, forecast_project) VALUES (?,?,?,?) "
            "ON CONFLICT(month) DO UPDATE SET "
            "telstra_invoice=excluded.telstra_invoice, "
            "forecast_run=excluded.forecast_run, "
            "forecast_project=excluded.forecast_project",
            (month, telstra, forecast_run, forecast_project),
        )

    log.info(f"Monthly inputs saved: {month} by {session.get('username','')}")
    return jsonify({"ok": True})


# ── API: upload CUR ───────────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/upload-cur", methods=["POST"])
@login_required
def api_upload_cur():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file received."}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".xlsx", ".xlsm", ".xls", ".csv"):
        return jsonify({"error": f"Unsupported file type ({ext}). Use .xlsx or .csv."}), 400

    tmp_path = os.path.join(UPLOAD_TMP, f"{uuid.uuid4().hex}{ext}")
    try:
        f.save(tmp_path)
        result = ingest_cur(tmp_path, uploaded_by=session.get("username", ""))

        months = get_available_months()
        result["latest_month"] = months[-1] if months else None
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


# ── API: upload history ────────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/upload-history", methods=["GET"])
@login_required
def api_upload_history():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT filename, rows_upserted, months_found, uploaded_by, uploaded_at "
            "FROM upload_log ORDER BY id DESC LIMIT 20"
        ).fetchall()
    return jsonify({"history": [dict(r) for r in rows]})


# ── API: workloads ─────────────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/workloads", methods=["GET"])
@login_required
def api_list_workloads():
    return jsonify({"workloads": get_workloads()})


@app.route("/AWSFinOps/api/workloads", methods=["POST"])
@login_required
def api_create_workload():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Workload name is required."}), 400
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO workloads (name,domain,cost_category,budget_manager,description,budget_monthly,cur_tag) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    name,
                    (data.get("domain") or "").strip() or None,
                    (data.get("cost_category") or "Consumption").strip(),
                    (data.get("budget_manager") or "").strip() or None,
                    (data.get("description") or "").strip() or None,
                    float(data.get("budget_monthly") or 0) or None,
                    (data.get("cur_tag") or "").strip() or None,
                ),
            )
        log.info(f"Workload created: {name} by {session.get('username','')}")
        return jsonify({"ok": True})
    except Exception as e:
        if "UNIQUE" in str(e):
            return jsonify({"error": f"Workload '{name}' already exists."}), 409
        return jsonify({"error": str(e)}), 500


@app.route("/AWSFinOps/api/workloads/<name>", methods=["PUT"])
@login_required
def api_update_workload(name):
    data = request.get_json(force=True)
    with get_conn() as conn:
        conn.execute(
            "UPDATE workloads SET domain=?,cost_category=?,budget_manager=?,description=?,budget_monthly=?,cur_tag=? "
            "WHERE name=?",
            (
                (data.get("domain") or "").strip() or None,
                (data.get("cost_category") or "Consumption").strip(),
                (data.get("budget_manager") or "").strip() or None,
                (data.get("description") or "").strip() or None,
                float(data.get("budget_monthly") or 0) or None,
                (data.get("cur_tag") or "").strip() or None,
                name,
            ),
        )
    log.info(f"Workload updated: {name} by {session.get('username','')}")
    return jsonify({"ok": True})


@app.route("/AWSFinOps/api/workloads/<name>", methods=["DELETE"])
@login_required
def api_delete_workload(name):
    with get_conn() as conn:
        conn.execute("DELETE FROM workloads WHERE name=?", (name,))
    log.info(f"Workload deleted: {name} by {session.get('username','')}")
    return jsonify({"ok": True})


# ── API: marketplace adjustments ──────────────────────────────────────────────

@app.route("/AWSFinOps/api/marketplace-adjustment", methods=["POST"])
@login_required
def api_save_marketplace_adjustment():
    data = request.get_json(force=True)
    workload = (data.get("workload") or "").strip()
    month    = (data.get("month")    or "").strip()
    if not workload or not month:
        return jsonify({"error": "workload and month are required"}), 400
    try:
        adjustment = float(data.get("adjustment") or 0)
    except (TypeError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    note           = (data.get("note")           or "").strip()
    po_number      = (data.get("po_number")      or "").strip()
    purchaser_name = (data.get("purchaser_name") or "").strip()

    with get_conn() as conn:
        if adjustment == 0 and not note and not po_number and not purchaser_name:
            conn.execute(
                "DELETE FROM marketplace_adjustments WHERE workload=? AND month=?",
                (workload, month),
            )
        else:
            conn.execute(
                "INSERT INTO marketplace_adjustments (workload, month, adjustment, note, po_number, purchaser_name) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(workload, month) DO UPDATE SET "
                "adjustment=excluded.adjustment, note=excluded.note, "
                "po_number=excluded.po_number, purchaser_name=excluded.purchaser_name, "
                "updated_at=datetime('now')",
                (workload, month, adjustment, note or None, po_number or None, purchaser_name or None),
            )

    log.info(f"Marketplace adjustment saved: {workload}/{month} adj={adjustment} by {session.get('username','')}")
    return jsonify({"ok": True})


# ── API: CUR tag discovery ─────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/cur-tags", methods=["GET"])
@login_required
def api_cur_tags():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT workloads_tag FROM cur_data "
            "WHERE workloads_tag != '' ORDER BY workloads_tag"
        ).fetchall()
    return jsonify({"tags": [r["workloads_tag"] for r in rows]})


# ── API: accounts for a workload ──────────────────────────────────────────────

@app.route("/AWSFinOps/api/workloads/<name>/accounts", methods=["GET"])
@login_required
def api_workload_accounts(name):
    with get_conn() as conn:
        # Resolve effective CUR tag (cur_tag override or workload name)
        wl = conn.execute("SELECT cur_tag FROM workloads WHERE name=?", (name,)).fetchone()
        tag = (wl["cur_tag"] or name).strip() if wl else name
        rows = conn.execute(
            "SELECT DISTINCT account_id, account_name FROM cur_data "
            "WHERE workloads_tag=? OR LOWER(workloads_tag)=LOWER(?) "
            "ORDER BY account_name",
            (tag, tag),
        ).fetchall()
    return jsonify({"accounts": [{"account_id": r["account_id"], "account_name": r["account_name"]} for r in rows]})


# ── API: accounts for a raw CUR tag (used for unassigned tags) ────────────────

@app.route("/AWSFinOps/api/cur-tags/<tag>/accounts", methods=["GET"])
@login_required
def api_cur_tag_accounts(tag):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT account_id, account_name FROM cur_data "
            "WHERE workloads_tag=? OR LOWER(workloads_tag)=LOWER(?) "
            "ORDER BY account_name",
            (tag, tag),
        ).fetchall()
    return jsonify({"accounts": [{"account_id": r["account_id"], "account_name": r["account_name"]} for r in rows]})


# ── API: unassigned CUR tags (in CUR but not matched to any workload) ──────────

@app.route("/AWSFinOps/api/cur-tags/unassigned", methods=["GET"])
@login_required
def api_unassigned_tags():
    with get_conn() as conn:
        # All distinct non-blank CUR tags
        all_tags = {r["workloads_tag"] for r in conn.execute(
            "SELECT DISTINCT workloads_tag FROM cur_data WHERE workloads_tag != ''"
        ).fetchall()}
        # All workload names + cur_tag overrides
        workloads = conn.execute("SELECT name, cur_tag FROM workloads").fetchall()
    matched = set()
    for w in workloads:
        matched.add(w["name"].lower())
        if w["cur_tag"]:
            matched.add(w["cur_tag"].lower())
    unassigned = sorted(t for t in all_tags if t.lower() not in matched)
    return jsonify({"tags": unassigned})


# ── API: auto-create workloads from CUR tags ──────────────────────────────────

@app.route("/AWSFinOps/api/workloads/discover", methods=["POST"])
@login_required
def api_discover_workloads():
    """Insert any workloads_tag from cur_data not already in the workloads table."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT workloads_tag,
                   (SELECT outcomegroup FROM cur_data c2
                    WHERE c2.workloads_tag = c1.workloads_tag AND c2.outcomegroup IS NOT NULL
                    LIMIT 1) AS outcomegroup
            FROM cur_data c1
            WHERE workloads_tag != ''
            GROUP BY workloads_tag
        """).fetchall()
        added = 0
        for r in rows:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO workloads (name, domain) VALUES (?, ?)",
                    (r["workloads_tag"], r["outcomegroup"]),
                )
                added += conn.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass
    return jsonify({"added": added})


# ── API: summary ──────────────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/summary", methods=["GET"])
@login_required
def api_summary():
    actual_months = set(get_available_months())

    with get_conn() as conn:
        fc_rows = conn.execute(
            "SELECT month, forecast_run, forecast_project FROM monthly_inputs "
            "WHERE forecast_run IS NOT NULL OR forecast_project IS NOT NULL ORDER BY month"
        ).fetchall()
    forecast_map = {r["month"]: dict(r) for r in fc_rows}

    all_months = sorted(actual_months | set(forecast_map.keys()))
    result = []
    for m in all_months:
        fc = forecast_map.get(m, {})
        if m in actual_months:
            try:
                d = compute(m)
                result.append({
                    "month":                   m,
                    "run_finops":              d["total_consumption_finops"],
                    "project_finops":          d["total_project_finops"],
                    "run_actual":              d["total_consumption_actual"],
                    "run_shared_alloc":        d["total_consumption_shared_alloc"],
                    "run_telstra_diff":        d["total_consumption_telstra_diff"],
                    "project_actual":          d["total_project_actual"],
                    "project_shared_alloc":    d["total_project_shared_alloc"],
                    "project_telstra_diff":    d["total_project_telstra_diff"],
                    "marketplace_pos_adj":     d["total_marketplace_pos_adj"],
                    "grand_total":             d["grand_total"],
                    "telstra_invoice":         d["telstra_invoice"] or 0,
                    "forecast_run":            fc.get("forecast_run"),
                    "forecast_project":        fc.get("forecast_project"),
                    "run_workloads":           [{"name": r["workload"], "actual": r["actual"], "marketplace": r["actual_marketplace"]} for r in d["consumption_rows"] if r["workload"] != "Other"],
                    "project_workloads":       [{"name": r["workload"], "actual": r["actual"], "shared_alloc": r["shared_alloc"], "telstra_diff": r["telstra_diff"], "budget_monthly": r["budget_monthly"], "domain": r["domain"]} for r in d["project_rows"]],
                })
            except Exception as e:
                log.warning(f"Summary compute error for {m}: {e}")
        else:
            result.append({
                "month":           m,
                "run_finops":      None,
                "project_finops":  None,
                "grand_total":     None,
                "telstra_invoice": 0,
                "forecast_run":    fc.get("forecast_run"),
                "forecast_project":fc.get("forecast_project"),
            })
    return jsonify({"months": result})


# ── API: receiving — forecast ─────────────────────────────────────────────────

@app.route("/AWSFinOps/api/receiving/forecast/<month>", methods=["GET"])
@login_required
def api_receiving_forecast_get(month):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT received_forecast, forecast_note FROM receiving_forecast WHERE month=?", (month,)
        ).fetchone()
    return jsonify(dict(row) if row else {"received_forecast": None, "forecast_note": ""})


@app.route("/AWSFinOps/api/receiving/forecast/<month>", methods=["POST"])
@login_required
def api_receiving_forecast_save(month):
    data = request.get_json(force=True)
    try:
        forecast = float(data.get("received_forecast") or 0) or None
    except (TypeError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    note = (data.get("forecast_note") or "").strip()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO receiving_forecast (month, received_forecast, forecast_note) VALUES (?,?,?) "
            "ON CONFLICT(month) DO UPDATE SET received_forecast=excluded.received_forecast, "
            "forecast_note=excluded.forecast_note, updated_at=datetime('now')",
            (month, forecast, note),
        )
    log.info(f"Receiving forecast saved: {month} by {session.get('username','')}")
    return jsonify({"ok": True})


@app.route("/AWSFinOps/api/receiving/forecast-estimate/<month>", methods=["GET"])
@login_required
def api_receiving_forecast_estimate(month):
    """
    Auto-calculate received forecast from CUR data for the Receiving page.

    Formula:
        base = monthly_expense (all workloads) + marketplace CUR − marketplace adjustments paid via PO
             = monthly_expense + unadjusted marketplace
    Unadjusted marketplace = CUR marketplace total − abs(negative adjustments for this month).
    Negative adjustments represent marketplace purchases paid via separate PO (excluded from Telstra scope).
    Marketplace with no adjustment flows through to Telstra invoice and must be included.

    If the CUR was uploaded mid-month, extrapolate to month-end using daily run rate.
    """
    with get_conn() as conn:
        expense_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM cur_data WHERE month=? AND category='monthly_expense'",
            (month,),
        ).fetchone()[0]

        marketplace_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM cur_data WHERE month=? AND category='marketplace'",
            (month,),
        ).fetchone()[0]

        # Negative adjustments = marketplace paid via separate PO (removed from Telstra scope)
        adj_removed = conn.execute(
            "SELECT COALESCE(SUM(adjustment), 0) FROM marketplace_adjustments WHERE month=? AND adjustment < 0",
            (month,),
        ).fetchone()[0]

        upload_row = conn.execute(
            "SELECT uploaded_at FROM upload_log ORDER BY id DESC LIMIT 1"
        ).fetchone()

    # unadjusted marketplace = CUR marketplace - what was removed via PO adjustment
    unadjusted_mkt = max(0.0, float(marketplace_total) + float(adj_removed))  # adj_removed is negative
    base_total = float(expense_total) + unadjusted_mkt

    if base_total == 0:
        return jsonify({"estimate": None, "note": "No CUR data for this month."})

    upload_dt = None
    if upload_row and upload_row[0]:
        try:
            upload_dt = datetime.datetime.fromisoformat(upload_row[0].replace("Z", "+00:00"))
        except Exception:
            try:
                upload_dt = datetime.datetime.strptime(upload_row[0][:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                upload_dt = None

    try:
        year, mon, _ = month.split("-")
        year, mon = int(year), int(mon)
    except Exception:
        return jsonify({"estimate": None, "error": "Invalid month format"}), 400

    days_in_month = calendar.monthrange(year, mon)[1]

    mkt_note = ""
    if unadjusted_mkt > 0:
        mkt_note = f" + ${unadjusted_mkt:,.2f} unadjusted marketplace"
    elif float(marketplace_total) > 0:
        mkt_note = f" (marketplace ${float(marketplace_total):,.2f} fully adjusted via PO — excluded)"

    if upload_dt and upload_dt.year == year and upload_dt.month == mon:
        days_elapsed = upload_dt.day
        if days_elapsed < days_in_month:
            estimate = round(base_total * days_in_month / days_elapsed, 2)
            note = (f"CUR uploaded {upload_dt.strftime('%-d %b')} ({days_elapsed}/{days_in_month} days). "
                    f"Base: ${base_total:,.2f} (expense${mkt_note}) × {days_in_month}/{days_elapsed} "
                    f"= ${estimate:,.2f}")
            return jsonify({
                "estimate": estimate,
                "expense_total": round(float(expense_total), 2),
                "marketplace_total": round(float(marketplace_total), 2),
                "unadjusted_mkt": round(unadjusted_mkt, 2),
                "base_total": round(base_total, 2),
                "days_elapsed": days_elapsed,
                "total_days": days_in_month,
                "is_extrapolated": True,
                "note": note,
            })

    estimate = round(base_total, 2)
    note = f"Full month data. Expense: ${float(expense_total):,.2f}{mkt_note} = ${estimate:,.2f}"
    return jsonify({
        "estimate": estimate,
        "expense_total": round(float(expense_total), 2),
        "marketplace_total": round(float(marketplace_total), 2),
        "unadjusted_mkt": round(unadjusted_mkt, 2),
        "base_total": estimate,
        "days_elapsed": days_in_month,
        "total_days": days_in_month,
        "is_extrapolated": False,
        "note": note,
    })


# ── API: receiving — invoice upload ───────────────────────────────────────────

@app.route("/AWSFinOps/api/receiving/invoice/<month>", methods=["GET"])
@login_required
def api_receiving_invoice_get(month):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, filename, account_number, validated, total_new_charges, uploaded_at "
            "FROM invoice_uploads WHERE month=? ORDER BY id DESC LIMIT 1", (month,)
        ).fetchone()
        if not row:
            return jsonify({"invoice": None})
        inv = dict(row)
        items = conn.execute(
            "SELECT line_type, description, amount, po_number, workload_match "
            "FROM invoice_line_items WHERE invoice_id=?", (inv["id"],)
        ).fetchall()
        inv["line_items"] = [dict(i) for i in items]
        # Include marketplace adjustments so the modal can populate the orange box
        adj_rows = conn.execute(
            "SELECT workload, adjustment, note, po_number, purchaser_name "
            "FROM marketplace_adjustments WHERE month=? AND adjustment != 0",
            (month,),
        ).fetchall()
        inv["mkt_adjustments"] = [dict(r) for r in adj_rows]
    return jsonify({"invoice": inv})


@app.route("/AWSFinOps/api/receiving/adjustments/<month>", methods=["GET"])
@login_required
def api_receiving_adjustments(month):
    """Return marketplace adjustments for a given month (for the receiving modal)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT workload, adjustment, note, po_number, purchaser_name "
            "FROM marketplace_adjustments WHERE month=? AND adjustment != 0",
            (month,),
        ).fetchall()
    return jsonify({"adjustments": [dict(r) for r in rows]})


@app.route("/AWSFinOps/api/receiving/invoice/<month>", methods=["POST"])
@login_required
def api_receiving_invoice_upload(month):
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file received."}), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted."}), 400

    tmp_path = os.path.join(UPLOAD_TMP, f"{uuid.uuid4().hex}.pdf")
    try:
        f.save(tmp_path)
        pdf_bytes = open(tmp_path, "rb").read()

        from aws_invoice_parser import parse_invoice
        parsed = parse_invoice(tmp_path)

        # Match marketplace lines to adjusted workloads for this month
        with get_conn() as conn:
            adj_rows = conn.execute(
                "SELECT workload, adjustment, note, po_number, purchaser_name FROM marketplace_adjustments WHERE month=?",
                (month,),
            ).fetchall()
        adj_map = {r["workload"]: {"adj": float(r["adjustment"]), "note": r["note"] or "", "po_number": r["po_number"] or "", "purchaser_name": r["purchaser_name"] or ""} for r in adj_rows}

        # Assign workload matches to marketplace lines based on amount proximity
        mkt_lines = parsed["marketplace_lines"]
        adj_items = [{"workload": k, **v} for k, v in adj_map.items() if v["adj"] != 0]

        used = set()
        for line in mkt_lines:
            best = None
            best_delta = 1e9
            for item in adj_items:
                if item["workload"] in used:
                    continue
                # adjustments are negative (removed), invoice amounts positive
                delta = abs(line["amount"] - abs(item["adj"]))
                if delta < best_delta:
                    best_delta = delta
                    best = item
            if best and best_delta < max(50, line["amount"] * 0.05):
                line["workload_match"] = best["workload"]
                used.add(best["workload"])
            else:
                line["workload_match"] = ""

        with get_conn() as conn:
            # Remove previous upload for this month
            old = conn.execute(
                "SELECT id FROM invoice_uploads WHERE month=?", (month,)
            ).fetchall()
            for o in old:
                conn.execute("DELETE FROM invoice_line_items WHERE invoice_id=?", (o["id"],))
            conn.execute("DELETE FROM invoice_uploads WHERE month=?", (month,))

            conn.execute(
                "INSERT INTO invoice_uploads (month, filename, pdf_blob, account_number, validated, total_new_charges, uploaded_by) "
                "VALUES (?,?,?,?,?,?,?)",
                (month, f.filename, pdf_bytes, parsed["account_number"],
                 1 if parsed["validated"] else 0,
                 parsed["total_new_charges"],
                 session.get("username", "")),
            )
            inv_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for line in parsed["all_lines"]:
                conn.execute(
                    "INSERT INTO invoice_line_items (invoice_id, month, line_type, description, amount, po_number, workload_match) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (inv_id, month, line["line_type"], line["description"],
                     line["amount"], line.get("po_number", ""), line.get("workload_match", "")),
                )

        # Return adj_rows with new fields for the frontend modal
        with get_conn() as conn:
            fresh_adj = conn.execute(
                "SELECT workload, adjustment, note, po_number, purchaser_name "
                "FROM marketplace_adjustments WHERE month=?", (month,)
            ).fetchall()

        log.info(f"Invoice uploaded for {month}: {f.filename} by {session.get('username','')}")
        return jsonify({
            "ok":                True,
            "account_number":    parsed["account_number"],
            "validated":         parsed["validated"],
            "total_new_charges": parsed["total_new_charges"],
            "marketplace_lines": mkt_lines,
            "all_lines":         parsed["all_lines"],
            "mkt_adjustments":   [dict(r) for r in fresh_adj],
        })
    except Exception as e:
        log.error(f"Invoice upload error for {month}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


@app.route("/AWSFinOps/api/receiving/invoice/<month>/raw-text", methods=["GET"])
@login_required
def api_receiving_invoice_raw(month):
    """Debug endpoint — returns raw text extracted from the stored PDF."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT pdf_blob FROM invoice_uploads WHERE month=? ORDER BY id DESC LIMIT 1", (month,)
        ).fetchone()
    if not row or not row["pdf_blob"]:
        return jsonify({"error": "No invoice found."}), 404
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(row["pdf_blob"])
        tmp = f.name
    try:
        from aws_invoice_parser import _extract_text
        text = _extract_text(tmp)
        return jsonify({"text": text, "length": len(text)})
    finally:
        try: os.remove(tmp)
        except Exception: pass


@app.route("/AWSFinOps/api/receiving/invoice/<month>/reparse", methods=["POST"])
@login_required
def api_receiving_invoice_reparse(month):
    """Re-run the parser on the stored PDF blob and update line items."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, pdf_blob, filename FROM invoice_uploads WHERE month=? ORDER BY id DESC LIMIT 1", (month,)
        ).fetchone()
    if not row or not row["pdf_blob"]:
        return jsonify({"error": "No invoice found."}), 404

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(row["pdf_blob"])
        tmp = f.name
    try:
        from aws_invoice_parser import parse_invoice
        parsed = parse_invoice(tmp)

        with get_conn() as conn:
            adj_rows = conn.execute(
                "SELECT workload, adjustment, note, po_number, purchaser_name FROM marketplace_adjustments WHERE month=?", (month,)
            ).fetchall()
        adj_map = {r["workload"]: {"adj": float(r["adjustment"]), "note": r["note"] or "", "po_number": r["po_number"] or "", "purchaser_name": r["purchaser_name"] or ""} for r in adj_rows}
        adj_items = [{"workload": k, **v} for k, v in adj_map.items() if v["adj"] != 0]

        mkt_lines = parsed["marketplace_lines"]
        used = set()
        for line in mkt_lines:
            best, best_delta = None, 1e9
            for item in adj_items:
                if item["workload"] in used: continue
                delta = abs(line["amount"] - abs(item["adj"]))
                if delta < best_delta:
                    best_delta = delta
                    best = item
            if best and best_delta < max(50, line["amount"] * 0.05):
                line["workload_match"] = best["workload"]
                used.add(best["workload"])
            else:
                line["workload_match"] = ""

        inv_id = row["id"]
        with get_conn() as conn:
            conn.execute("DELETE FROM invoice_line_items WHERE invoice_id=?", (inv_id,))
            conn.execute(
                "UPDATE invoice_uploads SET account_number=?, validated=?, total_new_charges=? WHERE id=?",
                (parsed["account_number"], 1 if parsed["validated"] else 0,
                 parsed["total_new_charges"], inv_id),
            )
            for line in parsed["all_lines"]:
                conn.execute(
                    "INSERT INTO invoice_line_items (invoice_id, month, line_type, description, amount, po_number, workload_match) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (inv_id, month, line["line_type"], line["description"],
                     line["amount"], line.get("po_number", ""), line.get("workload_match", "")),
                )

        log.info(f"Invoice reparsed for {month}")
        return jsonify({
            "ok": True,
            "account_number": parsed["account_number"],
            "validated": parsed["validated"],
            "total_new_charges": parsed["total_new_charges"],
            "marketplace_lines": mkt_lines,
            "all_lines": parsed["all_lines"],
            "raw_text": parsed["raw_text"],
        })
    finally:
        try: os.remove(tmp)
        except Exception: pass


@app.route("/AWSFinOps/api/receiving/invoice/<month>/pdf", methods=["GET"])
@login_required
def api_receiving_invoice_pdf(month):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT filename, pdf_blob FROM invoice_uploads WHERE month=? ORDER BY id DESC LIMIT 1",
            (month,),
        ).fetchone()
    if not row or not row["pdf_blob"]:
        return jsonify({"error": "No invoice found."}), 404
    resp = make_response(row["pdf_blob"])
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f'inline; filename="{row["filename"]}"'
    return resp


# ── API: receiving — email ─────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/receiving/send-email/<month>", methods=["POST"])
@login_required
def api_receiving_send_email(month):
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.application import MIMEApplication
        from email.utils import formatdate

        with get_conn() as conn:
            inv_row = conn.execute(
                "SELECT id, filename, pdf_blob, account_number, validated, total_new_charges FROM invoice_uploads "
                "WHERE month=? ORDER BY id DESC LIMIT 1", (month,)
            ).fetchone()
            fc_row = conn.execute(
                "SELECT received_forecast, forecast_note FROM receiving_forecast WHERE month=?", (month,)
            ).fetchone()
            adj_rows = conn.execute(
                "SELECT workload, adjustment, note, po_number, purchaser_name "
                "FROM marketplace_adjustments WHERE month=? AND adjustment != 0",
                (month,)
            ).fetchall()

        if not inv_row:
            return jsonify({"error": "No invoice uploaded for this month."}), 400

        inv    = dict(inv_row)
        fc     = dict(fc_row) if fc_row else {}
        adjs   = [dict(r) for r in adj_rows]

        received_forecast = float(fc.get("received_forecast") or 0)
        total_new_charges = float(inv.get("total_new_charges") or 0)
        mkt_adj_total     = abs(sum(float(r["adjustment"]) for r in adjs if float(r["adjustment"]) < 0))
        gap               = total_new_charges - received_forecast - mkt_adj_total

        _MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        _mp = month.split("-")
        display_month = f"{_MONTH_NAMES[int(_mp[1])-1]} '{_mp[0][2:]}"
        gap_color     = "#C0392B" if gap > 0 else "#1B7340"
        gap_label     = "Underpaid — update Finance tool" if gap > 0 else "Overpaid / Credit"
        acct_status   = "&#x2705; Validated" if inv.get("validated") else "&#x26A0;&#xFE0F; Not matched"

        def fmtd(v): return f"${v:,.2f}"

        mkt_rows_html = ""
        for a in adjs:
            amt = abs(float(a["adjustment"]))
            mkt_rows_html += (
                '<tr>'
                '<td style="padding:10px 14px;border-bottom:1px solid #EEF0F3">' + (a["workload"] or "") + '</td>'
                '<td style="padding:10px 14px;border-bottom:1px solid #EEF0F3">' + (a.get("po_number") or "—") + '</td>'
                '<td style="padding:10px 14px;border-bottom:1px solid #EEF0F3">' + (a.get("purchaser_name") or "—") + '</td>'
                '<td style="padding:10px 14px;border-bottom:1px solid #EEF0F3">' + (a.get("note") or "—") + '</td>'
                '<td style="padding:10px 14px;border-bottom:1px solid #EEF0F3;text-align:right;font-weight:600">' + fmtd(amt) + '</td>'
                '</tr>'
            )

        if not mkt_rows_html:
            mkt_rows_html = '<tr><td colspan="5" style="padding:14px;text-align:center;color:#888">No marketplace purchases recorded for this month</td></tr>'

        html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F4F6FA;font-family:'Segoe UI',Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F6FA;padding:32px 0">
  <tr><td align="center">
    <table width="640" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08)">

      <!-- Header -->
      <tr><td style="background:linear-gradient(135deg,#1A2744 0%,#2B3F6B 100%);padding:28px 36px">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td>
              <div style="color:#F0C040;font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:4px">AWS FinOps</div>
              <div style="color:#fff;font-size:22px;font-weight:700">Marketplace Receiving Summary</div>
              <div style="color:#A8B8D8;font-size:13px;margin-top:4px">Consumption Month: {display_month}</div>
            </td>
            <td align="right" style="color:#F0C040;font-size:32px">&#128230;</td>
          </tr>
        </table>
      </td></tr>

      <!-- Account badge -->
      <tr><td style="padding:20px 36px 0">
        <table cellpadding="0" cellspacing="0">
          <tr>
            <td style="background:#EBF5EB;border:1px solid #A5D6A7;border-radius:6px;padding:8px 14px;font-size:12px;color:#1B7340;font-weight:600">
              {acct_status} &nbsp;·&nbsp; Account {inv['account_number']}
            </td>
            <td width="12"></td>
            <td style="font-size:12px;color:#666">Invoice: <strong>{inv['filename']}</strong></td>
          </tr>
        </table>
      </td></tr>

      <!-- Summary cards -->
      <tr><td style="padding:20px 36px">
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:10px 0">
          <tr>
            <td style="background:#F8FAFE;border:1px solid #DDE4EF;border-radius:8px;padding:14px 16px;width:33%">
              <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px">Total New Charges</div>
              <div style="font-size:20px;font-weight:700;color:#1A2744">{fmtd(total_new_charges)}</div>
              <div style="font-size:11px;color:#888;margin-top:2px">From invoice excl. GST</div>
            </td>
            <td width="10"></td>
            <td style="background:#F8FAFE;border:1px solid #DDE4EF;border-radius:8px;padding:14px 16px;width:33%">
              <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px">Received Forecast</div>
              <div style="font-size:20px;font-weight:700;color:#1A2744">{fmtd(received_forecast)}</div>
              <div style="font-size:11px;color:#888;margin-top:2px">Pre-invoice estimate</div>
            </td>
            <td width="10"></td>
            <td style="background:#F8FAFE;border:1px solid #DDE4EF;border-radius:8px;padding:14px 16px;width:33%">
              <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px">Marketplace (PO)</div>
              <div style="font-size:20px;font-weight:700;color:#1A2744">{fmtd(mkt_adj_total)}</div>
              <div style="font-size:11px;color:#888;margin-top:2px">Separate PO purchases</div>
            </td>
          </tr>
        </table>
      </td></tr>

      <!-- Gap -->
      <tr><td style="padding:0 36px 20px">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="background:{gap_color};border-radius:8px;padding:16px 20px">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <div style="color:rgba(255,255,255,.8);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px">Gap Amount</div>
                    <div style="color:#fff;font-size:26px;font-weight:700;margin-top:2px">{fmtd(gap)}</div>
                    <div style="color:rgba(255,255,255,.75);font-size:11px;margin-top:4px">{gap_label}</div>
                  </td>
                  <td align="right" style="color:rgba(255,255,255,.35);font-size:48px">&#9651;</td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </td></tr>

      <!-- Formula note -->
      <tr><td style="padding:0 36px 20px">
        <div style="background:#FFFBEB;border:1px solid #F0C040;border-radius:6px;padding:10px 14px;font-size:12px;color:#6B5200">
          <strong>Gap formula:</strong> Total New Charges &minus; Received Forecast &minus; Marketplace (PO) =
          <strong>{fmtd(total_new_charges)} &minus; {fmtd(received_forecast)} &minus; {fmtd(mkt_adj_total)} = {fmtd(gap)}</strong>
        </div>
      </td></tr>

      <!-- Marketplace table -->
      <tr><td style="padding:0 36px 28px">
        <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:#1A2744;margin-bottom:10px">
          Marketplace PO Purchases
        </div>
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #DDE4EF;border-radius:8px;overflow:hidden">
          <thead>
            <tr style="background:#F4F6FA">
              <th style="padding:10px 14px;text-align:left;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">Workload</th>
              <th style="padding:10px 14px;text-align:left;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">PO Number</th>
              <th style="padding:10px 14px;text-align:left;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">Purchaser</th>
              <th style="padding:10px 14px;text-align:left;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">Description</th>
              <th style="padding:10px 14px;text-align:right;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">Amount</th>
            </tr>
          </thead>
          <tbody>
            {mkt_rows_html}
            <tr style="background:#F8FAFE">
              <td colspan="4" style="padding:10px 14px;font-weight:700;font-size:12px">Total</td>
              <td style="padding:10px 14px;text-align:right;font-weight:700;font-size:13px;color:#1A2744">{fmtd(mkt_adj_total)}</td>
            </tr>
          </tbody>
        </table>
      </td></tr>

      <!-- Footer -->
      <tr><td style="background:#F4F6FA;border-top:1px solid #DDE4EF;padding:18px 36px">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="font-size:11px;color:#888">
              Generated by <strong>AWS FinOps Tracker</strong> &nbsp;·&nbsp; {display_month} &nbsp;·&nbsp;
              Invoice attached as PDF
            </td>
          </tr>
        </table>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""

        smtp_host = os.environ.get("SMTP_HOST", "smtp.cochlear.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "25"))
        from_addr = os.environ.get("SMTP_FROM", "noreply-awsfinops@cochlear.com")
        to_addr   = "global-aws-finops@cochlear.com"

        msg = MIMEMultipart("mixed")
        msg["Subject"] = f"AWS Marketplace Receiving — {display_month}"
        msg["From"]    = from_addr
        msg["To"]      = to_addr
        msg["Date"]    = formatdate(localtime=True)

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(html_body, "html", "utf-8"))
        msg.attach(alt)

        if inv.get("pdf_blob"):
            att = MIMEApplication(inv["pdf_blob"], _subtype="pdf")
            att.add_header("Content-Disposition", "attachment", filename=inv["filename"])
            msg.attach(att)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.sendmail(from_addr, [to_addr], msg.as_string())

        log.info(f"Receiving email sent for {month} by {session.get('username','')}")
        return jsonify({"ok": True, "to": to_addr})

    except Exception as e:
        log.error(f"Email send error for {month}: {e}")
        return jsonify({"error": str(e)}), 500


# ── API: project email (MES / CNA / ADA) ─────────────────────────────────────

_ADA_WORKLOADS = {"Clark AI", "DataInsights", "Sonar", "Model Gateway"}
_ADA_GROUP_BUDGET = 244_000 / 12   # $20,333.33/mo group total

@app.route("/AWSFinOps/api/project-email/<month>/<workload_key>", methods=["POST"])
@login_required
def api_project_email(month, workload_key):
    """Send monthly cost summary email for MES, CNA, or ADA."""
    try:
        import smtplib, calendar as _cal
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.utils import formatdate

        if workload_key not in ("MES", "CNA", "ADA"):
            return jsonify({"error": "workload_key must be MES, CNA or ADA"}), 400

        is_ada = workload_key == "ADA"
        _MN = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

        def _display(m):
            p = m.split("-"); return f"{_MN[int(p[1])-1]} '{p[0][2:]}"

        def _prev_month(m, n):
            y, mo, _ = (int(x) for x in m.split("-"))
            for _ in range(n):
                mo -= 1
                if mo == 0: mo = 12; y -= 1
            return f"{y:04d}-{mo:02d}-01"

        # ── gather current + last 3 months data ──────────────────────────────
        months_needed = [month] + [_prev_month(month, i) for i in range(1, 4)]

        def _extract(d, wl_key):
            """Pull relevant figures from compute() output for this workload key."""
            if wl_key == "ADA":
                rows = [r for r in d["project_rows"] if r["domain"] == "ADA" or r["workload"] in _ADA_WORKLOADS]
                actual      = sum(r["actual"] for r in rows)
                marketplace = sum(r.get("actual_marketplace", 0) for r in rows)
                finops      = actual          # ADA: no shared alloc / telstra diff
                budget      = _ADA_GROUP_BUDGET
                shared      = 0.0
                return {"actual": actual, "marketplace": marketplace, "finops": finops,
                        "budget": budget, "shared": shared, "rows": rows}
            else:
                row = next((r for r in d["project_rows"] if r["workload"] == wl_key), None)
                if row is None:
                    return None
                return {"actual": row["actual"], "marketplace": row.get("actual_marketplace", 0),
                        "finops": row["total"], "budget": row.get("budget_monthly") or 0,
                        "shared": row["shared_alloc"], "rows": [row]}

        computed = {}
        for m in months_needed:
            try:
                computed[m] = compute(m)
            except Exception:
                computed[m] = None

        cur = _extract(computed[month], workload_key) if computed[month] else None
        if cur is None:
            return jsonify({"error": f"No data for {workload_key} in {month}"}), 400

        # forecast from monthly_inputs
        mi = computed[month]
        forecast_val = mi.get("forecast_project") if mi else None

        # last 3 prior months trend
        trend_months = months_needed[1:]
        trend = []
        for m in trend_months:
            if computed.get(m):
                ex = _extract(computed[m], workload_key)
                if ex:
                    trend.append({"month": m, "display": _display(m), "finops": ex["finops"],
                                  "actual": ex["actual"], "marketplace": ex["marketplace"]})

        # ── marketplace adjustments ───────────────────────────────────────────
        with get_conn() as conn:
            if is_ada:
                # all ADA workloads
                placeholders = ",".join("?" * len(_ADA_WORKLOADS))
                adj_rows = conn.execute(
                    f"SELECT workload, adjustment, note, po_number, purchaser_name "
                    f"FROM marketplace_adjustments WHERE month=? AND workload IN ({placeholders}) AND adjustment != 0",
                    (month, *_ADA_WORKLOADS),
                ).fetchall()
            else:
                adj_rows = conn.execute(
                    "SELECT workload, adjustment, note, po_number, purchaser_name "
                    "FROM marketplace_adjustments WHERE month=? AND workload=? AND adjustment != 0",
                    (month, workload_key),
                ).fetchall()
        adjs = [dict(r) for r in adj_rows]
        mkt_adj_total = abs(sum(float(r["adjustment"]) for r in adjs if float(r["adjustment"]) < 0))

        # ── display helpers ───────────────────────────────────────────────────
        display_month = _display(month)

        def fmtd(v):
            return f"${v:,.2f}" if v is not None else "—"

        def fmts(v, prefix=""):
            if v is None: return "—"
            sign = "+" if v >= 0 else ""
            return f"{prefix}{sign}${v:,.2f}"

        # Period-aware budget for CNA (Jul-Dec $35,700 · Jan-Jun $64,000)
        def _period_budget(wl_key, m, db_budget):
            if wl_key == "CNA":
                return 64000.0 if int(m[5:7]) <= 6 else 35700.0
            return db_budget

        workload_budget = _period_budget(workload_key, month, cur["budget"]) if not is_ada else _ADA_GROUP_BUDGET

        # deviation: cross-charge total vs workload budget
        cur_actual_val = cur["actual"]
        cur_finops_val = cur["finops"]
        if is_ada:
            deviation = cur_actual_val - _ADA_GROUP_BUDGET
            dev_formula = "Actual " + fmtd(cur_actual_val) + " − Group Budget " + fmtd(_ADA_GROUP_BUDGET) + " = " + fmts(deviation)
            dev_label   = "Over budget" if deviation > 0 else "Within budget"
            forecast_label = "Group budget " + fmtd(_ADA_GROUP_BUDGET) + "/mo"
        else:
            deviation = cur_finops_val - workload_budget
            dev_formula = "Total Cross Charge Amount " + fmtd(cur_finops_val) + " − Budget " + fmtd(workload_budget) + " = " + fmts(deviation)
            dev_label   = "Over budget" if deviation > 0 else "Under budget"
            forecast_label = fmtd(workload_budget)

        dev_color = "#C0392B" if (deviation or 0) > 0 else "#1B7340"

        # ── trend rows ────────────────────────────────────────────────────────
        trend_col_hdr = "Actual (no alloc)" if is_ada else "Total Cross Charge"
        trend_html = ""
        if trend:
            trend_rows = ""
            for t in trend:
                trend_rows += (
                    '<tr>'
                    '<td style="padding:9px 14px;border-bottom:1px solid #EEF0F3;font-weight:600">' + t["display"] + '</td>'
                    '<td style="padding:9px 14px;border-bottom:1px solid #EEF0F3;text-align:right">' + fmtd(t["actual"]) + '</td>'
                    '<td style="padding:9px 14px;border-bottom:1px solid #EEF0F3;text-align:right">' + fmtd(t["marketplace"]) + '</td>'
                    '<td style="padding:9px 14px;border-bottom:1px solid #EEF0F3;text-align:right;font-weight:600">' + fmtd(t["finops"]) + '</td>'
                    '</tr>'
                )
            trend_html = (
                '<tr><td style="padding:0 36px 20px">'
                '<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:#1A2744;margin-bottom:10px">Last 3 Months Trend</div>'
                '<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #DDE4EF;border-radius:8px;overflow:hidden">'
                '<thead><tr style="background:#F4F6FA">'
                '<th style="padding:9px 14px;text-align:left;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">Month</th>'
                '<th style="padding:9px 14px;text-align:right;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">Actuals</th>'
                '<th style="padding:9px 14px;text-align:right;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">Marketplace</th>'
                '<th style="padding:9px 14px;text-align:right;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">' + trend_col_hdr + '</th>'
                '</tr></thead>'
                '<tbody>' + trend_rows + '</tbody>'
                '</table>'
                '</td></tr>'
            )

        # ── marketplace table ─────────────────────────────────────────────────
        mkt_rows_html = ""
        for a in adjs:
            amt = abs(float(a["adjustment"]))
            mkt_rows_html += (
                '<tr>'
                '<td style="padding:10px 14px;border-bottom:1px solid #EEF0F3">' + (a["workload"] or "") + '</td>'
                '<td style="padding:10px 14px;border-bottom:1px solid #EEF0F3">' + (a.get("po_number") or "—") + '</td>'
                '<td style="padding:10px 14px;border-bottom:1px solid #EEF0F3">' + (a.get("purchaser_name") or "—") + '</td>'
                '<td style="padding:10px 14px;border-bottom:1px solid #EEF0F3">' + (a.get("note") or "—") + '</td>'
                '<td style="padding:10px 14px;border-bottom:1px solid #EEF0F3;text-align:right;font-weight:600">' + fmtd(amt) + '</td>'
                '</tr>'
            )
        if not mkt_rows_html:
            mkt_rows_html = '<tr><td colspan="5" style="padding:14px;text-align:center;color:#888">No marketplace purchases recorded for this month</td></tr>'

        # ── ADA workload breakdown (per-workload rows for ADA email) ──────────
        ada_breakdown_html = ""
        if is_ada and computed[month]:
            ada_wl_rows = [r for r in computed[month]["project_rows"]
                           if r["domain"] == "ADA" or r["workload"] in _ADA_WORKLOADS]
            if ada_wl_rows:
                def _ada_row(r):
                    mkt = r.get("actual_marketplace", 0)
                    mkt_str = fmtd(mkt) if mkt else "—"
                    return (
                        '<tr>'
                        '<td style="padding:9px 14px;border-bottom:1px solid #EEF0F3">' + r["workload"] + '</td>'
                        '<td style="padding:9px 14px;border-bottom:1px solid #EEF0F3;text-align:right">' + fmtd(r["actual"] - mkt) + '</td>'
                        '<td style="padding:9px 14px;border-bottom:1px solid #EEF0F3;text-align:right">' + mkt_str + '</td>'
                        '<td style="padding:9px 14px;border-bottom:1px solid #EEF0F3;text-align:right;font-weight:600">' + fmtd(r["actual"]) + '</td>'
                        '</tr>'
                    )
                rows_html = "".join(_ada_row(r) for r in ada_wl_rows)
                ada_breakdown_html = f"""
      <tr><td style="padding:0 36px 20px">
        <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:#2E7D32;margin-bottom:10px">ADA Workload Breakdown</div>
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #A5D6A7;border-radius:8px;overflow:hidden">
          <thead><tr style="background:#E8F5E9">
            <th style="padding:9px 14px;text-align:left;font-size:11px;font-weight:700;color:#2E7D32;text-transform:uppercase;letter-spacing:.5px">Workload</th>
            <th style="padding:9px 14px;text-align:right;font-size:11px;font-weight:700;color:#2E7D32;text-transform:uppercase;letter-spacing:.5px">Expense</th>
            <th style="padding:9px 14px;text-align:right;font-size:11px;font-weight:700;color:#2E7D32;text-transform:uppercase;letter-spacing:.5px">Marketplace</th>
            <th style="padding:9px 14px;text-align:right;font-size:11px;font-weight:700;color:#2E7D32;text-transform:uppercase;letter-spacing:.5px">Total Actual</th>
          </tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
      </td></tr>"""

        # ── shared alloc note for MES/CNA ─────────────────────────────────────
        shared_note_html = ""
        if not is_ada and cur["shared"] > 0:
            shared_note_html = (
                '<tr><td style="padding:0 36px 20px">'
                '<div style="background:#EEF2FF;border:1px solid #C5CAE9;border-radius:6px;padding:10px 14px;font-size:12px;color:#283593">'
                '<strong>Total Cross Charge Amount includes shared cost allocation:</strong> '
                'Actuals ' + fmtd(cur["actual"]) + ' + Shared Alloc ' + fmtd(cur["shared"]) + ' = Total Cross Charge ' + fmtd(cur["finops"]) +
                '<span style="color:#666;font-size:11px;margin-left:6px">(Shared pool distributed proportionally across all Run &amp; Project workloads)</span>'
                '</div>'
                '</td></tr>'
            )

        # ── header colour ─────────────────────────────────────────────────────
        if is_ada:
            hdr_grad = "linear-gradient(135deg,#1B5E20 0%,#2E7D32 100%)"
            hdr_icon = "&#127808;"   # leaf
            hdr_sub  = "ADA Projects (Clark AI · DataInsights · Sonar · Model Gateway)"
        else:
            hdr_grad = "linear-gradient(135deg,#1A2744 0%,#2B3F6B 100%)"
            hdr_icon = "&#128202;"   # bar chart
            hdr_sub  = f"Project X-charge workload"

        # ── pre-compute all conditional strings (avoid expressions inside f-strings) ──
        subject         = "AWS FinOps — " + workload_key + " Monthly Cost Summary — " + display_month
        kpi_budget_lbl  = "Group Budget" if is_ada else "Budget per month"
        kpi_budget_sub  = "USD 244,000/yr · transferred to ISD" if is_ada else "Monthly workload budget"
        dev_arrow       = "&#9651;" if (deviation or 0) > 0 else "&#9661;"
        finops_row_html = "" if is_ada else (
            '<tr><td style="padding:0 36px 16px">'
            '<table width="100%" cellpadding="0" cellspacing="0"><tr>'
            '<td style="background:#F8FAFE;border:1px solid #DDE4EF;border-radius:8px;padding:14px 16px">'
            '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px">Total Cross Charge Amount</div>'
            '<div style="font-size:20px;font-weight:700;color:#1A2744">' + fmtd(cur["finops"]) + '</div>'
            '<div style="font-size:11px;color:#888;margin-top:2px">Actuals + shared cost allocation + Telstra diff</div>'
            '</td></tr></table></td></tr>'
        )
        cur_actual_str    = fmtd(cur["actual"])
        cur_mkt_str       = fmtd(cur["marketplace"])
        dev_str           = fmts(deviation)
        mkt_adj_total_str = fmtd(mkt_adj_total)

        html_body = (
"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F4F6FA;font-family:'Segoe UI',Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F6FA;padding:32px 0">
  <tr><td align="center">
    <table width="660" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08)">
      <tr><td style="background:""" + hdr_grad + """;padding:36px 40px">
        <table width="100%" cellpadding="0" cellspacing="0"><tr>
          <td>
            <div style="color:#F0C040;font-size:12px;font-weight:800;letter-spacing:2px;text-transform:uppercase;margin-bottom:10px">AWS FinOps &middot; """ + workload_key + """ &middot; Monthly Cost Report</div>
            <div style="color:#fff;font-size:36px;font-weight:800;line-height:1.15;letter-spacing:-.5px">""" + workload_key + """ Cost Summary</div>
            <div style="color:rgba(255,255,255,.85);font-size:17px;font-weight:600;margin-top:8px">""" + hdr_sub + """</div>
            <div style="display:inline-block;margin-top:12px;background:rgba(255,255,255,.15);border-radius:20px;padding:5px 14px;color:rgba(255,255,255,.9);font-size:13px;font-weight:600;letter-spacing:.3px">&#128197; Consumption Month: """ + display_month + """</div>
          </td>
          <td align="right" style="color:rgba(255,255,255,.2);font-size:72px;vertical-align:top;padding-top:4px">""" + hdr_icon + """</td>
        </tr></table>
      </td></tr>
      <tr><td style="padding:24px 36px 16px">
        <table width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="background:#F8FAFE;border:1px solid #DDE4EF;border-radius:8px;padding:14px 16px">
            <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px">Total Consumption</div>
            <div style="font-size:20px;font-weight:700;color:#1A2744">""" + cur_actual_str + """</div>
            <div style="font-size:11px;color:#888;margin-top:2px">Expense + marketplace actuals</div>
          </td>
          <td width="10"></td>
          <td style="background:#F8FAFE;border:1px solid #DDE4EF;border-radius:8px;padding:14px 16px">
            <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px">Marketplace (non-adjusted)</div>
            <div style="font-size:20px;font-weight:700;color:#1A2744">""" + cur_mkt_str + """</div>
            <div style="font-size:11px;color:#888;margin-top:2px">CUR marketplace charges</div>
          </td>
          <td width="10"></td>
          <td style="background:#F8FAFE;border:1px solid #DDE4EF;border-radius:8px;padding:14px 16px">
            <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px">""" + kpi_budget_lbl + """</div>
            <div style="font-size:20px;font-weight:700;color:#1A2744">""" + forecast_label + """</div>
            <div style="font-size:11px;color:#888;margin-top:2px">""" + kpi_budget_sub + """</div>
          </td>
        </tr></table>
      </td></tr>
      """ + finops_row_html + """
      <tr><td style="padding:0 36px 16px">
        <table width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="background:""" + dev_color + """;border-radius:8px;padding:16px 20px">
            <table width="100%" cellpadding="0" cellspacing="0"><tr>
              <td>
                <div style="color:rgba(255,255,255,.8);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px">Deviation</div>
                <div style="color:#fff;font-size:26px;font-weight:700;margin-top:2px">""" + dev_str + """</div>
                <div style="color:rgba(255,255,255,.75);font-size:11px;margin-top:4px">""" + dev_label + """</div>
              </td>
              <td align="right" style="color:rgba(255,255,255,.3);font-size:42px">""" + dev_arrow + """</td>
            </tr></table>
          </td>
        </tr></table>
      </td></tr>
      <tr><td style="padding:0 36px 20px">
        <div style="background:#FFFBEB;border:1px solid #F0C040;border-radius:6px;padding:10px 14px;font-size:12px;color:#6B5200">
          <strong>Deviation formula:</strong> """ + dev_formula + """
        </div>
      </td></tr>
      """ + shared_note_html + ada_breakdown_html + trend_html + """
      <tr><td style="padding:0 36px 28px">
        <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:#1A2744;margin-bottom:10px">
          Marketplace PO Purchases &mdash; """ + display_month + """
        </div>
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #DDE4EF;border-radius:8px;overflow:hidden">
          <thead><tr style="background:#F4F6FA">
            <th style="padding:10px 14px;text-align:left;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">Workload</th>
            <th style="padding:10px 14px;text-align:left;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">PO Number</th>
            <th style="padding:10px 14px;text-align:left;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">Purchaser</th>
            <th style="padding:10px 14px;text-align:left;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">Description</th>
            <th style="padding:10px 14px;text-align:right;font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px">Amount</th>
          </tr></thead>
          <tbody>
            """ + mkt_rows_html + """
            <tr style="background:#F8FAFE">
              <td colspan="4" style="padding:10px 14px;font-weight:700;font-size:12px">Total Marketplace (PO)</td>
              <td style="padding:10px 14px;text-align:right;font-weight:700;font-size:13px;color:#1A2744">""" + mkt_adj_total_str + """</td>
            </tr>
          </tbody>
        </table>
      </td></tr>
      <tr><td style="background:#F4F6FA;border-top:1px solid #DDE4EF;padding:18px 36px">
        <div style="font-size:11px;color:#888">
          Generated by <strong>AWS FinOps Tracker</strong> &nbsp;&middot;&nbsp; """ + workload_key + """ &nbsp;&middot;&nbsp; """ + display_month + """
        </div>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""
        )

        smtp_host = os.environ.get("SMTP_HOST", "smtp.cochlear.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "25"))
        from_addr = os.environ.get("SMTP_FROM", "noreply-awsfinops@cochlear.com")
        to_addr   = "global-aws-finops@cochlear.com"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = from_addr
        msg["To"]      = to_addr
        msg["Date"]    = formatdate(localtime=True)
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.sendmail(from_addr, [to_addr], msg.as_string())

        log.info("Project email sent for " + workload_key + "/" + month + " by " + session.get("username", ""))
        return jsonify({"ok": True, "to": to_addr})

    except Exception as e:
        log.error(f"Project email error {workload_key}/{month}: {e}")
        return jsonify({"error": str(e)}), 500


# ── API: receiving — summary (all months in FY) ────────────────────────────────

@app.route("/AWSFinOps/api/receiving/summary", methods=["GET"])
@login_required
def api_receiving_summary():
    fy = request.args.get("fy", "").strip()
    if not fy:
        return jsonify({"error": "fy parameter required"}), 400

    # FY = July→June; fy=2027 means 2026-07 to 2027-06
    year = int(fy)
    months_in_fy = [
        f"{year - 1}-{m:02d}-01" for m in range(7, 13)
    ] + [
        f"{year}-{m:02d}-01" for m in range(1, 7)
    ]

    with get_conn() as conn:
        fc_rows = conn.execute(
            "SELECT month, received_forecast, forecast_note FROM receiving_forecast WHERE month IN ({})".format(
                ",".join("?" * len(months_in_fy))
            ),
            months_in_fy,
        ).fetchall()
        fc_map = {r["month"]: dict(r) for r in fc_rows}

        inv_rows = conn.execute(
            "SELECT month, filename, account_number, validated, total_new_charges, uploaded_at "
            "FROM invoice_uploads WHERE month IN ({}) AND id IN ("
            "  SELECT MAX(id) FROM invoice_uploads GROUP BY month)".format(
                ",".join("?" * len(months_in_fy))
            ),
            months_in_fy,
        ).fetchall()
        inv_map = {r["month"]: dict(r) for r in inv_rows}

        adj_rows = conn.execute(
            "SELECT month, workload, adjustment, note, po_number, purchaser_name FROM marketplace_adjustments WHERE month IN ({})".format(
                ",".join("?" * len(months_in_fy))
            ),
            months_in_fy,
        ).fetchall()

    adj_by_month: dict = {}
    for r in adj_rows:
        adj_by_month.setdefault(r["month"], []).append(dict(r))

    result = []
    for m in months_in_fy:
        fc   = fc_map.get(m, {})
        inv  = inv_map.get(m)
        adjs = adj_by_month.get(m, [])

        received_forecast = float(fc.get("received_forecast") or 0)
        total_new_charges = float(inv["total_new_charges"] or 0) if inv else None
        mkt_adj_total     = abs(sum(float(a["adjustment"] or 0) for a in adjs if float(a["adjustment"] or 0) < 0))
        gap               = (total_new_charges - received_forecast - mkt_adj_total) if total_new_charges is not None else None

        result.append({
            "month":             m,
            "receiving_month":   _add_months(m, 2),
            "received_forecast": received_forecast or None,
            "forecast_note":     fc.get("forecast_note", ""),
            "mkt_adjustments":   adjs,
            "mkt_adj_total":     mkt_adj_total,
            "invoice":           inv,
            "total_new_charges": total_new_charges,
            "gap":               gap,
        })

    return jsonify({"months": result})


def _add_months(month_str: str, n: int) -> str:
    """Add n months to a YYYY-MM-DD string, return YYYY-MM-DD."""
    from datetime import date
    import calendar
    parts = month_str.split("-")
    y, m = int(parts[0]), int(parts[1])
    m += n
    while m > 12:
        m -= 12
        y += 1
    last = calendar.monthrange(y, m)[1]
    return f"{y}-{m:02d}-{min(int(parts[2]), last):02d}"


# ── API: status ────────────────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/status", methods=["GET"])
@login_required
def api_status():
    return jsonify({
        "ok":   True,
        "user": session.get("display_name", session.get("username", "unknown")),
    })


# ── ERROR HANDLERS ────────────────────────────────────────────────────────────

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": f"File too large. Maximum is {MAX_MB} MB."}), 413


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(f"Starting AWS FinOps Tracker on http://{HOST}:{PORT}/AWSFinOps")
    serve(app, host=HOST, port=PORT)
