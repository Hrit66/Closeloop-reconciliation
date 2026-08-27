import os
import json
import razorpay
from dotenv import load_dotenv
from datetime import datetime
import random
import time

load_dotenv()

client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))

METHODS = ["card", "netbanking", "upi", "wallet", "emi"]

def create_orders(count=60, amount_base=10000):
    orders = []
    for i in range(count):
        amount = amount_base + random.randint(0, 50000)
        method = random.choice(METHODS)
        order = client.order.create({
            "amount": amount,
            "currency": "INR",
            "receipt": f"receipt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i:03d}",
            "notes": {
                "source": "test_suite",
                "batch": "closeLoop_test",
                "index": str(i),
                "method": method
            }
        })
        orders.append(order)
        print(f"Created order: {order['id']} - Amount: {amount/100:.2f} INR - Method: {method}")
        time.sleep(0.3)
    return orders

def generate_checkout_html(orders, output_file="test_checkout.html"):
    key_id = os.getenv("RAZORPAY_KEY_ID")
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>CloseLoop Test Payments</title>
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <style>
        body {{ font-family: system-ui; max-width: 900px; margin: 2rem auto; padding: 1rem; }}
        .order-card {{ border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin: 0.5rem 0; display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }}
        .btn {{ background: #02042B; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-size: 0.875rem; }}
        .btn:hover {{ background: #1a1d4a; }}
        .amount {{ font-size: 1rem; font-weight: bold; color: #02042B; min-width: 100px; }}
        .order-id {{ font-family: monospace; font-size: 0.75rem; color: #666; flex: 1; }}
        .method-badge {{ background: #e8f0fe; color: #1a73e8; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; }}
        .paid {{ background: #e6f4ea; color: #1e7e34; }}
    </style>
</head>
<body>
    <h1>CloseLoop - Test Payment Suite ({len(orders)} orders)</h1>
    <p>Use test card: <strong>4111 1111 1111 1111</strong> | Any future date | Any CVV | Click "Pay Now" for each</p>
    <div id="orders">
"""
    for order in orders:
        amount_inr = order['amount'] / 100
        method = order.get('notes', {}).get('method', 'card')
        html += f"""
        <div class="order-card" id="card-{order['id']}">
            <div class="amount">₹{amount_inr:,.2f}</div>
            <div class="order-id">{order['id']}</div>
            <span class="method-badge">{method}</span>
            <button class="btn" onclick="pay('{order['id']}', {order['amount']}, this)">Pay Now</button>
        </div>
"""
    html += f"""
    </div>
    <script>
        function pay(orderId, amount, btn) {{
            var options = {{
                key: "{key_id}",
                amount: amount,
                currency: "INR",
                name: "CloseLoop Test",
                description: "Test payment for reconciliation",
                order_id: orderId,
                handler: function (response) {{
                    alert("Payment successful! Payment ID: " + response.razorpay_payment_id);
                    console.log("Payment response:", response);
                    btn.textContent = "Paid";
                    btn.classList.add("paid");
                    btn.disabled = true;
                    btn.onclick = null;
                    document.getElementById("card-" + orderId).classList.add("paid");
                }},
                prefill: {{
                    name: "Test User",
                    email: "test@closeloop.com",
                    contact: "9999999999"
                }},
                theme: {{
                    color: "#02042B"
                }}
            }};
            var rzp = new Razorpay(options);
            rzp.open();
        }}
    </script>
</body>
</html>
"""
    with open(output_file, "w") as f:
        f.write(html)
    print(f"Generated {output_file} - open in browser to complete payments")

if __name__ == "__main__":
    orders = create_orders(60)
    generate_checkout_html(orders)
    
    with open("data/test_orders.json", "w") as f:
        json.dump(orders, f, indent=2)
    print("Saved orders to data/test_orders.json")