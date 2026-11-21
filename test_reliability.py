import asyncio
import unittest
from io import BytesIO
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from parser import clean_number, parse_bank_pdf, parse_excel_or_csv
from server import parse_statement


class StatementChecks(unittest.TestCase):
    def parse(self, content):
        return asyncio.run(parse_statement(UploadFile(file=BytesIO(content), filename="test.csv"), ""))

    def test_balance_mismatch_and_duplicates_are_reported(self):
        content = b"Date,Narration,Debit,Credit,Balance\n01/11/2026,TEST,100,,900\n02/11/2026,SECOND,,200,1200\n02/11/2026,SECOND,,200,1200\n"
        result = self.parse(content)
        self.assertEqual(result["count"], 3)
        self.assertTrue(any("Balance mismatch" in w for w in result["warnings"]))
        self.assertTrue(any("repeats" in w for w in result["warnings"]))

    def test_balanced_statement_has_no_warning(self):
        content = b"Date,Narration,Debit,Credit,Balance\n01/11/2026,TEST,100,,900\n02/11/2026,SECOND,,200,1100\n"
        self.assertEqual(self.parse(content)["warnings"], [])

    def test_bad_number_is_rejected(self):
        for value in ["unreadable", "inf", "NaN"]:
            with self.assertRaises(ValueError):
                clean_number(value)

    def test_both_amount_columns_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_excel_or_csv(b"Date,Narration,Debit,Credit\n01/11/2026,TEST,100,200\n", "test.csv")

    def test_upload_size_and_empty_file(self):
        for content, status in [(b"", 400), (b"x" * (4 * 1024 * 1024 + 1), 413)]:
            with self.assertRaises(HTTPException) as error:
                self.parse(content)
            self.assertEqual(error.exception.status_code, status)

    def test_unknown_first_direction_requires_review(self):
        page = unittest.mock.Mock()
        page.extract_tables.return_value = []
        page.extract_text.return_value = "Date Narration Withdrawal ClosingBalance\n01/11/26 TEST 01/11/26 100.00 900.00"
        with patch("pdfplumber.open") as opened:
            opened.return_value.__enter__.return_value.pages = [page]
            rows = parse_bank_pdf(b"unused")
        self.assertTrue(rows[0]["needs_direction_review"])

    def test_unreadable_pdf_row_is_reported(self):
        page = unittest.mock.Mock()
        page.extract_tables.return_value = []
        page.extract_text.return_value = "Date Narration Withdrawal ClosingBalance\n01/11/26 TEST NO AMOUNT"
        with patch("pdfplumber.open") as opened:
            opened.return_value.__enter__.return_value.pages = [page]
            with self.assertRaises(ValueError):
                parse_bank_pdf(b"unused")


if __name__ == "__main__":
    unittest.main()
