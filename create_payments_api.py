import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

KEY_ID = os.getenv("RAZORPAY_KEY_ID")
KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

with open("data/test_orders.json") as f:
    orders = json.load(f)

METHOD_PAYLOADS = {
    "netbanking": {"method": "netbanking", "bank": "HDFC"},
    "upi": {"method": "upi", "vpa": "test@razorpay"},
    "wallet": {"method": "wallet", "wallet": "razorpay"},
    "emi": {"method": "emi", "emi_issuer": "HDFC", "emi_plan": "3"},
}

created_payments = []
for order in orders:
    method = order.get("notes", {}).get("method", "card")
    if method in METHOD_PAYLOADS:
        payload = {
            "amount": order["amount"],
            "currency": "INR",
            "order_id": order["id"],
            **METHOD_PAYLOADS[method]
        }
        try:
            resp = requests.post(
                "https://api.razorpay.com/v1/payments",
                auth=(KEY_ID, KEY_SECRET),
                json=payload
            )
            if resp.status_code == 200:
                payment = resp.json()
                created_payments.append(payment)
                print(f"Created {method} payment: {payment['id']} for order {order['id']}")
            else:
                print(f"Failed {method} for {order['id']}: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"Error {method} for {order['id']}: {e}")

with open("data/api_payments.json", "w") as f:
    json.dump(created_payments, f, indent=2, default=str)

print(f"\nCreated {len(created_payments)} payments via API")