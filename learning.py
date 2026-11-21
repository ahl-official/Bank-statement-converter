"""Local, accountant-confirmed merchant patterns. No automatic guesses are trained."""

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).with_name("ledger_learning.sqlite3")


def merchant_pattern(narration):
    from matcher import clean_narration

    text = clean_narration(narration)
    # Discard dates, amounts, reference codes and changing card identifiers.
    text = re.sub(r"\b\S*\d\S*\b", " ", text)
    words = re.findall(r"[A-Z]+", text.upper())
    noise = {"UPI", "NEFT", "RTGS", "IMPS", "POS", "PAYMENT", "TRANSFER",
             "HDFC", "ICICI", "SBI", "BANK", "REF", "TXN", "CR", "DR",
             "INR", "RS", "CARD", "DEBIT", "CREDIT", "PURCHASE", "TO", "FROM"}
    words = [w for w in words if w not in noise and len(w) > 1]
    return " ".join(words)


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rules (
            scope TEXT, direction TEXT, pattern TEXT, ledger TEXT,
            PRIMARY KEY(scope, direction, pattern)
        );
        CREATE TABLE IF NOT EXISTS examples (
            scope TEXT, direction TEXT, pattern TEXT, fingerprint TEXT, ledger TEXT,
            PRIMARY KEY(scope, direction, fingerprint)
        );
    """)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def learn_corrections(scope, vouchers):
    """Commit only corrected, exported rows, once XML generation succeeds."""
    batches = {}
    for v in vouchers:
        pattern = merchant_pattern(v.narration)
        if len(pattern.replace(" ", "")) < 4 or v.party_ledger == "Suspense A/c":
            continue
        batches.setdefault((v.voucher_type, pattern), []).append(v)
    if not batches:
        return 0
    with _connect() as conn:
        for (direction, pattern), rows in batches.items():
            ledgers = {v.party_ledger for v in rows}
            # Conflicting corrections in one export must not create an auto-rule.
            ledger = next(iter(ledgers)) if len(ledgers) == 1 else None
            conn.execute("INSERT OR REPLACE INTO rules VALUES (?, ?, ?, ?)",
                         (scope.strip(), direction, pattern, ledger))
            for v in rows:
                fingerprint = hashlib.sha256(
                    f"{v.date}|{v.amount:.2f}|{v.narration}".encode("utf-8")
                ).hexdigest()
                conn.execute("INSERT OR REPLACE INTO examples VALUES (?, ?, ?, ?, ?)",
                             (scope.strip(), direction, pattern, fingerprint, v.party_ledger))
    return len(batches)


def list_rules(scope):
    if not DB_PATH.exists():
        return []
    with _connect() as conn:
        return [dict(row) for row in conn.execute("""
            SELECT r.direction, r.pattern, r.ledger, COUNT(e.fingerprint) AS confirmations
            FROM rules r LEFT JOIN examples e
            ON e.scope=r.scope AND e.direction=r.direction AND e.pattern=r.pattern
                AND e.ledger=r.ledger
            WHERE r.scope=? GROUP BY r.direction, r.pattern ORDER BY r.pattern
        """, (scope.strip(),))]


def match_learned(narration, ledgers, scope, direction):
    if not scope or not direction:
        return None
    pattern = merchant_pattern(narration)
    if len(pattern.replace(" ", "")) < 4:
        return None
    rules = [r for r in list_rules(scope) if r["direction"] == direction]
    for rule in rules:
        if rule["pattern"] == pattern:
            if rule["ledger"] is None:
                return "Suspense A/c", 0, "Conflicting learned choices: review required"
            if rule["ledger"] in ledgers:
                return rule["ledger"], 99, f"Learned merchant ({rule['confirmations']} confirmed examples)"
    from rapidfuzz.fuzz import ratio

    candidates = sorted(
        [(ratio(pattern, r["pattern"]), r) for r in rules
         if r["ledger"] in ledgers],
        key=lambda item: item[0], reverse=True,
    )
    if candidates:
        score, best = candidates[0]
        # Require the same first merchant word; reject ambiguous alternatives.
        rival = max((s for s, r in candidates[1:] if r["ledger"] != best["ledger"]), default=0)
        blocked = any(r["ledger"] is None and ratio(pattern, r["pattern"]) >= 92 for r in rules)
        if best["confirmations"] >= 2 and score >= 92 and score - rival >= 8 and not blocked and pattern.split()[0] == best["pattern"].split()[0]:
            return best["ledger"], min(96, int(score)), "Similar learned merchant (review suggestion)"
    return None
