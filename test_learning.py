"""Regression checks for correction learning and export boundaries."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import learning
import server


def voucher(narration="POS/12345678/FIGMA/HDFC", ledger="Software Exp", **kwargs):
    return server.VoucherItem(
        voucher_type=kwargs.pop("voucher_type", "Payment"), date=kwargs.pop("date", "01/11/2026"),
        bank_ledger="HDFC", party_ledger=ledger, amount=100, narration=narration, **kwargs,
    )


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.db_patch = patch.object(learning, "DB_PATH", Path(self.tmp.name) / "learning.sqlite3")
        self.db_patch.start()
        self.ledgers = ["Software Exp", "Subscriptions Expenses"]

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def match(self, narration, scope="HDFC", direction="Payment", ledgers=None):
        return learning.match_learned(narration, ledgers or self.ledgers, scope, direction)

    def test_reference_changes_and_restart_keep_memory(self):
        learning.learn_corrections("HDFC", [voucher()])
        self.assertEqual(self.match("POS/99999999/FIGMA/HDFC")[0], "Software Exp")
        # Every lookup opens a new connection: memory survives process-local state.
        self.assertEqual(learning.list_rules("HDFC")[0]["confirmations"], 1)

    def test_bank_direction_and_active_ledger_boundaries(self):
        learning.learn_corrections("HDFC", [voucher()])
        self.assertIsNone(self.match("FIGMA", scope="OTHER BANK"))
        self.assertIsNone(self.match("FIGMA", direction="Receipt"))
        self.assertIsNone(self.match("FIGMA", ledgers=["Subscriptions Expenses"]))
        self.assertIsNone(self.match("FIGMATIC"))

    def test_repeated_download_is_not_new_evidence(self):
        learning.learn_corrections("HDFC", [voucher()])
        learning.learn_corrections("HDFC", [voucher()])
        self.assertEqual(learning.list_rules("HDFC")[0]["confirmations"], 1)

    def test_similar_spelling_needs_two_distinct_examples(self):
        learning.learn_corrections("HDFC", [voucher("GOOGLE WORKSPACE")])
        self.assertIsNone(self.match("GOOGLE WORKSPAC"))
        learning.learn_corrections("HDFC", [voucher("GOOGLE WORKSPACE", date="02/11/2026")])
        self.assertEqual(self.match("GOOGLE WORKSPAC")[0], "Software Exp")

    def test_conflict_requires_review_and_later_correction_replaces_rule(self):
        learning.learn_corrections("HDFC", [voucher(), voucher(ledger="Subscriptions Expenses")])
        self.assertEqual(self.match("FIGMA")[0], "Suspense A/c")
        learning.learn_corrections("HDFC", [voucher(ledger="Subscriptions Expenses")])
        self.assertEqual(self.match("FIGMA")[0], "Subscriptions Expenses")

    def test_export_uses_suspense_and_does_not_learn(self):
        request = server.GenerateXmlRequest(bank_ledger_name="HDFC", vouchers=[
            voucher(corrected=True), voucher("ADOBE", corrected=False),
        ])
        response = server.generate_xml(request)
        self.assertEqual(response.headers["x-learned-patterns"], "0")
        self.assertEqual(response.body.count(b"<LEDGERNAME>Suspense</LEDGERNAME>"), 2)
        self.assertEqual(learning.list_rules("HDFC"), [])

    def test_disabled_empty_and_failed_exports_do_not_learn(self):
        server.generate_xml(server.GenerateXmlRequest(
            bank_ledger_name="HDFC", vouchers=[voucher(corrected=True)], save_mappings=False))
        with self.assertRaises(server.HTTPException):
            server.generate_xml(server.GenerateXmlRequest(bank_ledger_name="HDFC", vouchers=[]))
        with patch.object(server, "generate_tally_xml_envelope", side_effect=ValueError("failure")):
            with self.assertRaises(server.HTTPException) as error:
                server.generate_xml(server.GenerateXmlRequest(
                    bank_ledger_name="HDFC", vouchers=[voucher(corrected=True)]))
            self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(learning.list_rules("HDFC"), [])

    def test_ambiguous_similar_patterns_do_not_auto_select(self):
        for pattern, ledger in [("GOOGLE WORKSPACE", "Software Exp"),
                                ("GOOGLE WORKSPACES", "Subscriptions Expenses")]:
            learning.learn_corrections("HDFC", [voucher(pattern, ledger),
                voucher(pattern, ledger, date="02/11/2026")])
        self.assertIsNone(self.match("GOOGLE WORKSPAC"))


if __name__ == "__main__":
    unittest.main()
