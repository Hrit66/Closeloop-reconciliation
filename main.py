import logging
import os
from data_loader import load_ledger, load_bank, load_ground_truth, validate_data
from matcher import Matcher
from llm_matcher import LLMMatcher
from report import evaluate_results, write_exceptions, write_report, print_summary
from config import CONFIG
from models import MatchMethod

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)


def main():
    log.info("Starting CloseLoop reconciliation...")
    
    log.info("Loading data...")
    ledger = load_ledger()
    bank = load_bank()
    ground_truth = load_ground_truth()
    validate_data(ledger, bank, ground_truth)
    
    log.info("Running Tier 1-3 matcher (rule-based)...")
    matcher = Matcher()
    tier13_results = matcher.match(ledger, bank)
    
    # Check if LLM should run
    unresolved = [r for r in tier13_results if r.method == MatchMethod.UNRESOLVED or r.confidence < 0.7]
    log.info(f"Found {len(unresolved)} unresolved/low-confidence results")
    
    if unresolved:
        log.info("Running Tier 4 LLM matcher...")
        llm_matcher = LLMMatcher(use_mock=False)
        final_results = llm_matcher.match_unresolved(tier13_results, ledger, bank)
    else:
        final_results = tier13_results
    
    log.info("Evaluating against ground truth...")
    report = evaluate_results(tier13_results, final_results, ground_truth)
    
    log.info("Writing outputs...")
    write_exceptions(final_results, ground_truth)
    write_report(report)
    print_summary(report)
    
    log.info("Done!")


if __name__ == "__main__":
    main()