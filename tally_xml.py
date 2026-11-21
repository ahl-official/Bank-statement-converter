"""
Tally XML Generator Module
Generates valid TallyPrime / Tally.ERP 9 XML envelope for importing Payment and Receipt vouchers.
"""

from xml.sax.saxutils import escape
from datetime import datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree


def format_tally_date(date_val) -> str:
    """Formats various date formats into Tally's YYYYMMDD string format."""
    if isinstance(date_val, str):
        # Clean common date strings: DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD
        clean_str = date_val.strip()
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
            if fmt == "%Y%m%d" and len(clean_str) != 8:
                continue
            try:
                dt = datetime.strptime(clean_str, fmt)
                return dt.strftime("%Y%m%d")
            except ValueError:
                continue
    elif hasattr(date_val, "strftime"):
        return date_val.strftime("%Y%m%d")
    
    raise ValueError("Enter a valid voucher date.")


def voucher_date(date_val):
    """Return a calendar date using the same interpretation as XML export."""
    return datetime.strptime(format_tally_date(date_val), "%Y%m%d").date()


def build_tally_voucher_xml(
    voucher_type: str,
    date_str: str,
    bank_ledger: str,
    party_ledger: str,
    amount: float,
    narration: str = "",
    instrument_no: str = "",
) -> str:
    """
    Creates a single <TALLYMESSAGE> block for a voucher.
    
    voucher_type: 'Payment' (money out/withdrawal) or 'Receipt' (money in/deposit)
    amount: positive float
    """
    voucher_type = voucher_type.strip().capitalize()
    if voucher_type not in {"Payment", "Receipt"}:
        raise ValueError("Voucher type must be Payment or Receipt.")
    date_str = format_tally_date(date_str)
    try:
        amount_value = Decimal(str(amount))
    except InvalidOperation as exc:
        raise ValueError("Voucher amount must be a positive number.") from exc
    if not amount_value.is_finite() or amount_value <= 0:
        raise ValueError("Voucher amount must be a positive number.")
    amount_str = f"{amount_value:.2f}"
    if amount_str == "0.00":
        raise ValueError("Voucher amount rounds to zero.")
    
    clean_narration = escape(str(narration or ""))
    clean_bank = escape(str(bank_ledger or "").strip())
    clean_party = escape(str(party_ledger or "").strip())
    clean_inst = escape(str(instrument_no or "").strip())
    if not clean_bank or not clean_party:
        raise ValueError("Both bank and counterpart ledger names are required.")
    if clean_bank.casefold() == clean_party.casefold():
        raise ValueError("Bank and counterpart ledgers must be different.")
    
    # In Tally XML Amount convention:
    # Debits:  ISDEEMEDPOSITIVE = Yes, AMOUNT = -amount
    # Credits: ISDEEMEDPOSITIVE = No,  AMOUNT = +amount
    
    if voucher_type == "Payment":
        # Payment: Debit Party, Credit Bank
        vch_type_name = "Payment"
        ledger_entries = f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{clean_party}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>-{amount_str}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{clean_bank}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>{amount_str}</AMOUNT>
              {f'<INSTRUMENTNUMBER>{clean_inst}</INSTRUMENTNUMBER>' if clean_inst else ''}
            </ALLLEDGERENTRIES.LIST>"""
    else:
        # Receipt: Debit Bank, Credit Party
        vch_type_name = "Receipt"
        ledger_entries = f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{clean_bank}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>-{amount_str}</AMOUNT>
              {f'<INSTRUMENTNUMBER>{clean_inst}</INSTRUMENTNUMBER>' if clean_inst else ''}
            </ALLLEDGERENTRIES.LIST>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{clean_party}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>{amount_str}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>"""

    return f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="{vch_type_name}" ACTION="Create" OBJVIEW="Accounting Voucher View">
            <DATE>{date_str}</DATE>
            <EFFECTIVEDATE>{date_str}</EFFECTIVEDATE>
            <VOUCHERTYPENAME>{vch_type_name}</VOUCHERTYPENAME>
            <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>
            <ISINVOICE>No</ISINVOICE>
            <NARRATION>{clean_narration}</NARRATION>
            {ledger_entries}
          </VOUCHER>
        </TALLYMESSAGE>"""


def generate_tally_xml_envelope(vouchers_list: list) -> str:
    """
    Wraps all vouchers in the standard Tally <ENVELOPE> XML structure.
    vouchers_list: list of dicts with keys:
      ['voucher_type', 'date', 'bank_ledger', 'party_ledger', 'amount', 'narration', 'instrument_no']
    """
    voucher_xml_blocks = []
    for row, v in enumerate(vouchers_list, start=1):
        try:
            vch_xml = build_tally_voucher_xml(
                voucher_type=v["voucher_type"],
                date_str=v["date"],
                bank_ledger=v["bank_ledger"],
                party_ledger=v["party_ledger"],
                amount=v["amount"],
                narration=v.get("narration", ""),
                instrument_no=v.get("instrument_no", ""),
            )
            ElementTree.fromstring(vch_xml.strip())
        except ElementTree.ParseError as exc:
            raise ValueError(f"Voucher {row} contains characters that XML cannot represent.") from exc
        except ValueError as exc:
            raise ValueError(f"Voucher {row}: {exc}") from exc
        voucher_xml_blocks.append(vch_xml)

    joined_vouchers = "\n".join(voucher_xml_blocks)

    envelope_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>All Vouchers</REPORTNAME>
      </REQUESTDESC>
      <REQUESTDATA>
{joined_vouchers}
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""
    return envelope_xml
