"""
Parse Telstra/AWS invoice PDFs.

Expected format (Telstra Managed Services invoice for AWS):
  - Account number: 228530556149
  - Invoice Detail page has line items:
      AWS CHARGES - CREDIT
      AWS CHARGES - EDP DISC
      AWS CHARGES - ENT SUPPORT
      AWS CHARGES - NO EDP DISC   ← marketplace (no EDP discount applied)
  - "Total New Charges excl GST" is the authoritative total

PDF text extraction quirks:
  - pdfplumber may put description and amount on the same line separated by spaces,
    or on adjacent lines depending on the PDF column layout.
  - Dash may be ASCII hyphen or en-dash.
  - Amount may or may not have leading $.
"""
from __future__ import annotations
import re

EXPECTED_ACCOUNT = "228530556149"

# All known Telstra/AWS charge type suffixes (case-insensitive)
_CHARGE_TYPES = [
    "NO EDP DISC",
    "EDP DISC",
    "ENT SUPPORT",
    "CREDIT",
    "MARKETPLACE",
    "SUPPORT",
]


def _extract_text(pdf_path: str) -> str:
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber is not installed. Run: pip install pdfplumber")

    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # Also try extract_words for table-like layouts
            t = page.extract_text(x_tolerance=3, y_tolerance=3)
            if t:
                pages.append(t)
    return "\n".join(pages)


