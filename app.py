"""Legacy Streamlit entry point for the local bank statement converter."""

import streamlit as st

from parser import parse_bank_pdf, parse_excel_or_csv
from server import SUSPENSE_LEDGER
from tally_xml import generate_tally_xml_envelope, voucher_date

st.set_page_config(page_title="Bank Statement Converter", layout="wide")
st.title("Bank Statement Converter")
st.write("Export all vouchers against Suspense and clear them in Tally.")
bank_ledger = st.text_input("Bank ledger name in Tally", "HDFC Bank Current A/c")
statement = st.file_uploader("Bank statement", type=["pdf", "xlsx", "xls", "csv"])

if statement is None:
    st.stop()

filename = statement.name.lower()
password = st.text_input("PDF password if required", type="password") if filename.endswith(".pdf") else ""
try:
    contents = statement.getvalue()
    if filename.endswith(".pdf"):
        transactions = parse_bank_pdf(contents, password=password)
    else:
        transactions = parse_excel_or_csv(contents, filename)
except Exception as exc:
    st.error(f"Could not read the statement. Check the file format and PDF password. {exc}")
    st.stop()

if not transactions:
    st.warning("No transactions were found in the statement.")
    st.stop()

from_column, to_column = st.columns(2)
from_date = from_column.date_input("From date", value=None, format="DD/MM/YYYY")
to_date = to_column.date_input("To date", value=None, format="DD/MM/YYYY")
if from_date and to_date and from_date > to_date:
    st.error("From date must be on or before To date.")
    st.stop()
if from_date or to_date:
    in_range = []
    for row in transactions:
        try:
            day = voucher_date(row["date"])
        except ValueError:
            continue
        if (not from_date or day >= from_date) and (not to_date or day <= to_date):
            in_range.append(row)
    transactions = in_range
    if not transactions:
        st.info("No transactions in the selected dates.")
        st.stop()

edited = st.data_editor(
    [{"Include": True, **row, "voucher_type": None if row.get("needs_direction_review") else row["voucher_type"]} for row in transactions],
    hide_index=True,
    disabled=["date", "narration", "amount", "instrument_no"],
    column_config={
        "voucher_type": st.column_config.SelectboxColumn("Voucher type", options=["Payment", "Receipt"], required=True),
    },
)
selected = [
    {**row, "bank_ledger": bank_ledger, "party_ledger": SUSPENSE_LEDGER}
    for row in edited if row["Include"]
]

if not selected or not bank_ledger.strip():
    st.info("Enter the Tally bank ledger name and select at least one transaction.")
    st.stop()
if any(row["voucher_type"] is None for row in selected):
    st.info("Confirm Payment or Receipt for each selected transaction.")
    st.stop()

try:
    xml = generate_tally_xml_envelope(selected)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

st.download_button("Download Tally XML", xml, "tally_import.xml", "application/xml")
st.caption("In TallyPrime, open Alt+O → Transactions and select the XML file.")
