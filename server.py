"""
FastAPI Local Backend for Tally Smart Connector.
Provides high-performance REST APIs for PDF/Excel parsing,
fuzzy ledger matching, persistent rule caching, and Tally XML generation.
"""

import os
from datetime import date
from io import BytesIO
from typing import List, Optional
from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pandas as pd

from parser import parse_excel_or_csv, parse_bank_pdf
from matcher import load_persistent_mappings
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException
from tally_xml import generate_tally_xml_envelope, voucher_date
from learning import list_rules

SUSPENSE_LEDGER = "Suspense"

app = FastAPI(
    title="Tally Smart Connector API",
    description="Local bank statement converter for Tally voucher XML",
    version="2.0.0",
)

router = APIRouter()


@app.middleware("http")
async def prevent_stale_page(request, call_next):
    response = await call_next(request)
    # Always load the current HTML so it references the latest built JS bundle.
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-store"
    return response

# Enable CORS for local development (Vite dev server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Company Active Ledgers (Configured from Chart of Accounts)
COMPANY_BANKS = {
    "HAIRLINE SOLUTIONS": ["HDFC BANK"],
    "AESTHETIQUE SOLUTION": ["HDFC BANK"],
    "HAIR ALIVE": ["HDFC BANK"],
    "HAIR LOSS SOLUTION": ["HDFC BANK"],
    "TRICHO HAIR": ["HDFC BANK"],
    "AHL": [
        "HDFC BANK",
        "Central Bank (Saving A/c)",
        "Bank of Baroda (Saving A/c)",
    ],
    "HOUSE OF AESTHETICS": [
        "HDFC Bank (96996)",
        "HDFC Bank (5801) AHL 2",
        "HDFC BANK (2236-SAVING)",
    ],
}

DEFAULT_LEDGERS = [
    "Administrative and Other Expenses",
    "Banglore Exp",
    "BANGLORE PURCHASE",
    "CBDT TAX",
    "Consumable",
    "Conveyance Charges",
    "Conveyance Expenses",
    "DELHI PURCHSE",
    "Employee Benefit Expenses",
    "Financial  Expenses",
    "Fuel Charges",
    "Fuel Expenses",
    "Hair Transplant",
    "Internet Exp",
    "Laundry Expenses",
    "Legal Charges",
    "Maintenance Charges",
    "Manohar Kokne",
    "OT Charges",
    "Product Expenses",
    "Professional Service",
    "PROFESSIONAL FEES",
    "Project 2",
    "Sales Refund",
    "Salon Consumption Expn",
    "Salon Exp.",
    "Salon Expenses",
    "Salon Purchases",
    "Selling And Distribution",
    "SHABANESA",
    "Shoot Expenses",
    "Skin Product",
    "Software Exp",
    "Subscriptions Expenses",
    "Transplant",
    "Suspense",
]

ACTIVE_LEDGERS = list(DEFAULT_LEDGERS)


class VoucherItem(BaseModel):
    voucher_type: str
    date: str
    bank_ledger: str = ""
    party_ledger: str = SUSPENSE_LEDGER
    amount: float
    narration: str
    instrument_no: Optional[str] = ""
    corrected: bool = False


class GenerateXmlRequest(BaseModel):
    bank_ledger_name: str
    company_name: Optional[str] = None
    vouchers: List[VoucherItem]
    save_mappings: bool = True
    manual_mappings: Optional[dict] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None


@router.get("/companies")
def get_companies():
    """Returns the list of companies and their associated bank accounts."""
    return {"companies": COMPANY_BANKS}


@router.get("/ledgers")
def get_ledgers():
    """Returns the list of current active ledgers."""
    return {"ledgers": ACTIVE_LEDGERS, "count": len(ACTIVE_LEDGERS)}


@router.post("/upload-ledgers")
async def upload_ledgers(file: UploadFile = File(...)):
    """Upload Tally chart of accounts export to update active ledgers."""
    global ACTIVE_LEDGERS
    contents = await file.read()
    filename = file.filename.lower()

    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(BytesIO(contents))
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Only CSV or Excel files are supported.")

        found_col = None
        for col in df.columns:
            if any(k in str(col).lower() for k in ["name", "ledger", "particular"]):
                found_col = col
                break
        if not found_col:
            found_col = df.columns[0]

        custom_ledgers = df[found_col].dropna().astype(str).str.strip().tolist()
        if custom_ledgers:
            ACTIVE_LEDGERS = sorted(list(set(custom_ledgers + ["Suspense", "Bank Charges"])))
            return {"status": "success", "count": len(ACTIVE_LEDGERS), "ledgers": ACTIVE_LEDGERS}
        else:
            raise HTTPException(status_code=400, detail="No ledger names found in uploaded file.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse ledgers: {str(e)}")


