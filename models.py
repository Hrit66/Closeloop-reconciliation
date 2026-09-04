from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional


class MatchMethod(Enum):
    EXACT = "EXACT"
    BATCH = "BATCH"
    FUZZY_RULE = "FUZZY_RULE"
    LLM = "LLM"
    UNRESOLVED = "UNRESOLVED"


@dataclass
class LedgerRow:
    id: str
    amount: float
    fee: float
    tax: float
    method: str
    bank: Optional[str]
    status: str
    bank_transaction_id: Optional[str]
    created_at: datetime
    net_amount: float
    settlement_date: datetime
    description: str

    @classmethod
    def from_dict(cls, d: dict) -> "LedgerRow":
        return cls(
            id=d["id"],
            amount=float(d["amount"]),
            fee=float(d.get("fee", 0) or 0),
            tax=float(d.get("tax", 0) or 0),
            method=d.get("method", ""),
            bank=d.get("bank") if pd_notna(d.get("bank")) else None,
            status=d.get("status", ""),
            bank_transaction_id=d.get("acquirer_data.bank_transaction_id") if pd_notna(d.get("acquirer_data.bank_transaction_id")) else None,
            created_at=pd_to_datetime(d["created_at"]),
            net_amount=float(d["net_amount"]),
            settlement_date=pd_to_datetime(d["settlement_date"]),
            description=d.get("description", ""),
        )


@dataclass
class BankRow:
    id: str
    amount: float
    fee: float
    tax: float
    method: str
    bank: Optional[str]
    status: str
    bank_transaction_id: Optional[str]
    created_at: datetime
    net_amount: float
    settlement_date: datetime
    description: str

    @classmethod
    def from_dict(cls, d: dict) -> "BankRow":
        return cls(
            id=d["id"],
            amount=float(d["amount"]),
            fee=float(d.get("fee", 0) or 0),
            tax=float(d.get("tax", 0) or 0),
            method=d.get("method", ""),
            bank=d.get("bank") if pd_notna(d.get("bank")) else None,
            status=d.get("status", ""),
            bank_transaction_id=d.get("acquirer_data.bank_transaction_id") if pd_notna(d.get("acquirer_data.bank_transaction_id")) else None,
            created_at=pd_to_datetime(d["created_at"]),
            net_amount=float(d["net_amount"]),
            settlement_date=pd_to_datetime(d["settlement_date"]),
            description=d.get("description", ""),
        )


@dataclass
class MatchResult:
    settlement_id: str
    matched_payment_ids: List[str]
    method: MatchMethod
    confidence: float
    reasoning: str
    expected_payment_ids: Optional[List[str]] = None
    is_correct: Optional[bool] = None


def pd_notna(val) -> bool:
    import pandas as pd
    return pd.notna(val) and val != ""


def pd_to_datetime(val) -> datetime:
    import pandas as pd
    return pd.to_datetime(val)