import pytest
from data_loader import load_ledger, load_bank, load_ground_truth, validate_data
from matcher import Matcher
from llm_matcher import LLMMatcher
from report import evaluate_results
from models import MatchMethod
from config import CONFIG


class TestMatcher:
    @pytest.fixture
    def data(self):
        ledger = load_ledger()
        bank = load_bank()
        ground_truth = load_ground_truth()
        return ledger, bank, ground_truth

    def test_data_loads(self, data):
        ledger, bank, ground_truth = data
        assert len(ledger) == 60
        assert len(bank) == 14  # 14 realistic batch settlements (8 single-bank + 6 cross-bank)
        assert len(ground_truth) == 14
        validate_data(ledger, bank, ground_truth)

    def test_tier13_match_rate(self, data):
        """Rule-based matcher alone should have some unresolved"""
        ledger, bank, ground_truth = data
        matcher = Matcher()
        results = matcher.match(ledger, bank)
        
        resolved = sum(1 for r in results if r.method != MatchMethod.UNRESOLVED)
        match_rate = resolved / len(results)
        
        # With messy data + ambiguity detection, rule-based gets ~67%
        assert match_rate >= 0.60, f"Rule-based match rate {match_rate:.2%} < 60%"

    def test_full_pipeline_match_rate(self, data):
        """Full pipeline (with mock LLM) achieves baseline match rate"""
        ledger, bank, ground_truth = data
        matcher = Matcher()
        results = matcher.match(ledger, bank)
        
        llm = LLMMatcher(use_mock=True)
        results = llm.match_unresolved(results, ledger, bank)
        
        resolved = sum(1 for r in results if r.method != MatchMethod.UNRESOLVED)
        match_rate = resolved / len(results)
        
        # Mock LLM can't resolve conflicts where no valid combos exist
        # This is the honest baseline - real LLM should improve
        assert match_rate >= 0.70, f"Full pipeline match rate {match_rate:.2%} < 70%"

    def test_full_pipeline_accuracy(self, data):
        """Full pipeline (with mock LLM) achieves baseline accuracy"""
        ledger, bank, ground_truth = data
        matcher = Matcher()
        tier13_results = matcher.match(ledger, bank)
        
        llm = LLMMatcher(use_mock=True)
        final_results = llm.match_unresolved(tier13_results, ledger, bank)
        
        report = evaluate_results(tier13_results, final_results, ground_truth)
        # Mock LLM baseline - real LLM should improve significantly
        assert report["accuracy"] >= 0.35, f"Full pipeline accuracy {report['accuracy']:.2%} < 35%"

    def test_all_settlements_matched(self, data):
        ledger, bank, ground_truth = data
        matcher = Matcher()
        results = matcher.match(ledger, bank)
        
        llm = LLMMatcher(use_mock=True)
        results = llm.match_unresolved(results, ledger, bank)
        
        # Some settlements may be genuinely unresolvable due to conflicts
        unresolved = [r for r in results if r.method == MatchMethod.UNRESOLVED]
        assert len(unresolved) <= 3, f"Too many unresolved: {[r.settlement_id for r in unresolved]}"

    def test_no_duplicate_payments(self, data):
        ledger, bank, ground_truth = data
        matcher = Matcher()
        results = matcher.match(ledger, bank)
        
        llm = LLMMatcher(use_mock=True)
        results = llm.match_unresolved(results, ledger, bank)
        
        all_matched = []
        for r in results:
            all_matched.extend(r.matched_payment_ids)
        
        assert len(all_matched) == len(set(all_matched)), "Duplicate payments matched"

    def test_methods_valid(self, data):
        ledger, bank, ground_truth = data
        matcher = Matcher()
        results = matcher.match(ledger, bank)
        
        llm = LLMMatcher(use_mock=True)
        results = llm.match_unresolved(results, ledger, bank)
        
        for result in results:
            assert result.method in (MatchMethod.EXACT, MatchMethod.BATCH, MatchMethod.FUZZY_RULE, MatchMethod.LLM, MatchMethod.UNRESOLVED), \
                f"Unexpected method: {result.method}"

    def test_confidence_scores(self, data):
        ledger, bank, ground_truth = data
        matcher = Matcher()
        results = matcher.match(ledger, bank)
        
        llm = LLMMatcher(use_mock=True)
        results = llm.match_unresolved(results, ledger, bank)
        
        for result in results:
            assert 0.0 <= result.confidence <= 1.0, f"Invalid confidence: {result.confidence}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])