@router.post("/parse-statement")
async def parse_statement(file: UploadFile = File(...), password: str = Form("")):
    """Parse statement rows and assign every counterpart to suspense."""
    contents = await file.read()
    filename = file.filename.lower()

    try:
        if filename.endswith(".pdf"):
            raw_txns = parse_bank_pdf(contents, password=password)
        elif filename.endswith((".xlsx", ".xls", ".csv")):
            raw_txns = parse_excel_or_csv(contents, filename)
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported format. Please upload PDF, XLSX, XLS, or CSV.",
            )
    except (PDFPasswordIncorrect, PdfminerException) as exc:
        if not isinstance(exc, PDFPasswordIncorrect) and not (
            exc.args and isinstance(exc.args[0], PDFPasswordIncorrect)
        ):
            raise HTTPException(status_code=422, detail="Unable to read the statement PDF.") from exc
        raise HTTPException(status_code=422, detail={
            "code": "pdf_password_required",
            "message": "Incorrect PDF password. Try again." if password else "Enter the statement PDF password.",
        }) from exc
    except HTTPException:
        raise
    except (ValueError, OSError, ImportError) as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse statement: {e}") from e

    if not raw_txns:
        return {"status": "empty", "count": 0, "transactions": [], "opening_balance": None, "closing_balance": None}

    opening_balance = None
    closing_balance = None

    if raw_txns:
        first_txn = raw_txns[0]
        last_txn = raw_txns[-1]
        if "balance" in last_txn and last_txn["balance"] is not None:
            closing_balance = round(float(last_txn["balance"]), 2)
        if "balance" in first_txn and first_txn["balance"] is not None:
            f_bal = float(first_txn["balance"])
            f_amt = float(first_txn["amount"])
            if first_txn["voucher_type"] == "Receipt":
                opening_balance = round(f_bal - f_amt, 2)
            else:
                opening_balance = round(f_bal + f_amt, 2)

    matched_records = []
    for i, t in enumerate(raw_txns):
        try:
            calendar_date = voucher_date(t["date"]).isoformat()
        except ValueError:
            calendar_date = None
        matched_records.append({
            "id": f"txn_{i+1}",
            "selected": True,
            "date": t["date"],
            "calendar_date": calendar_date,
            "voucher_type": t["voucher_type"],
            "amount": float(t["amount"]),
            "balance": float(t["balance"]) if t.get("balance") is not None else None,
            "assigned_ledger": SUSPENSE_LEDGER,
            "original_narration": t["narration"],
            "instrument_no": t.get("instrument_no", ""),
        })

    return {
        "status": "success",
        "count": len(matched_records),
        "transactions": matched_records,
        "opening_balance": opening_balance,
        "closing_balance": closing_balance,
    }


@router.get("/mappings")
def get_mappings(bank_ledger_name: str = ""):
    """Retrieve learned memory rules."""
    rules = list_rules(bank_ledger_name)
    return {"mappings": {
        **load_persistent_mappings(),
        **{f"{r['direction']}: {r['pattern']} ({r['confirmations']} examples)":
           r['ledger'] or "Conflicting choices: review required" for r in rules},
    }, "learned_rules": rules}


@router.post("/generate-xml")
def generate_xml(req: GenerateXmlRequest):
    """Export selected vouchers against Suspense."""
    if req.date_from and req.date_to and req.date_from > req.date_to:
        raise HTTPException(status_code=422, detail="From date must be on or before To date.")
    vouchers_payload = []
    for index, v in enumerate(req.vouchers, start=1):
        if req.date_from or req.date_to:
            try:
                day = voucher_date(v.date)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Voucher {index} has an invalid date.") from exc
            if (req.date_from and day < req.date_from) or (req.date_to and day > req.date_to):
                continue
        vouchers_payload.append({
            "voucher_type": v.voucher_type,
            "date": v.date,
            "bank_ledger": req.bank_ledger_name or v.bank_ledger,
            "party_ledger": SUSPENSE_LEDGER,
            "amount": v.amount,
            "narration": v.narration,
            "instrument_no": v.instrument_no,
        })

    if not vouchers_payload:
        detail = "No vouchers in the selected dates." if req.date_from or req.date_to else "No vouchers provided."
        raise HTTPException(status_code=400, detail=detail)

    try:
        xml_str = generate_tally_xml_envelope(vouchers_payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return Response(
        content=xml_str,
        media_type="application/xml",
        headers={"Content-Disposition": "attachment; filename=tally_import.xml",
                 "X-Learned-Patterns": "0"},
    )


# Include routes with both /api prefix (for local Vite proxy & Vercel) and root (for direct rewrites)
app.include_router(router, prefix="/api")
app.include_router(router, prefix="")


# Serve built frontend if dist folder exists
frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)

