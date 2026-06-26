# Integration steps — copy this folder next to app.py

## 1. Folder layout after copying

```
C:\Apps\PlatformTCO\
    app.py
    excel_log.py
    extractor.py
    index.html
    aws_finops\
        __init__.py
        aws_db.py
        aws_ingestor.py
        aws_run_cost.py
        aws_routes.py
        aws_index.html
        aws_finops.db          ← created automatically on first run
```

## 2. Install extra dependency

The ingestor already uses openpyxl (same as the existing app).
No new packages needed beyond what is already installed.

## 3. Two lines to add to app.py

Add these two lines **after** the `app = Flask(...)` line in app.py:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from aws_finops.aws_routes import aws_bp
app.register_blueprint(aws_bp)
```

Also add the AWS FinOps route to the ALLOWED_ORIGINS in app.py if needed.

## 4. Add AD_ENABLED to app config (already there — just confirm)

The blueprint reads `current_app.config.get("AD_ENABLED", True)`.
Make sure app.py sets: `app.config["AD_ENABLED"] = AD_ENABLED`
(Add this line right after `app.secret_key = SECRET_KEY`.)

## 5. Access the app

    http://<server>:4000/PlatformTCO/aws/

## 6. First-time setup

1. Go to **Workloads** tab → click **Discover CUR tags** after uploading a CUR file.
2. Click each tag you want tracked individually to add it as a named workload.
3. Anything not in the list automatically rolls into **Other**.
4. Each month: enter the Telstra invoice amount in the **Run Cost** tab
   (the input panel at the top when a month is selected).

## 7. CUR file format expected

Same as the AWSCUR tab in the Excel tracker:
- Column A: account_id  (no leading \t)
- Column B: account_name
- Column C: workloads_tag
- Column D: outcomegroup_tag
- Column E: category  ('monthly_expense' or 'marketplace')
- Column F onwards: one column per month (Excel date values or YYYY-MM-DD strings)

Summary rows (account_id blank) are skipped automatically.
Re-uploading the same file or period is safe — data is upserted.
