import os
import json
import razorpay
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))

def fetch_all_payments(count=100):
    payments = client.payment.all({"count": count})
    return payments

def save_raw_json(data, filename):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"Saved {len(data.get('items', []))} payments to {filename}")

if __name__ == "__main__":
    print("Fetching all recent payments (up to 100)...")
    payments = fetch_all_payments(100)
    save_raw_json(payments, "data/raw_payments.json")
    print("Done. Raw JSON saved as permanent proof file.")