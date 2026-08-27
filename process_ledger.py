import json
import pandas as pd
from datetime import datetime, timedelta
import random

with open("data/raw_payments.json") as f:
    data = json.load(f)

items = data.get("items", [])
print(f"Loaded {len(items)} payments")

df = pd.json_normalize(items)

cols_to_keep = [
    "id", "amount", "fee", "tax", "method", "bank", "status",
    "acquirer_data.bank_transaction_id", "created_at"
]

for col in cols_to_keep:
    if col not in df.columns:
        df[col] = None

df = df[cols_to_keep].copy()

df["net_amount"] = df["amount"] - df["fee"].fillna(0) - df["tax"].fillna(0)

df["created_at"] = pd.to_datetime(df["created_at"], unit="s")
df["settlement_date"] = df["created_at"] + pd.to_timedelta(
    [random.randint(1, 2) for _ in range(len(df))], unit="D"
)

def make_description(row):
    bank = str(row["bank"]) if pd.notna(row["bank"]) else "UNKNOWN"
    btid = str(row["acquirer_data.bank_transaction_id"]) if pd.notna(row["acquirer_data.bank_transaction_id"]) else ""
    if btid:
        short = btid[:12].upper()
        return f"{bank[:10].upper()}-{short}"
    return bank[:18].upper()

df["description"] = df.apply(make_description, axis=1)

df = df.sort_values("created_at").reset_index(drop=True)

df.to_csv("data/razorpay_ledger.csv", index=False)
print(f"Saved {len(df)} rows to data/razorpay_ledger.csv")
print(df.head())

settled = df[df["status"] == "captured"].copy()
if len(settled) > 0:
    batch_rows = []
    for i in range(0, len(settled), random.randint(2, 4)):
        batch = settled.iloc[i:i+random.randint(2, 4)]
        if len(batch) < 2:
            continue
        batch_rows.append({
            "id": f"BATCH_{batch.iloc[0]['id'][:8]}",
            "amount": batch["net_amount"].sum(),
            "fee": 0,
            "tax": 0,
            "method": "batch_settlement",
            "bank": batch.iloc[0]["bank"] or "UNKNOWN",
            "status": "settled",
            "acquirer_data.bank_transaction_id": f"BATCH_{random.randint(100000,999999)}",
            "created_at": batch["created_at"].min(),
            "net_amount": batch["net_amount"].sum(),
            "settlement_date": batch["settlement_date"].max(),
            "description": f"BATCH-{(batch.iloc[0]['bank'] or 'UNK')[:8].upper()}-{len(batch)}TXN"
        })
    
    if batch_rows:
        batch_df = pd.DataFrame(batch_rows)
        batch_df.to_csv("data/bank_settlements.csv", index=False)
        print(f"Generated {len(batch_rows)} batch settlement rows to data/bank_settlements.csv")