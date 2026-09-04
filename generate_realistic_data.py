import json
import pandas as pd
from datetime import datetime, timedelta
import random
import uuid

with open("data/raw_payments.json") as f:
    data = json.load(f)

items = data.get("items", [])
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
    [random.randint(1, 3) for _ in range(len(df))], unit="D"
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

settled = df[df["status"] == "captured"].copy()
print(f"Captured payments: {len(settled)}")

# Build realistic bank settlements with MESSINESS
batch_rows = []
batch_payment_map = {}
used_payment_ids = set()

random.seed(42)

# 1. Same-bank, nearby-date batches (clean) - group by bank, allow 1-2 day date window
banks_with_payments = settled[~settled["bank"].isin([None, "", "UNKNOWN", "nan"])].copy()
banks_with_payments = banks_with_payments[~banks_with_payments["id"].isin(used_payment_ids)]

for bank_name in banks_with_payments["bank"].unique():
    bank_payments = banks_with_payments[banks_with_payments["bank"] == bank_name].copy()
    bank_payments = bank_payments.sort_values("settlement_date")
    
    if len(bank_payments) < 2:
        continue
    
    # Group into batches by nearby dates (within 2 days)
    batches_formed = 0
    while len(bank_payments) >= 2 and batches_formed < 3:
        # Take first payment as anchor, find others within 2 days
        anchor = bank_payments.iloc[0]
        anchor_date = anchor["settlement_date"]
        
        nearby = bank_payments[
            (bank_payments["settlement_date"] >= anchor_date - timedelta(days=2)) &
            (bank_payments["settlement_date"] <= anchor_date + timedelta(days=2))
        ]
        
        if len(nearby) < 2:
            break
        
        batch_size = min(random.randint(2, 4), len(nearby))
        batch = nearby.head(batch_size)
        bank_payments = bank_payments[~bank_payments["id"].isin(batch["id"])]
        
        batches_formed += 1
        total_net = batch["net_amount"].sum()
        total_net = round(total_net + random.uniform(-0.05, 0.05), 2)
        
        batch_id = f"BATCH_{bank_name[:4].upper()}_{anchor_date.strftime('%m%d')}_{batches_formed}"
        batch_payment_map[batch_id] = batch["id"].tolist()
        used_payment_ids.update(batch["id"].tolist())
        
        settle_lag = random.randint(0, 2)
        batch_settle = batch["settlement_date"].max() + timedelta(days=settle_lag)
        
        batch_rows.append({
            "id": batch_id,
            "amount": total_net,
            "fee": 0,
            "tax": 0,
            "method": "batch_settlement",
            "bank": bank_name,
            "status": "settled",
            "acquirer_data.bank_transaction_id": f"BATCH_{random.randint(100000,999999)}",
            "created_at": batch["created_at"].min(),
            "net_amount": total_net,
            "settlement_date": batch_settle,
            "description": f"BATCH-{bank_name[:8].upper()}-{len(batch)}TXN"
        })

# 2. Cross-bank / UNKNOWN bank batches (messy)
unknown_bank = settled[
    (settled["bank"].isna()) | 
    (settled["bank"] == "") | 
    (settled["bank"] == "UNKNOWN") |
    (settled["bank"] == "nan")
].copy()
unknown_bank = unknown_bank[~unknown_bank["id"].isin(used_payment_ids)]

# Also steal some from known banks to create cross-bank batches
known_bank = settled[~settled["id"].isin(used_payment_ids)].copy()
all_remaining = pd.concat([unknown_bank, known_bank]).drop_duplicates(subset="id")

if len(all_remaining) >= 2:
    indices = list(range(len(all_remaining)))
    random.shuffle(indices)
    i = 0
    batch_num = 0
    while i < len(indices):
        batch_size = min(random.randint(2, 5), len(indices) - i)
        batch_indices = indices[i:i+batch_size]
        i += batch_size
        if len(batch_indices) < 2:
            break
        
        batch = all_remaining.iloc[batch_indices]
        batch_num += 1
        total_net = batch["net_amount"].sum()
        
        # Add rounding noise (±1-10 paise)
        total_net = round(total_net + random.uniform(-0.10, 0.10), 2)
        
        batch_id = f"BATCH_XBANK_{batch_num}"
        batch_payment_map[batch_id] = batch["id"].tolist()
        used_payment_ids.update(batch["id"].tolist())
        
        # Settlement date 1-3 days after
        settle_lag = random.randint(1, 3)
        batch_settle = batch["settlement_date"].max() + timedelta(days=settle_lag)
        
        batch_rows.append({
            "id": batch_id,
            "amount": total_net,
            "fee": 0,
            "tax": 0,
            "method": "batch_settlement",
            "bank": "MULTI",
            "status": "settled",
            "acquirer_data.bank_transaction_id": f"BATCH_{random.randint(100000,999999)}",
            "created_at": batch["created_at"].min(),
            "net_amount": total_net,
            "settlement_date": batch_settle,
            "description": f"BATCH-MULTI-{len(batch)}TXN"
        })

