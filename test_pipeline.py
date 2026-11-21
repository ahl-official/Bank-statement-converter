"""
Pipeline test script to verify parsing, matching, and XML generation end-to-end.
"""

from parser import parse_excel_or_csv
from matcher import match_narration_to_ledger, clean_narration
from tally_xml import generate_tally_xml_envelope

SAMPLE_LEDGERS = [
    "Suspense A/c",
    "Bank Charges",
    "Interest Received",
    "Salary Expenses",
    "Telephone & Internet Expenses",
    "Ramesh Enterprises Pvt Ltd",
    "Shree Ganesh Logistics",
    "Krishna Traders",
    "Airtel Broadband Services",
    "Amazon Seller Services",
]

def run_test():
    with open("sample_bank_statement.csv", "rb") as f:
        file_bytes = f.read()

    txns = parse_excel_or_csv(file_bytes, "sample_bank_statement.csv")
    print(f"[SUCCESS] Parsed {len(txns)} transactions from CSV.\n")

    vouchers = []
    print(f"{'Date':<12} {'Type':<8} {'Amount':<10} {'Cleaned Party':<25} {'Matched Ledger':<28} {'Score':<8} {'Reason'}")
    print("-" * 115)

    for t in txns:
        matched_ledger, score, reason = match_narration_to_ledger(
            t["narration"],
            SAMPLE_LEDGERS,
            similarity_threshold=65
        )
        cleaned = clean_narration(t["narration"])
        print(f"{t['date']:<12} {t['voucher_type']:<8} Rs.{t['amount']:<8.2f} {cleaned[:24]:<25} {matched_ledger[:27]:<28} {score}%{'':<3} {reason}")

        vouchers.append({
            "voucher_type": t["voucher_type"],
            "date": t["date"],
            "bank_ledger": "HDFC Bank Current A/c",
            "party_ledger": matched_ledger,
            "amount": t["amount"],
            "narration": t["narration"],
            "instrument_no": t.get("instrument_no", ""),
        })

    xml_output = generate_tally_xml_envelope(vouchers)
    with open("output_test_tally.xml", "w", encoding="utf-8") as out:
        out.write(xml_output)

    print("\n[SUCCESS] Generated 'output_test_tally.xml' successfully!")
    print(f"Total XML size: {len(xml_output)} characters.")

if __name__ == "__main__":
    run_test()
