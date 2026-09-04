import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    AMOUNT_TOLERANCE: float = 1.0
    MIN_LAG_DAYS: int = 0
    MAX_LAG_DAYS: int = 5
    FUZZY_LAG_DAYS: int = 10
    MAX_BATCH_SIZE: int = 5
    MAX_COMBINATIONS: int = 50000
    AMOUNT_PRE_FILTER_RATIO: float = 3.0  # Only consider payments <= 3x target
    
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "")
    
    LEDGER_PATH: str = "data/razorpay_ledger.csv"
    BANK_PATH: str = "data/bank_settlements.csv"
    GROUND_TRUTH_PATH: str = "data/ground_truth.csv"
    EXCEPTIONS_PATH: str = "data/exceptions.csv"
    REPORT_PATH: str = "data/match_report.json"

CONFIG = Config()