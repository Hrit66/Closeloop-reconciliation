import json
import csv
from datetime import datetime
from typing import List, Dict
from models import MatchResult, MatchMethod
from config import CONFIG


def evaluate_results(tier13_results: List[MatchResult], final_results: List[MatchResult], ground_truth: Dict[str, tuple]) -> Dict:
    total = len(final_results)
    resolved = sum(1 for r in final_results if r.method != MatchMethod.UNRESOLVED)
    match_rate = resolved / total if total > 0 else 0.0
    
    correct = 0
    incorrect = 0
    unresolved_count = 0
    unmatched_in_truth = 0
    
    for result in final_results:
        if result.settlement_id in ground_truth:
            expected_ids, expected_method = ground_truth[result.settlement_id]
            matched_set = set(result.matched_payment_ids)
            expected_set = set(expected_ids)
            
            if result.method == MatchMethod.UNRESOLVED:
                unresolved_count += 1
            elif matched_set == expected_set:
                result.is_correct = True
                correct += 1
            else:
                result.is_correct = False
                incorrect += 1
        elif result.method != MatchMethod.UNRESOLVED:
            unmatched_in_truth += 1
    
    # Track tier attribution
    tier13_methods = {}
    final_methods = {}
    for r in tier13_results:
        tier13_methods[r.method.value] = tier13_methods.get(r.method.value, 0) + 1
    for r in final_results:
        final_methods[r.method.value] = final_methods.get(r.method.value, 0) + 1
    
    # Accuracy = correct / total
    accuracy = round(correct / total, 4) if total > 0 else 0.0
    
    return {
        "timestamp": datetime.now().isoformat(),
        "total_settlements": total,
        "resolved": resolved,
        "unresolved": unresolved_count,
        "match_rate": round(match_rate, 4),
        "correct_matches": correct,
        "incorrect_matches": incorrect,
        "unmatched_in_truth": unmatched_in_truth,
        "accuracy": accuracy,
        "tier13_method_breakdown": tier13_methods,
        "final_method_breakdown": final_methods
    }


def write_exceptions(results: List[MatchResult], ground_truth: Dict[str, tuple], path: str = None):
    path = path or CONFIG.EXCEPTIONS_PATH
    
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "settlement_id", "matched_payment_ids", "method", "confidence",
            "reasoning", "expected_payment_ids", "expected_method", "is_correct"
        ])
        
        for r in results:
            expected_ids, expected_method = ground_truth.get(r.settlement_id, ([], None))
            writer.writerow([
                r.settlement_id,
                ",".join(r.matched_payment_ids),
                r.method.value,
                r.confidence,
                r.reasoning,
                ",".join(expected_ids) if expected_ids else "",
                expected_method.value if expected_method else "",
                r.is_correct if r.is_correct is not None else ""
            ])
    
    print(f"Exceptions written to {path}")


def write_report(report: Dict, path: str = None):
    path = path or CONFIG.REPORT_PATH
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written to {path}")


def print_summary(report: Dict):
    print("\n" + "=" * 50)
    print("RECONCILIATION REPORT")
    print("=" * 50)
    print(f"Total settlements:     {report['total_settlements']}")
    print(f"Resolved:              {report['resolved']}")
    print(f"Unresolved:            {report['unresolved']}")
    print(f"Match rate:            {report['match_rate']:.2%}")
    print(f"Correct matches:       {report['correct_matches']}")
    print(f"Incorrect matches:     {report['incorrect_matches']}")
    print(f"Accuracy (vs truth):   {report['accuracy']:.2%}")
    print(f"\nTier 1-3 (rule-based) breakdown:")
    for method, count in report.get('tier13_method_breakdown', {}).items():
        print(f"  {method:15s}: {count}")
    print(f"\nFinal (after LLM) breakdown:")
    for method, count in report.get('final_method_breakdown', {}).items():
        print(f"  {method:15s}: {count}")
    print("=" * 50)