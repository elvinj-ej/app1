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
    note = (data.get("note") or "").strip()

    with get_conn() as conn:
        if adjustment == 0 and not note:
            conn.execute(
                "DELETE FROM marketplace_adjustments WHERE workload=? AND month=?",
                (workload, month),
            )
        else:
            conn.execute(
                "INSERT INTO marketplace_adjustments (workload, month, adjustment, note) VALUES (?,?,?,?) "
                "ON CONFLICT(workload, month) DO UPDATE SET "
                "adjustment=excluded.adjustment, note=excluded.note, updated_at=datetime('now')",
                (workload, month, adjustment, note or None),
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
    return jsonify({"invoice": inv})


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
                "SELECT workload, adjustment, note FROM marketplace_adjustments WHERE month=?",
                (month,),
            ).fetchall()
        adj_map = {r["workload"]: {"adj": float(r["adjustment"]), "note": r["note"] or ""} for r in adj_rows}

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

        log.info(f"Invoice uploaded for {month}: {f.filename} by {session.get('username','')}")
        return jsonify({
            "ok":              True,
            "account_number":  parsed["account_number"],
            "validated":       parsed["validated"],
            "total_new_charges": parsed["total_new_charges"],
            "marketplace_lines": mkt_lines,
            "all_lines":       parsed["all_lines"],
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
                "SELECT workload, adjustment, note FROM marketplace_adjustments WHERE month=?", (month,)
            ).fetchall()

        if not inv_row:
            return jsonify({"error": "No invoice uploaded for this month."}), 400

        inv = dict(inv_row)
        fc  = dict(fc_row) if fc_row else {}
        received_forecast  = float(fc.get("received_forecast") or 0)
        total_new_charges  = float(inv.get("total_new_charges") or 0)
        mkt_adj_total      = abs(sum(float(r["adjustment"] or 0) for r in adj_rows if float(r["adjustment"] or 0) < 0))
        gap                = total_new_charges - received_forecast - mkt_adj_total

        with get_conn() as conn:
            items = conn.execute(
                "SELECT line_type, description, amount, po_number, workload_match "
                "FROM invoice_line_items WHERE invoice_id=? AND line_type='marketplace'",
                (inv["id"],),
            ).fetchall()

        def fmt(v):
            return f"${v:,.2f}"

        lines_html = "".join(
            f"<tr><td>{i['description']}</td><td>{i['po_number'] or '—'}</td>"
            f"<td>{i['workload_match'] or '—'}</td><td style='text-align:right'>{fmt(i['amount'])}</td></tr>"
            for i in items
        )

        html_body = f"""
<html><body style="font-family:Arial,sans-serif;font-size:14px">
<p>Hi team,</p>
<p>Please find below the AWS Marketplace receiving summary for <strong>{month[:7]}</strong>.</p>

<h3>Invoice Summary</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
  <tr><td><strong>Account</strong></td><td>{inv['account_number']} {'✅ Validated' if inv['validated'] else '⚠️ Not matched'}</td></tr>
  <tr><td><strong>Invoice Total New Charges (excl GST)</strong></td><td>{fmt(total_new_charges)}</td></tr>
  <tr><td><strong>Received Forecast</strong></td><td>{fmt(received_forecast)}</td></tr>
  <tr><td><strong>Marketplace Purchases (adjusted)</strong></td><td>{fmt(mkt_adj_total)}</td></tr>
  <tr><td><strong>Gap</strong></td><td style="color:{'red' if gap > 0 else 'green'}">{fmt(gap)}</td></tr>
</table>

<h3>Marketplace Line Items</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
  <tr style="background:#f0f0f0">
    <th>Description</th><th>PO Number</th><th>Workload</th><th>Amount</th>
  </tr>
  {lines_html if lines_html else '<tr><td colspan="4">No marketplace items found</td></tr>'}
</table>

<p>Please update the Finance tool with the gap amount of <strong>{fmt(gap)}</strong>.</p>
<p>Invoice PDF is attached.</p>
<br><p>AWS FinOps Team</p>
</body></html>
"""

        smtp_host = os.environ.get("SMTP_HOST", "smtp.cochlear.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "25"))
        from_addr = os.environ.get("SMTP_FROM", "noreply-awsfinops@cochlear.com")
        to_addr   = "global-aws-finops@cochlear.com"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"AWS Marketplace Receiving — {month[:7]}"
        msg["From"]    = from_addr
        msg["To"]      = to_addr
        msg["Date"]    = formatdate(localtime=True)
        msg.attach(MIMEText(html_body, "html"))

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
            "SELECT month, workload, adjustment, note FROM marketplace_adjustments WHERE month IN ({})".format(
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
