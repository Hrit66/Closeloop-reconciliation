from datetime import timedelta
from itertools import combinations
from typing import List, Dict, Set, Tuple, Optional
from models import LedgerRow, BankRow, MatchResult, MatchMethod
from config import CONFIG


class Matcher:
    def __init__(self, config: CONFIG = CONFIG):
        self.config = config
        self.used_payments: Set[str] = set()
        self.results: List[MatchResult] = []

    def match(self, ledger: List[LedgerRow], bank: List[BankRow]) -> List[MatchResult]:
        self.used_payments = set()
        self.results = []

        captured = [p for p in ledger if p.status == "captured" and p.id not in self.used_payments]

        bank_sorted = sorted(bank, key=lambda b: b.settlement_date)

        for bank_row in bank_sorted:
            if bank_row.method == "batch_settlement":
                match = self._match_batch(bank_row, captured)
            else:
                # FIX: Tier 1 now falls back to Tier 3 fuzzy single-payment
                # match before giving up. Previously _match_fuzzy existed
                # but was never called.
                match = self._match_exact(bank_row, captured)
                if match is None:
                    match = self._match_fuzzy(bank_row, captured)

            if match:
                self.results.append(match)
                for pid in match.matched_payment_ids:
                    self.used_payments.add(pid)
                captured = [p for p in captured if p.id not in self.used_payments]
            else:
                self.results.append(MatchResult(
                    settlement_id=bank_row.id,
                    matched_payment_ids=[],
                    method=MatchMethod.UNRESOLVED,
                    confidence=0.0,
                    reasoning="No match found in any tier"
                ))

        return self.results

    def _match_exact(self, bank_row: BankRow, candidates: List[LedgerRow]) -> Optional[MatchResult]:
        """
        Tier 1: exact 1-to-1 match.

        FIX: previously returned on the FIRST candidate satisfying amount+date,
        which silently produces a wrong answer whenever two ledger rows both
        qualify. Now collects ALL qualifying candidates and only claims a
        match when there is exactly one.
        """
        qualifying = [
            p for p in candidates
            if p.id not in self.used_payments
            and self._amount_matches(p.net_amount, bank_row.net_amount)
            and self._date_matches(p.settlement_date, bank_row.settlement_date)
        ]

        if len(qualifying) == 1:
            payment = qualifying[0]
            return MatchResult(
                settlement_id=bank_row.id,
                matched_payment_ids=[payment.id],
                method=MatchMethod.EXACT,
                confidence=0.95,
                reasoning=(
                    f"Exact amount match ({payment.net_amount} == {bank_row.net_amount}) "
                    f"within {self.config.AMOUNT_TOLERANCE} tolerance, date within lag window"
                )
            )
        # 0 qualifying -> no match. 2+ qualifying -> ambiguous; don't guess,
        # let it fall through to fuzzy/LLM tiers.
        return None

    def _match_batch(self, bank_row: BankRow, candidates: List[LedgerRow]) -> Optional[MatchResult]:
        available = [p for p in candidates if p.id not in self.used_payments]

        if bank_row.bank and bank_row.bank not in ("UNKNOWN", "MULTI"):
            available = [p for p in available if p.bank == bank_row.bank]

        available = [p for p in available if self._date_matches_batch(p.settlement_date, bank_row.settlement_date)]

        max_single = bank_row.net_amount * self.config.AMOUNT_PRE_FILTER_RATIO
        available = [p for p in available if p.net_amount <= max_single]

        if len(available) < 2:
            return self._match_batch_fuzzy(bank_row, candidates)

        target = bank_row.net_amount
        best_match, is_ambiguous, num_valid = self._find_best_combination(available, target, bank_row)

        cross_bank_ambiguous = bank_row.bank in ("MULTI", "UNKNOWN", None)
        if cross_bank_ambiguous:
            is_ambiguous = True

        if best_match:
            payment_ids = [p.id for p in best_match]
            total = sum(p.net_amount for p in best_match)
            diff = abs(total - target)
            method = MatchMethod.BATCH if diff <= self.config.AMOUNT_TOLERANCE else MatchMethod.FUZZY_RULE
            if is_ambiguous:
                confidence = 0.4
                method = MatchMethod.FUZZY_RULE
            else:
                confidence = 0.9 if method == MatchMethod.BATCH else 0.7
            reasoning = f"Batch match: {len(best_match)} payments sum to {total:.2f} (target {target:.2f}, diff {diff:.2f})"
            if is_ambiguous:
                reason = "multiple valid combinations" if num_valid > 1 else "cross-bank settlement (no bank filter)"
                reasoning += f" [AMBIGUOUS: {reason}]"
            return MatchResult(
                settlement_id=bank_row.id,
                matched_payment_ids=payment_ids,
                method=method,
                confidence=confidence,
                reasoning=reasoning
            )

        return self._match_batch_fuzzy(bank_row, candidates)

    def _find_best_combination(self, available: List[LedgerRow], target: float, bank_row: BankRow) -> Tuple[Optional[Tuple[LedgerRow, ...]], bool, int]:
        """
        FIX: this method was previously defined OUTSIDE the class (missing
        indentation) -- self._find_best_combination(...) would have failed
        at runtime. Now correctly indented as an instance method.
        """
        best_match = None
        best_score = -1
        combo_count = 0
        valid_combos = []

        for r in range(2, min(self.config.MAX_BATCH_SIZE + 1, len(available) + 1)):
            for combo in combinations(available, r):
                combo_count += 1
                if combo_count > self.config.MAX_COMBINATIONS:
                    break

                total = sum(p.net_amount for p in combo)
                diff = abs(total - target)

                if diff <= self.config.AMOUNT_TOLERANCE * 5:
                    score = self._score_combination(combo, bank_row, diff)
                    if score > best_score:
                        best_score = score
                        best_match = combo

                if diff <= self.config.AMOUNT_TOLERANCE:
                    valid_combos.append(combo)

            if combo_count > self.config.MAX_COMBINATIONS:
                break

        is_ambiguous = len(valid_combos) > 1

        if best_match and not is_ambiguous:
            return best_match, False, len(valid_combos)
        elif best_match and is_ambiguous:
            return best_match, True, len(valid_combos)
        else:
            return None, False, len(valid_combos)

    def _score_combination(self, combo: Tuple[LedgerRow, ...], bank_row: BankRow, amount_diff: float) -> float:
        score = 1.0
        score -= amount_diff / max(bank_row.net_amount, 1) * 10

        date_diffs = [abs((bank_row.settlement_date - p.settlement_date).days) for p in combo]
        avg_date_diff = sum(date_diffs) / len(date_diffs)
        score -= avg_date_diff * 0.05

        if bank_row.bank and bank_row.bank != "UNKNOWN":
            same_bank = sum(1 for p in combo if p.bank == bank_row.bank)
            score += same_bank / len(combo) * 0.2

        score -= len(combo) * 0.02
        return max(0, score)

    def _match_batch_fuzzy(self, bank_row: BankRow, candidates: List[LedgerRow]) -> Optional[MatchResult]:
        available = [p for p in candidates if p.id not in self.used_payments]

        if bank_row.bank and bank_row.bank not in ("UNKNOWN", "MULTI"):
            available = [p for p in available if p.bank == bank_row.bank]

        available = [p for p in available if self._date_matches_batch(p.settlement_date, bank_row.settlement_date, fuzzy=True)]

        max_single = bank_row.net_amount * self.config.AMOUNT_PRE_FILTER_RATIO
        available = [p for p in available if p.net_amount <= max_single]

        if len(available) < 2:
            return None

        target = bank_row.net_amount
        # FIX: unpacks 3 values now, not 2 -- previously raised ValueError.
        best_match, is_ambiguous, num_valid = self._find_best_combination(available, target, bank_row)

        if best_match:
            payment_ids = [p.id for p in best_match]
            total = sum(p.net_amount for p in best_match)
            diff = abs(total - target)
            confidence = 0.6 if not is_ambiguous else 0.4
            reasoning = f"Fuzzy batch match: {len(best_match)} payments sum to {total:.2f} (target {target:.2f}, diff {diff:.2f})"
            if is_ambiguous:
                reasoning += f" [AMBIGUOUS: {num_valid} valid combinations]"
            return MatchResult(
                settlement_id=bank_row.id,
                matched_payment_ids=payment_ids,
                method=MatchMethod.FUZZY_RULE,
                confidence=confidence,
                reasoning=reasoning
            )

        return None

    def _match_fuzzy(self, bank_row: BankRow, candidates: List[LedgerRow]) -> Optional[MatchResult]:
        """
        Tier 3: single-payment fuzzy fallback.

        FIX: previously dead code, never called from match(). Now wired in
        as the fallback when _match_exact returns None for a non-batch row.
        Applies the same uniqueness discipline: 2+ candidates = don't guess.
        """
        available = [p for p in candidates if p.id not in self.used_payments]

        qualifying = [
            p for p in available
            if self._date_matches(p.settlement_date, bank_row.settlement_date, fuzzy=True)
            and self._amount_matches(p.net_amount, bank_row.net_amount)
        ]

        if len(qualifying) == 1:
            payment = qualifying[0]
            return MatchResult(
                settlement_id=bank_row.id,
                matched_payment_ids=[payment.id],
                method=MatchMethod.FUZZY_RULE,
                confidence=0.6,
                reasoning=f"Fuzzy match: amount matches, date within extended window ({self.config.FUZZY_LAG_DAYS} days)"
            )
        return None

    def _amount_matches(self, amount1: float, amount2: float) -> bool:
        return abs(amount1 - amount2) <= self.config.AMOUNT_TOLERANCE

    def _date_matches(self, pay_date, bank_date, fuzzy: bool = False) -> bool:
        max_lag = self.config.FUZZY_LAG_DAYS if fuzzy else self.config.MAX_LAG_DAYS
        min_lag = self.config.MIN_LAG_DAYS
        diff = (bank_date - pay_date).days
        return min_lag <= diff <= max_lag

    def _date_matches_batch(self, pay_date, bank_date, fuzzy: bool = False) -> bool:
        max_lag = self.config.FUZZY_LAG_DAYS if fuzzy else self.config.MAX_LAG_DAYS * 2
        min_lag = 0
        diff = (bank_date - pay_date).days
        return min_lag <= diff <= max_lag