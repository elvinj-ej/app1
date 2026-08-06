"""
Parse Telstra/AWS invoice PDFs.

Expected format:
  - Account validation: looks for account number 228530556149
  - Invoice Detail page has line items per charge type
  - "NO EDP DISC" lines = marketplace purchases (not covered by EDP discount)
  - Extracts "Total New Charges excl GST" as the authoritative total
"""
from __future__ import annotations
import re

EXPECTED_ACCOUNT = "228530556149"


def _extract_text(pdf_path: str) -> str:
    """Extract all text from PDF using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber is not installed. Run: pip install pdfplumber")

    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text(x_tolerance=3, y_tolerance=3)
            if t:
                pages.append(t)
    return "\n".join(pages)


def _parse_amount(s: str) -> float:
    """Parse a dollar amount string like '$1,234.56' or '1,234.56' to float."""
    s = s.strip().lstrip("$").replace(",", "").replace(" ", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_invoice(pdf_path: str) -> dict:
    """
    Parse an AWS/Telstra invoice PDF.

    Returns:
        {
            "account_number": str,
            "validated": bool,
            "total_new_charges": float,
            "marketplace_lines": [
                {"description": str, "amount": float, "po_number": str}
            ],
            "all_lines": [
                {"line_type": str, "description": str, "amount": float}
            ],
            "raw_text": str  (first 2000 chars for debug)
        }
    """
    text = _extract_text(pdf_path)

    # ── Account number ─────────────────────────────────────────────────────────
    account_match = re.search(r"\b(2285\s*3055\s*6149)\b", text.replace(" ", ""))
    if not account_match:
        # Try with spaces
        account_match = re.search(r"228[\s\-]?530[\s\-]?556[\s\-]?149", text)
    account_number = "".join(filter(str.isdigit, account_match.group(0))) if account_match else ""
    validated = account_number == EXPECTED_ACCOUNT

    # ── Total New Charges excl GST ─────────────────────────────────────────────
    total_new_charges = 0.0
    tnc_match = re.search(
        r"Total\s+New\s+Charges\s+(?:excl(?:uding)?\.?\s+GST\s+)?\$?\s*([\d,]+\.\d{2})",
        text, re.IGNORECASE
    )
    if tnc_match:
        total_new_charges = _parse_amount(tnc_match.group(1))

    # ── Line items ─────────────────────────────────────────────────────────────
    # Pattern: lines containing charge types and dollar amounts
    # Look for "AWS CHARGES - <TYPE>" followed by amount
    all_lines = []
    marketplace_lines = []

    # Match patterns like:
    #   AWS CHARGES - NO EDP DISC    $12,345.67
    #   AWS CHARGES- NO EDP DISC     $12,345.67
    #   AWS CHARGES - CREDIT         -$1,234.56
    line_pattern = re.compile(
        r"(AWS\s+CHARGES\s*[-–]\s*[A-Z0-9 /]+?)\s+(-?\$?[\d,]+\.\d{2})",
        re.IGNORECASE,
    )
    for m in line_pattern.finditer(text):
        desc = m.group(1).strip()
        amount = _parse_amount(m.group(2))
        line_type = "marketplace" if re.search(r"NO\s+EDP", desc, re.IGNORECASE) else "aws_charge"
        entry = {"line_type": line_type, "description": desc, "amount": amount, "po_number": ""}
        all_lines.append(entry)
        if line_type == "marketplace":
            marketplace_lines.append(entry)

    # ── PO number extraction from surrounding context ──────────────────────────
    # PO numbers often appear near "Purchase Order" or "PO#" in invoice detail
    po_pattern = re.compile(r"(?:P\.?O\.?#?|Purchase\s+Order)\s*[:\-]?\s*([A-Z0-9\-]{4,20})", re.IGNORECASE)
    po_matches = po_pattern.findall(text)
    # Assign POs to marketplace lines in order if multiple found
    for i, po in enumerate(po_matches):
        if i < len(marketplace_lines):
            marketplace_lines[i]["po_number"] = po

    return {
        "account_number":   account_number,
        "validated":        validated,
        "total_new_charges": total_new_charges,
        "marketplace_lines": marketplace_lines,
        "all_lines":         all_lines,
        "raw_text":          text[:3000],
    }
