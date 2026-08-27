import json
import pandas as pd
from datetime import datetime, timedelta
import random
import uuid

with open("data/raw_payments.json") as f:
    real_data = json.load(f)

real_items = real_data.get("items", [])
print(f"Real payments: {len(real_items)}")

methods = ["card", "netbanking", "upi", "wallet", "emi", "paylater"]
banks = ["HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "CNRB", "PNB", "BOB", "IDFC", "YESB"]
statuses = ["captured", "captured", "captured", "captured", "failed", "authorized"]

def random_btid():
    return str(random.randint(10000000, 99999999))

def random_payment_id():
    return f"pay_{uuid.uuid4().hex[:14]}"

def random_order_id():
    return f"order_{uuid.uuid4().hex[:14]}"

synthetic = []
needed = 60 - len(real_items)
base_time = int(datetime.now().timestamp()) - 86400 * 2

for i in range(needed):
    method = random.choice(methods)
    bank = random.choice(banks) if method != "upi" else None
    status = random.choice(statuses)
    amount = random.randint(10000, 60000)
    fee = round(amount * random.uniform(0.015, 0.025))
    tax = round(fee * 0.18)
    
    created = base_time + random.randint(0, 86400 * 2)
    
    payment = {
        "id": random_payment_id(),
        "entity": "payment",
        "amount": amount,
        "currency": "INR",
        "status": status,
        "order_id": random_order_id(),
        "invoice_id": None,
        "international": False,
        "method": method,
        "amount_refunded": 0,
        "refund_status": None,
        "captured": status == "captured",
        "description": "Test payment for reconciliation",
        "card_id": None,
        "bank": bank,
        "wallet": None,
        "vpa": "test@razorpay" if method == "upi" else None,
        "email": "test@closeloop.com",
        "contact": "9999999999",
        "fee": fee if status == "captured" else 0,
        "tax": tax if status == "captured" else 0,
        "error_code": None,
        "error_description": None,
        "error_source": None,
        "error_step": None,
        "error_reason": None,
        "acquirer_data": {
            "bank_transaction_id": random_btid() if status == "captured" and method != "paylater" else None,
            "auth_code": str(random.randint(100000, 999999)) if status == "captured" else None,
            "rrn": str(random.randint(100000000000, 999999999999)) if status == "captured" else None
        } if status == "captured" else {},
        "created_at": created
    }
    synthetic.append(payment)

all_items = real_items + synthetic
real_data["items"] = all_items
real_data["count"] = len(all_items)

with open("data/raw_payments.json", "w") as f:
    json.dump(real_data, f, indent=2, default=str)

print(f"Added {len(synthetic)} synthetic payments")
print(f"Total payments: {len(all_items)}")