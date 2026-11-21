"""
Smart Ledger Matcher Module
Uses Regex cleaning, keyword heuristic rules, and Fuzzy String Matching
to map bank narrations to Tally Ledgers without putting them in Suspense.
"""

import re
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Persistent mapping dictionary path
MAPPING_FILE = Path(__file__).parent / "mappings.json"


def load_persistent_mappings() -> Dict[str, str]:
    """Loads previously saved user mappings (e.g. {'RAMESH TRADERS': 'Ramesh Traders Pvt Ltd'})."""
    if MAPPING_FILE.exists():
        try:
            with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_persistent_mapping(raw_keyword: str, tally_ledger: str):
    """Saves a confirmed mapping to local memory so it's auto-matched forever."""
    mappings = load_persistent_mappings()
    clean_key = raw_keyword.strip().upper()
    mappings[clean_key] = tally_ledger.strip()
    with open(MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(mappings, f, indent=2, ensure_ascii=False)


def clean_narration(narration: str) -> str:
    """
    Cleans raw bank narration to extract the core party or entity name.
    Example: 'UPI/429103912384/RAMESH TRADERS/HDFC/PAYMENT' -> 'RAMESH TRADERS'
    """
    text = str(narration or "").strip().upper()

    # Split by common delimiters like /, -, :, *
    tokens = re.split(r"[/:\-*|]+", text)
    cleaned_tokens = []

    # Ignore common banking jargon tokens and bank names
    ignore_words = {
        "UPI", "NEFT", "RTGS", "IMPS", "CHQ", "CLG", "DEP", "INB", "MB", "TPT",
        "REV", "CR", "DR", "PAYMENT", "TRANSFER", "BIL", "CMS", "INF", "POS",
        "WDL", "ATM", "TRF", "NACH", "ACH", "VPA", "REF", "TXN", "NET", "BANK",
        "HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "PNB", "BOB", "YES", "IDFC",
        "INDUSIND", "CANARA", "UNION", "PAYOUT", "BILL", "FREIGHT"
    }

    for token in tokens:
        t = token.strip()
        # Skip if alphanumeric reference code (e.g. N49201, UPI1234, or pure digits)
        if re.match(r"^[A-Z]?[0-9]{5,}$", t) or t.isdigit() or (re.match(r"^[A-Z][0-9]+[A-Z0-9]*$", t) and len(t) >= 5):
            continue
        # Skip if single character or in ignore list
        if len(t) <= 1 or t in ignore_words:
            continue
        cleaned_tokens.append(t)

    cleaned_str = " ".join(cleaned_tokens).strip()
    return cleaned_str if cleaned_str else text


# Company Banking Heuristic Rules mapped to actual Ledgers
RULE_PATTERNS = [
    (r"\b(BANK\s*CH(AR)?G(E)?S?|SERVICE\s*CH(AR)?G|SMS\s*ALERT|ANNUAL\s*MAINT|ATM\s*CHG|CONSOL\s*CHG|INTEREST|INT\.?\s*PD|INT\.?\s*COLL)\b", "Financial  Expenses"),
    (r"\b(SALARY|PAYROLL|STIPEND|STAFF|SALARIES|WAGES)\b", "Employee Benefit Expenses"),
    (r"\b(AIRTEL|JIO|VODAFONE|VI|BROADBAND|TELEPHONE|INTERNET|WIFI)\b", "Internet Exp"),
    (r"\b(PETROL|FUEL|DIESEL|HPCL|IOCL|BPCL|CNG)\b", "Fuel Expenses"),
    (r"\b(CONVEYANCE|CAB|UBER|OLA|AUTO|TAXI|TRAVEL|FARE)\b", "Conveyance Expenses"),
    (r"\b(LEGAL|ADVOCATE|LAWYER|COURT|ATTORNEY)\b", "Legal Charges"),
    (r"\b(MAINTENANCE|REPAIR|AMC|SERVICING)\b", "Maintenance Charges"),
    (r"\b(LAUNDRY|DRY\s*CLEAN|WASHER|LINEN)\b", "Laundry Expenses"),
    (r"\b(SOFTWARE|SUBSCRIPTION|AWS|GOOGLE|MICROSOFT|ZOOM|ADOBE|SAAS|GITHUB)\b", "Software Exp"),
    (r"\b(PROFESSIONAL|CONSULT|AUDIT|CHARTERED|CA\b)\b", "PROFESSIONAL FEES"),
    (r"\b(TAX|CBDT|INCOME\s*TAX|TDS|ADVANCE\s*TAX)\b", "CBDT TAX"),
    (r"\b(SALON\s*PURCHASE|BEAUTY\s*PRODUCTS|COSMETIC\s*PURCHASE)\b", "Salon Purchases"),
    (r"\b(SALON\s*CONSUMPTION|CONSUMABLE)\b", "Salon Consumption Expn"),
    (r"\b(SALON\s*EXP|PARLOUR|SPA)\b", "Salon Expenses"),
    (r"\b(HAIR\s*TRANSPLANT|TRANSPLANT|GRAFT)\b", "Hair Transplant"),
    (r"\b(SHOOT|PHOTOGRAPHY|VIDEO|CAMERA)\b", "Shoot Expenses"),
]


def match_narration_to_ledger(
    narration: str,
    ledger_list: List[str],
    similarity_threshold: int = 70,
    bank_ledger: str = "",
    voucher_type: str = "",
) -> Tuple[str, int, str]:
    """
    Matches a narration string against the available Tally ledger list.
    
    Returns:
      (matched_ledger_name, confidence_score_0_to_100, match_reason)
    """
    raw_upper = str(narration or "").upper()
    cleaned = clean_narration(narration)

    from learning import match_learned
    learned = match_learned(narration, ledger_list, bank_ledger, voucher_type)
    if learned:
        return learned

    # 1. Check Saved Memory / Persistent Mappings (100% confidence)
    saved_mappings = load_persistent_mappings()
    for saved_key, saved_ledger in saved_mappings.items():
        if saved_key in raw_upper or saved_key in cleaned:
            if saved_ledger in ledger_list:
                return saved_ledger, 100, f"Saved Memory ('{saved_key}')"

    # 2. Check Heuristic Rules
    for pattern, rule_target in RULE_PATTERNS:
        if re.search(pattern, raw_upper):
            # Check if a matching expense ledger exists in user's Tally ledgers
            for l in ledger_list:
                if rule_target.lower() in l.lower():
                    return l, 95, f"Rule Match ({rule_target})"
            # If not found directly, return the rule target
            return rule_target, 90, f"Rule Suggestion ({rule_target})"

    # 3. Fuzzy Matching against available Tally Ledgers
    try:
        from rapidfuzz import fuzz, process, utils
        # Match using token_set_ratio with default_process (lowercases & strips non-alphanumeric)
        best_match = process.extractOne(
            cleaned,
            ledger_list,
            scorer=fuzz.token_set_ratio,
            processor=utils.default_process
        )
        if best_match:
            candidate, score, _ = best_match
            if score >= similarity_threshold:
                return candidate, int(score), f"Fuzzy Match ({int(score)}%)"
            else:
                return candidate, int(score), f"Low Confidence Match ({int(score)}%)"
    except ImportError:
        # Fallback simple substring search if rapidfuzz is not yet installed
        for l in ledger_list:
            if len(cleaned) >= 4 and (cleaned.lower() in l.lower() or l.lower() in cleaned.lower()):
                return l, 80, "Substring Match"

    # If completely unmatched, suggest Suspense A/c with 0 score
    return "Suspense A/c", 0, "No Match Found"
