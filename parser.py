"""
Bank Statement Parser Module.
Supports Excel (.xlsx, .xls), CSV, and PDF statements from Indian banks
(HDFC, ICICI, SBI, Axis, Kotak, etc.) with automatic header and column detection.
"""

import io
import re
import math
from typing import List, Dict, Any, Optional
import pandas as pd


def clean_number(val: Any) -> float:
    """Safely converts string/numeric values like '15,000.00' or '(500.00)' to float."""
    if val is None or pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        number = float(val)
        if not math.isfinite(number):
            raise ValueError("Statement contains a non-finite amount.")
        return number
    
    s = str(val).strip()
    # Check if empty or hyphen
    if not s or s in ["-", "--", "NA", "N/A", "Nil", "nil"]:
        return 0.0
        
    is_negative = False
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1]
    elif s.endswith("Cr") or s.endswith("CR"):
        s = s[:-2].strip()
    elif s.endswith("Dr") or s.endswith("DR"):
        is_negative = True
        s = s[:-2].strip()

    # Remove currency symbols and commas
    s = re.sub(r"[₹$,\s]", "", s)
    try:
        num = float(s)
        if not math.isfinite(num):
            raise ValueError("Statement contains a non-finite amount.")
        return -num if is_negative else num
    except ValueError as exc:
        raise ValueError(f"Could not read a statement amount: {val}") from exc


def find_table_header_row(df: pd.DataFrame) -> int:
    """
    Finds the row index that contains table headers like Date, Narration, Debit, Credit.
    Handles bank statements where the first 5-15 rows contain account/branch info.
    """
    header_keywords = ["date", "narration", "particular", "description", "debit", "withdrawal", "credit", "deposit", "balance"]
    
    for i in range(min(30, len(df))):
        row_str = " ".join([str(val).lower() for val in df.iloc[i].dropna()])
        matches = sum(1 for kw in header_keywords if kw in row_str)
        if matches >= 3:
            return i
            
    return 0


def identify_columns(df: pd.DataFrame) -> Dict[str, str]:
    """Identifies and maps standard column roles from dataframe headers."""
    col_map = {}
    cols = [str(c).strip() for c in df.columns]

    for c in cols:
        cl = c.lower()
        if "date" in cl and "val" not in cl and "date" not in col_map:
            col_map["date"] = c
        elif any(k in cl for k in ["narration", "particular", "description", "details", "remarks"]) and "narration" not in col_map:
            col_map["narration"] = c
        elif any(k in cl for k in ["withdrawal", "debit", "dr", "dr."]) and "debit" not in col_map:
            col_map["debit"] = c
        elif any(k in cl for k in ["deposit", "credit", "cr", "cr."]) and "credit" not in col_map:
            col_map["credit"] = c
        elif any(k in cl for k in ["chq", "ref", "instrument", "cheque", "utr"]) and "ref_no" not in col_map:
            col_map["ref_no"] = c
        elif any(k in cl for k in ["balance", "bal"]) and "balance" not in col_map:
            col_map["balance"] = c

    # Fallback if withdrawal/deposit are combined into Amount and Type columns
    if "debit" not in col_map and "credit" not in col_map:
        for c in cols:
            cl = c.lower()
            if any(k in cl for k in ["amount", "txn amt", "net amount"]):
                col_map["amount"] = c
            if any(k in cl for k in ["type", "cr/dr", "d/c"]):
                col_map["type"] = c

    return col_map


