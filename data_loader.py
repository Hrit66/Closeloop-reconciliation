import pandas as pd
from typing import List, Dict, Tuple
from models import LedgerRow, BankRow, MatchMethod
from config import CONFIG


REQUIRED_LEDGER_COLS = [
    "id", "amount", "fee", "tax", "method", "bank", "status",
    "acquirer_data.bank_transaction_id", "created_at",
    "net_amount", "settlement_date", "description"
]

REQUIRED_BANK_COLS = REQUIRED_LEDGER_COLS


def load_ledger(path: str = None) -> List[LedgerRow]:
    path = path or CONFIG.LEDGER_PATH
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_LEDGER_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Ledger missing columns: {missing}")
    return [LedgerRow.from_dict(row) for row in df.to_dict("records")]


def load_bank(path: str = None) -> List[BankRow]:
    path = path or CONFIG.BANK_PATH
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_BANK_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Bank CSV missing columns: {missing}")
    return [BankRow.from_dict(row) for row in df.to_dict("records")]


def load_ground_truth(path: str = None) -> Dict[str, Tuple[List[str], MatchMethod]]:
    path = path or CONFIG.GROUND_TRUTH_PATH
    df = pd.read_csv(path)
    if "settlement_id" not in df.columns or "expected_payment_ids" not in df.columns:
        raise ValueError("ground_truth.csv must have settlement_id and expected_payment_ids columns")
    
    truth = {}
    for _, row in df.iterrows():
        settlement_id = row["settlement_id"]
        payment_ids = [pid.strip() for pid in str(row["expected_payment_ids"]).split(",") if pid.strip()]
        method_str = row.get("match_type", "BATCH")
        try:
            method = MatchMethod(method_str)
        except ValueError:
            method = MatchMethod.BATCH
        truth[settlement_id] = (payment_ids, method)
    return truth


def validate_data(ledger: List[LedgerRow], bank: List[BankRow], ground_truth: Dict):
    ledger_ids = {r.id for r in ledger}
    bank_ids = {r.id for r in bank}
    
    for settlement_id, (expected_ids, _) in ground_truth.items():
        if settlement_id not in bank_ids:
            raise ValueError(f"Ground truth settlement {settlement_id} not found in bank data")
        for pid in expected_ids:
            if pid not in ledger_ids:
                raise ValueError(f"Ground truth payment {pid} not found in ledger")
    
    print(f"Validation passed: {len(ledger)} ledger rows, {len(bank)} bank rows, {len(ground_truth)} ground truth entries")