def _extract_text_with_words(pdf_path: str) -> list[dict]:
    """Extract words with bounding boxes for position-aware parsing."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber not installed")
    words = []
    with pdfplumber.open(pdf_path) as pdf:
        for pnum, page in enumerate(pdf.pages):
            for w in (page.extract_words(x_tolerance=3, y_tolerance=3) or []):
                words.append({**w, "page": pnum})
    return words


def _parse_amount(s: str) -> float:
    s = s.strip().lstrip("$").replace(",", "").replace(" ", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _is_amount(s: str) -> bool:
    """Return True if s looks like a dollar amount."""
    s = s.strip().lstrip("-").lstrip("$").replace(",", "")
    try:
        float(s)
        return "." in s and len(s) > 2
    except ValueError:
        return False


def parse_invoice(pdf_path: str) -> dict:
    """
    Parse an AWS/Telstra invoice PDF.

    Returns dict with:
        account_number, validated, total_new_charges,
        marketplace_lines, all_lines, raw_text
    """
    text = _extract_text(pdf_path)
    lines = text.splitlines()

    # ── Account number ─────────────────────────────────────────────────────────
    # Remove all spaces and search for the 12-digit account number
    text_nospace = re.sub(r"\s+", "", text)
    account_match = re.search(r"228530556149", text_nospace)
    if not account_match:
        # Try in original text with possible spaces
        account_match = re.search(r"2\s*2\s*8\s*5\s*3\s*0\s*5\s*5\s*6\s*1\s*4\s*9", text)
    account_number = "228530556149" if account_match else ""

    # Also try to extract whatever account number is present (for display)
    if not account_number:
        acct_m = re.search(r"\b(\d{10,14})\b", text)
        account_number = acct_m.group(1) if acct_m else ""

    validated = account_number == EXPECTED_ACCOUNT

    # ── Total New Charges excl GST ─────────────────────────────────────────────
    total_new_charges = 0.0
    tnc_patterns = [
        r"Total\s+New\s+Charges\s+excl(?:uding)?\.?\s+GST[^\d\-]*(-?[\d,]+\.\d{2})",
        r"Total\s+New\s+Charges[^\d\-]*(-?[\d,]+\.\d{2})",
        r"TOTAL\s+NEW\s+CHARGES[^\d\-]*(-?[\d,]+\.\d{2})",
    ]
    for pat in tnc_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            total_new_charges = _parse_amount(m.group(1))
            break

    # ── Line items — multi-strategy ────────────────────────────────────────────
    all_lines: list[dict] = []

    # Strategy 1: description and amount on the same line
    # Handles: "AWS CHARGES - NO EDP DISC   $12,345.67" or "AWS CHARGES-ENT SUPPORT -1,234.56"
    same_line_pat = re.compile(
        r"(AWS\s+CHARGES\s*[-–—]\s*(?:NO\s+EDP\s+DISC|EDP\s+DISC|ENT\s+SUPPORT|CREDIT|MARKETPLACE|SUPPORT)[^\n\d\-]*?)"
        r"\s+(-?\$?[\d,]+\.\d{2})",
        re.IGNORECASE,
    )
    for m in same_line_pat.finditer(text):
        desc = re.sub(r"\s+", " ", m.group(1)).strip().rstrip("-– ")
        amount = _parse_amount(m.group(2))
        line_type = "marketplace" if re.search(r"NO\s+EDP", desc, re.IGNORECASE) else "aws_charge"
        all_lines.append({"line_type": line_type, "description": desc, "amount": amount, "po_number": ""})

    # Strategy 2: description on one line, amount on the next line
    if not all_lines:
        charge_line_pat = re.compile(
            r"AWS\s+CHARGES\s*[-–—]\s*(NO\s+EDP\s+DISC|EDP\s+DISC|ENT\s+SUPPORT|CREDIT|MARKETPLACE|SUPPORT)",
            re.IGNORECASE,
        )
        for i, line in enumerate(lines):
            m = charge_line_pat.search(line)
            if m:
                desc = f"AWS CHARGES - {m.group(1).strip().upper()}"
                # Look for amount in this line or the next 3 lines
                amount = 0.0
                for look in range(4):
                    idx = i + look
                    if idx >= len(lines):
                        break
                    amt_m = re.search(r"-?\$?([\d,]+\.\d{2})", lines[idx])
                    if amt_m:
                        amount = _parse_amount(amt_m.group(1))
                        # Preserve sign if preceded by -
                        if re.search(r"-\s*\$?" + re.escape(amt_m.group(1)), lines[idx]):
                            amount = -amount
                        break
                line_type = "marketplace" if "NO EDP" in desc else "aws_charge"
                all_lines.append({"line_type": line_type, "description": desc, "amount": amount, "po_number": ""})

    # Strategy 3: word-position-based extraction (tabular layout)
    if not all_lines:
        try:
            words = _extract_text_with_words(pdf_path)
            # Group words by page+y (same row = within 5pt vertically)
            rows: dict[tuple, list] = {}
            for w in words:
                key = (w["page"], round(w["top"] / 5) * 5)
                rows.setdefault(key, []).append(w)

            charge_re = re.compile(
                r"AWS.{0,3}CHARGES.{0,5}(NO\s*EDP\s*DISC|EDP\s*DISC|ENT\s*SUPPORT|CREDIT)",
                re.IGNORECASE,
            )
            for key in sorted(rows):
                row_text = " ".join(w["text"] for w in sorted(rows[key], key=lambda x: x["x0"]))
                m = charge_re.search(row_text)
                if m:
                    # Find amounts in this row
                    amounts = re.findall(r"-?\$?([\d,]+\.\d{2})", row_text)
                    amount = _parse_amount(amounts[-1]) if amounts else 0.0
                    ctype  = m.group(1).strip().upper()
                    desc   = f"AWS CHARGES - {ctype}"
                    line_type = "marketplace" if "NO EDP" in ctype else "aws_charge"
                    all_lines.append({"line_type": line_type, "description": desc, "amount": amount, "po_number": ""})
        except Exception:
            pass  # word extraction may fail; fall back to text results

    # Deduplicate by (description, amount)
    seen: set = set()
    deduped = []
    for l in all_lines:
        key = (l["description"].upper(), l["amount"])
        if key not in seen:
            seen.add(key)
            deduped.append(l)
    all_lines = deduped

    marketplace_lines = [l for l in all_lines if l["line_type"] == "marketplace"]

    # ── PO numbers ────────────────────────────────────────────────────────────
    po_pattern = re.compile(
        r"(?:P\.?O\.?\s*(?:Number|No\.?|#)?|Purchase\s+Order\s*(?:Number|No\.?|#)?)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-]{3,20})",
        re.IGNORECASE,
    )
    po_matches = po_pattern.findall(text)
    for i, po in enumerate(po_matches):
        if i < len(marketplace_lines):
            marketplace_lines[i]["po_number"] = po

    return {
        "account_number":    account_number,
        "validated":         validated,
        "total_new_charges": total_new_charges,
        "marketplace_lines": marketplace_lines,
        "all_lines":         all_lines,
        "raw_text":          text,  # full text for debug
    }