# 3. PARTIAL settlements (bank only settles part of what's due)
# Pick some payments that WON'T be fully settled
unmatched = settled[~settled["id"].isin(used_payment_ids)].copy()
if len(unmatched) >= 3:
    partial_payments = unmatched.sample(n=min(3, len(unmatched)), random_state=42)
    for _, p in partial_payments.iterrows():
        # Bank settles 70-95% of amount
        partial_amount = round(p["net_amount"] * random.uniform(0.70, 0.95), 2)
        batch_id = f"BATCH_PARTIAL_{p['id'][:8]}"
        
        batch_payment_map[batch_id] = [p["id"]]  # Still maps to this payment
        used_payment_ids.add(p["id"])
        
        settle_lag = random.randint(1, 3)
        batch_settle = p["settlement_date"] + timedelta(days=settle_lag)
        
        batch_rows.append({
            "id": batch_id,
            "amount": partial_amount,
            "fee": 0,
            "tax": 0,
            "method": "batch_settlement",
            "bank": p["bank"] if pd.notna(p["bank"]) else "MULTI",
            "status": "settled",
            "acquirer_data.bank_transaction_id": f"BATCH_{random.randint(100000,999999)}",
            "created_at": p["created_at"],
            "net_amount": partial_amount,
            "settlement_date": batch_settle,
            "description": f"PARTIAL-{p['id'][:8]}"
        })

# 4. Fee-deducted settlements (bank takes extra fee)
fee_payments = settled[~settled["id"].isin(used_payment_ids)].copy()
if len(fee_payments) >= 2:
    fee_payments = fee_payments.sample(n=min(2, len(fee_payments)), random_state=42)
    for _, p in fee_payments.iterrows():
        # Bank deducts extra 0.5-1.5%
        fee_rate = random.uniform(0.005, 0.015)
        net_after_fee = round(p["net_amount"] * (1 - fee_rate), 2)
        batch_id = f"BATCH_FEE_{p['id'][:8]}"
        
        batch_payment_map[batch_id] = [p["id"]]
        used_payment_ids.add(p["id"])
        
        settle_lag = random.randint(1, 3)
        batch_settle = p["settlement_date"] + timedelta(days=settle_lag)
        
        batch_rows.append({
            "id": batch_id,
            "amount": net_after_fee,
            "fee": round(p["net_amount"] * fee_rate, 2),
            "tax": 0,
            "method": "batch_settlement",
            "bank": p["bank"] if pd.notna(p["bank"]) else "MULTI",
            "status": "settled",
            "acquirer_data.bank_transaction_id": f"BATCH_{random.randint(100000,999999)}",
            "created_at": p["created_at"],
            "net_amount": net_after_fee,
            "settlement_date": batch_settle,
            "description": f"FEE-{p['id'][:8]}"
        })

# 5. One completely unmatched payment (orphan)
orphan_candidates = settled[~settled["id"].isin(used_payment_ids)]
if len(orphan_candidates) >= 1:
    orphan = orphan_candidates.sample(n=1, random_state=42).iloc[0]
    # Don't create a batch for it - it stays unresolved

print(f"Generated {len(batch_rows)} batch settlement rows")
print(f"Used {len(used_payment_ids)} payments, {len(settled) - len(used_payment_ids)} orphaned")

if batch_rows:
    batch_df = pd.DataFrame(batch_rows)
    batch_df.to_csv("data/bank_settlements.csv", index=False)
    print(f"Saved to data/bank_settlements.csv")
    
    # Save ground truth
    gt_rows = []
    for batch_id, payment_ids in batch_payment_map.items():
        gt_rows.append({
            "settlement_id": batch_id,
            "expected_payment_ids": ",".join(payment_ids),
            "match_type": "BATCH"
        })
    gt_df = pd.DataFrame(gt_rows)
    gt_df.to_csv("data/ground_truth.csv", index=False)
    print(f"Generated {len(gt_rows)} ground truth entries to data/ground_truth.csv")

print("Done!")