def parse_excel_or_csv(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    """Parses Excel or CSV statement files into standardized transaction objects."""
    if filename.endswith(".csv"):
        try:
            df_raw = pd.read_csv(io.BytesIO(file_bytes), header=None, dtype=str)
        except Exception:
            df_raw = pd.read_csv(io.BytesIO(file_bytes), header=None, encoding="latin1", dtype=str)
    else:
        df_raw = pd.read_excel(io.BytesIO(file_bytes), header=None, dtype=str)

    header_idx = find_table_header_row(df_raw)
    headers = [str(c).strip() for c in df_raw.iloc[header_idx]]
    df = df_raw.iloc[header_idx + 1:].copy()
    df.columns = headers

    col_map = identify_columns(df)
    if "date" not in col_map or "narration" not in col_map:
        raise ValueError(f"Could not locate Date and Narration columns. Found columns: {headers}")

    transactions = []
    for _, row in df.iterrows():
        date_val = str(row[col_map["date"]]).strip()
        narration_val = str(row[col_map["narration"]]).strip()
        
        if not date_val or date_val.lower() in ["nan", "none", ""] or not narration_val or narration_val.lower() in ["nan", "none", ""]:
            continue

        debit_amt = clean_number(row[col_map["debit"]]) if "debit" in col_map else 0.0
        credit_amt = clean_number(row[col_map["credit"]]) if "credit" in col_map else 0.0
        if debit_amt > 0 and credit_amt > 0:
            raise ValueError(f"Both debit and credit contain amounts on {date_val}. Check this row.")
        if debit_amt < 0 or credit_amt < 0:
            raise ValueError(f"Negative debit or credit on {date_val}. Check the statement format.")
        
        if "amount" in col_map and "type" in col_map:
            amt = clean_number(row[col_map["amount"]])
            t_type = str(row[col_map["type"]]).strip().lower()
            if "dr" in t_type or "debit" in t_type:
                debit_amt = amt
            elif t_type in {"cr", "credit", "receipt"}:
                credit_amt = amt
            else:
                raise ValueError(f"Unknown transaction direction on {date_val}: {t_type}")

        ref_no = str(row[col_map["ref_no"]]).strip() if "ref_no" in col_map and not pd.isna(row[col_map["ref_no"]]) else ""
        bal_val = clean_number(row[col_map["balance"]]) if "balance" in col_map else None

        if debit_amt > 0:
            transactions.append({
                "date": date_val,
                "narration": narration_val,
                "voucher_type": "Payment",
                "amount": debit_amt,
                "balance": bal_val,
                "instrument_no": ref_no,
            })
        elif credit_amt > 0:
            transactions.append({
                "date": date_val,
                "narration": narration_val,
                "voucher_type": "Receipt",
                "amount": credit_amt,
                "balance": bal_val,
                "instrument_no": ref_no,
            })

    return transactions


def parse_bank_pdf(file_bytes: bytes, password: str = "") -> List[Dict[str, Any]]:
    """
    Parses PDF bank statements using pdfplumber.
    Supports both bordered grid tables and unbordered stream formats (e.g. HDFC, ICICI, SBI).
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber is required to parse PDF statements. Please install it.")

    transactions = []

    with pdfplumber.open(io.BytesIO(file_bytes), password=password) as pdf:
        # First strategy: check if table extract returns discrete, clean rows
        has_discrete_tables = False
        requires_text_fallback = False
        all_table_rows = []

        for page in pdf.pages:
            tables = page.extract_tables()
            if not tables and re.search(r"^\d{2}[/-]\d{2}[/-]\d{2,4}\s", page.extract_text() or "", re.MULTILINE):
                requires_text_fallback = True
            for table in tables:
                if not table or len(table) < 2:
                    continue
                # Check if rows are discrete or joined by newlines
                first_data_row = table[1]
                has_multiline = any("\n" in str(cell or "") for cell in first_data_row[:3])
                requires_text_fallback = requires_text_fallback or has_multiline
                if not has_multiline:
                    has_discrete_tables = True
                    for r in table:
                        all_table_rows.append(r)

        if has_discrete_tables and not requires_text_fallback and len(all_table_rows) >= 2:
            try:
                df_raw = pd.DataFrame(all_table_rows)
                header_idx = find_table_header_row(df_raw)
                headers = [str(c).strip() for c in df_raw.iloc[header_idx]]
                df = df_raw.iloc[header_idx + 1:].copy()
                df.columns = headers
                col_map = identify_columns(df)

                if "date" in col_map and "narration" in col_map:
                    for _, row in df.iterrows():
                        d_val = str(row[col_map["date"]]).strip()
                        n_val = str(row[col_map["narration"]]).strip()
                        if not d_val or d_val.lower() == "nan" or not n_val or n_val.lower() == "nan":
                            continue
                        deb = clean_number(row[col_map["debit"]]) if "debit" in col_map else 0.0
                        crd = clean_number(row[col_map["credit"]]) if "credit" in col_map else 0.0
                        ref = str(row[col_map["ref_no"]]).strip() if "ref_no" in col_map and not pd.isna(row[col_map["ref_no"]]) else ""
                        balance = clean_number(row[col_map["balance"]]) if "balance" in col_map else None

                        if deb > 0:
                            transactions.append({
                                "date": d_val,
                                "narration": n_val,
                                "voucher_type": "Payment",
                                "amount": deb,
                                "balance": balance,
                                "instrument_no": ref,
                            })
                        elif crd > 0:
                            transactions.append({
                                "date": d_val,
                                "narration": n_val,
                                "voucher_type": "Receipt",
                                "amount": crd,
                                "balance": balance,
                                "instrument_no": ref,
                            })
                    if transactions:
                        return transactions
            except Exception:
                transactions = []
                pass  # Fall through to line-based parser

        # Second strategy: Robust text-line regex parsing (Standard for HDFC, ICICI, etc.)
        date_pattern = re.compile(r"^(\d{2}[/-]\d{2}[/-]\d{2,4})\s+(.*)")
        # Matches: ValueDate Amount ClosingBalance at end of line
        amt_pattern = re.compile(r"(\d{2}[/-]\d{2}[/-]\d{2,4})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})$")

        # Header/footer keywords to ignore across multi-page statements
        header_footer_keywords = [
            "pageno.:", "accountbranch", "address :", "groundfloor", "off15throad", "city :",
            "m/s. hairline", "state :", "202saffron", "oppositesatguru", "currency :",
            "anushreereddy", "email :", "custid :", "maharashtraindia", "accountno :",
            "a/copendate", "jointholders", "rtgs/neftifsc", "branchcode", "nomination:",
            "statementof account", "statement of account", "date narration", "hdfcbanklimited",
            "*closingbalance", "contentsofthisstatement", "stateaccountbranchgstn",
            "hdfcbankgstin", "registeredofficeaddress", "thisisacomputergenerated"
        ]

        full_text = "\n".join([p.extract_text() or "" for p in pdf.pages])
        m_open = re.search(r"Opening\s*Balance[^\d]*([\d,]+\.\d{2})", full_text, re.IGNORECASE)
        prev_closing = float(m_open.group(1).replace(",", "")) if m_open else None

        in_stmt = False
        curr = None

        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            lines = text.split("\n")

            for line in lines:
                l_str = line.strip()
                if not l_str:
                    continue
                if "Date" in l_str and "Narration" in l_str and any(k in l_str for k in ["Withdrawal", "Closing", "Deposit", "Debit", "Credit", "Balance"]):
                    in_stmt = True
                    continue
                if any(k in l_str for k in ["STATEMENTSUMMARY", "OpeningBalance DrCount", "Statement Summary", "GeneratedOn:"]):
                    in_stmt = False
                    continue
                if any(hk in l_str.lower() for hk in header_footer_keywords):
                    continue
                if not in_stmt:
                    continue

                m_date = date_pattern.match(l_str)
                if m_date:
                    if curr and curr.get("amount", 0) > 0:
                        transactions.append(curr)
                    
                    dt = m_date.group(1)
                    rest = m_date.group(2)
                    m_amt = amt_pattern.search(rest)
                    
                    if m_amt:
                        amt = float(m_amt.group(2).replace(",", ""))
                        closing = float(m_amt.group(3).replace(",", ""))
                        mid = rest[:m_amt.start()].strip()
                        
                        tokens = mid.split()
                        if len(tokens) > 1 and re.match(r"^[0-9A-Z]{8,}$", tokens[-1]):
                            ref = tokens[-1]
                            narr = " ".join(tokens[:-1])
                        else:
                            ref = ""
                            narr = mid

                        # Infer voucher type from closing balance change
                        uncertain_direction = prev_closing is None
                        if prev_closing is not None:
                            vtype = "Receipt" if closing > prev_closing else "Payment"
                        else:
                            vtype = "Payment"

                        prev_closing = closing
                        curr = {
                            "date": dt,
                            "narration": narr,
                            "voucher_type": vtype,
                            "amount": amt,
                            "balance": closing,
                            "needs_direction_review": uncertain_direction,
                            "instrument_no": ref,
                        }
                    else:
                        raise ValueError(f"Could not read the amount on {dt}. Use the bank's Excel or CSV export.")
                else:
                    if curr:
                        # Append continuation lines to narration
                        curr["narration"] += " " + l_str

        if curr and curr.get("amount", 0) > 0:
            transactions.append(curr)

        return transactions
