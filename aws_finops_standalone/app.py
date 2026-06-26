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
from aws_run_cost import get_available_months, get_workloads, get_monthly_input, compute_run_cost

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
    return jsonify({"months": get_available_months()})


# ── API: run cost ─────────────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/run-cost", methods=["GET"])
@login_required
def api_run_cost():
    month = request.args.get("month", "").strip()
    if not month:
        months = get_available_months()
        month  = months[-1] if months else None
    if not month:
        return jsonify({"error": "No CUR data available."}), 404
    return jsonify(compute_run_cost(month))


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
        telstra  = float(data.get("telstra_invoice") or 0) or None
        forecast = float(data.get("forecast") or 0) or None
    except (TypeError, ValueError) as e:
        return jsonify({"error": str(e)}), 400

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO monthly_inputs (month, telstra_invoice, forecast) VALUES (?,?,?)
            ON CONFLICT(month) DO UPDATE SET
                telstra_invoice = excluded.telstra_invoice,
                forecast        = excluded.forecast
        """, (month, telstra, forecast))

    log.info(f"Monthly inputs saved: {month} invoice={telstra} forecast={forecast} "
             f"by {session.get('username','')}")
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
                "INSERT INTO workloads (name,domain,department,budget_manager,description,budget_monthly) "
                "VALUES (?,?,?,?,?,?)",
                (
                    name,
                    (data.get("domain") or "").strip() or None,
                    (data.get("department") or "").strip() or None,
                    (data.get("budget_manager") or "").strip() or None,
                    (data.get("description") or "").strip() or None,
                    float(data.get("budget_monthly") or 0) or None,
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
            "UPDATE workloads SET domain=?,department=?,budget_manager=?,description=?,budget_monthly=? "
            "WHERE name=?",
            (
                (data.get("domain") or "").strip() or None,
                (data.get("department") or "").strip() or None,
                (data.get("budget_manager") or "").strip() or None,
                (data.get("description") or "").strip() or None,
                float(data.get("budget_monthly") or 0) or None,
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


# ── API: CUR tag discovery ─────────────────────────────────────────────────────

@app.route("/AWSFinOps/api/cur-tags", methods=["GET"])
@login_required
def api_cur_tags():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT workloads_tag FROM cur_data "
            "WHERE workloads_tag IS NOT NULL ORDER BY workloads_tag"
        ).fetchall()
    return jsonify({"tags": [r["workloads_tag"] for r in rows]})


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
