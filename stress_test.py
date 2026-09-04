import time
import random
import pandas as pd
from data_loader import load_ledger, load_bank, load_ground_truth
from matcher import Matcher
from llm_matcher import LLMMatcher
from models import MatchMethod
from config import CONFIG


def generate_large_dataset(num_payments: int, num_settlements: int):
    """Generate synthetic dataset at scale for stress testing."""
    from models import LedgerRow, BankRow
    from datetime import datetime, timedelta
    
    payments = []
    settlements = []
    
    # Generate payments
    for i in range(num_payments):
        amount = random.randint(10000, 100000)
        fee = random.randint(0, 500)
        tax = random.randint(0, 100)
        net_amount = amount - fee - tax
        
        p = LedgerRow(
            id=f"pay_{i:06d}",
            amount=amount,
            fee=fee,
            tax=tax,
            method=random.choice(["card", "netbanking", "upi", "wallet", "emi", "paylater"]),
            bank=random.choice(["HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "CNRB", "PNB", "BOB", "IDFC", "YESB", None]),
            status="captured",
            bank_transaction_id=str(random.randint(10000000, 99999999)),
            created_at=datetime.now() - timedelta(days=random.randint(0, 30)),
            net_amount=net_amount,
            settlement_date=datetime.now() - timedelta(days=random.randint(0, 28)),
            description="STRESS-TEST"
        )
        payments.append(p)
    
    # Generate settlements from payments (known ground truth)
    payment_ids = [p.id for p in payments]
    random.shuffle(payment_ids)
    
    ground_truth = {}
    for s in range(num_settlements):
        batch_size = random.randint(2, 5)
        batch_ids = payment_ids[:batch_size]
        payment_ids = payment_ids[batch_size:]
        
        total = sum(p.net_amount for p in payments if p.id in batch_ids)
        settle_date = max(p.settlement_date for p in payments if p.id in batch_ids)
        
        settlement_id = f"BATCH_STRESS_{s:04d}"
        b = BankRow(
            id=settlement_id,
            amount=total,
            fee=0,
            tax=0,
            method="batch_settlement",
            bank="MULTI",
            status="settled",
            bank_transaction_id=f"BATCH_{random.randint(100000,999999)}",
            created_at=min(p.created_at for p in payments if p.id in batch_ids),
            net_amount=total,
            settlement_date=settle_date + timedelta(days=random.randint(1, 3)),
            description=f"BATCH-MULTI-{batch_size}TXN"
        )
        settlements.append(b)
        ground_truth[settlement_id] = (batch_ids, MatchMethod.BATCH)
    
    return payments, settlements, ground_truth


def run_stress_test(sizes: list = [(100, 20), (500, 100), (1000, 200)]):
    print("=" * 60)
    print("STRESS TEST RESULTS")
    print("=" * 60)
    
    for num_payments, num_settlements in sizes:
        print(f"\n--- {num_payments} payments, {num_settlements} settlements ---")
        
        # Generate data
        payments, settlements, ground_truth = generate_large_dataset(num_payments, num_settlements)
        
        # Run matcher (rule-based only for speed)
        matcher = Matcher()
        start = time.time()
        results = matcher.match(payments, settlements)
        rule_time = time.time() - start
        
        rule_resolved = sum(1 for r in results if r.method != MatchMethod.UNRESOLVED)
        
        # Run LLM (mock mode for speed)
        llm = LLMMatcher(use_mock=True)
        start = time.time()
        results = llm.match_unresolved(results, payments, settlements)
        llm_time = time.time() - start
        
        resolved = sum(1 for r in results if r.method != MatchMethod.UNRESOLVED)
        
        # Accuracy
        correct = sum(1 for r in results if r.settlement_id in ground_truth 
                     and set(r.matched_payment_ids) == set(ground_truth[r.settlement_id][0]))
        
        print(f"  Rule-based: {rule_resolved}/{num_settlements} ({rule_time:.2f}s)")
        print(f"  LLM (mock): {resolved}/{num_settlements} ({llm_time:.2f}s)")
        print(f"  Accuracy:   {correct}/{num_settlements} = {correct/num_settlements:.1%}")
        
        # Check duplicates
        all_matched = [pid for r in results for pid in r.matched_payment_ids]
        print(f"  Duplicates: {len(all_matched) - len(set(all_matched))}")
    
    print("\n" + "=" * 60)


def audit_wrong_answers():
    """Audit specific wrong matches from the real dataset."""
    print("\n" + "=" * 60)
    print("AUDIT: WRONG ANSWERS FROM REAL DATASET")
    print("=" * 60)
    
    from data_loader import load_ledger, load_bank, load_ground_truth
    ledger = load_ledger()
    bank = load_bank()
    ground_truth = load_ground_truth()
    
    matcher = Matcher()
    results = matcher.match(ledger, bank)
    llm = LLMMatcher(use_mock=False)
    results = llm.match_unresolved(results, ledger, bank)
    
    for r in results:
        if r.settlement_id in ground_truth:
            expected_ids, _ = ground_truth[r.settlement_id]
            matched_set = set(r.matched_payment_ids)
            expected_set = set(expected_ids)
            
            if matched_set != expected_set:
                print(f"\n❌ {r.settlement_id} ({r.method}, conf={r.confidence:.2f})")
                print(f"   Matched: {r.matched_payment_ids}")
                print(f"   Expected: {expected_ids}")
                print(f"   Reason: {r.reasoning}")
                
                # Analyze why
                matched_banks = [p.bank for p in ledger if p.id in r.matched_payment_ids]
                expected_banks = [p.bank for p in ledger if p.id in expected_ids]
                print(f"   Matched banks: {matched_banks}")
                print(f"   Expected banks: {expected_banks}")


if __name__ == "__main__":
    run_stress_test([(100, 20)])  # Start small
    # audit_wrong_answers()