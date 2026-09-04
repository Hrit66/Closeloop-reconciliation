import json
import os
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from models import LedgerRow, BankRow, MatchResult, MatchMethod
from config import CONFIG

log = logging.getLogger(__name__)


@dataclass
class LLMCandidate:
    payment_id: str
    net_amount: float
    bank: Optional[str]
    method: str
    settlement_date: str
    description: str
    created_at: str
    bank_transaction_id: Optional[str]

    @classmethod
    def from_ledger(cls, row: LedgerRow) -> "LLMCandidate":
        return cls(
            payment_id=row.id,
            net_amount=row.net_amount,
            bank=row.bank,
            method=row.method,
            settlement_date=row.settlement_date.isoformat() if row.settlement_date else "",
            description=row.description,
            created_at=row.created_at.isoformat() if row.created_at else "",
            bank_transaction_id=row.bank_transaction_id
        )


@dataclass
class LLMContext:
    settlement_id: str
    settlement_amount: float
    settlement_date: str
    settlement_bank: Optional[str]
    settlement_description: str
    candidates: List[LLMCandidate]
    valid_combinations: List[List[str]]

    def to_prompt(self) -> str:
        combo_str = "\n".join([
            f"  Option {i+1}: {', '.join(combo)} (sum = {sum(self._get_amount(c) for c in combo):.2f})"
            for i, combo in enumerate(self.valid_combinations[:10])
        ])
        
        cand_str = "\n".join([
            f"  - {c.payment_id}: ₹{c.net_amount:,.2f} | {c.bank or 'N/A':8s} | {c.method:10s} | settle: {c.settlement_date[:10]} | {c.description}"
            for c in self.candidates
        ])
        
        return f"""You are a reconciliation expert. Match this bank settlement to the correct Razorpay payments.

BANK SETTLEMENT:
  ID: {self.settlement_id}
  Amount: ₹{self.settlement_amount:,.2f}
  Date: {self.settlement_date[:10]}
  Bank: {self.settlement_bank or 'N/A'}
  Description: {self.settlement_description}

CANDIDATE PAYMENTS ({len(self.candidates)} available):
{cand_str}

VALID COMBINATIONS THAT SUM TO TARGET (pre-computed):
{combo_str}

TASK: Select the MOST LIKELY combination. Consider:
1. Bank name match (settlement bank vs payment bank)
2. Settlement date proximity
3. Transaction ID patterns in descriptions
4. Payment method consistency
5. Amount rounding patterns

Respond with JSON only:
{{
  "selected_combination_index": 0,
  "confidence": 0.9,
  "reasoning": "Brief explanation"
}}"""

    def _get_amount(self, payment_id: str) -> float:
        for c in self.candidates:
            if c.payment_id == payment_id:
                return c.net_amount
        return 0.0


class LLMMatcher:
    def __init__(self, config: CONFIG = CONFIG, use_mock: bool = False):
        self.config = config
        
        # Check for API keys in priority order
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.nemotron_key = os.getenv("NEMOTRON_API_KEY")
        self.nemotron_base_url = os.getenv("NEMOTRON_BASE_URL", "https://integrate.api.nvidia.com/v1")
        
        has_key = bool(self.openai_key or self.anthropic_key or self.openrouter_key or self.nemotron_key)
        self.use_mock = use_mock or not has_key
        
        if self.nemotron_key:
            self.api_key = self.nemotron_key
            self.provider = "nemotron"
        elif self.openrouter_key:
            self.api_key = self.openrouter_key
            self.provider = "openrouter"
        elif self.anthropic_key:
            self.api_key = self.anthropic_key
            self.provider = "anthropic"
        elif self.openai_key:
            self.api_key = self.openai_key
            self.provider = "openai"
        else:
            self.api_key = ""
            self.provider = "mock"
        
        if self.use_mock:
            log.info("LLMMatcher running in mock mode (no API key)")
        else:
            log.info(f"LLMMatcher using {self.provider} provider")

    def match_unresolved(self, results: List[MatchResult], ledger: List[LedgerRow], bank: List[BankRow]) -> List[MatchResult]:
        if not self.use_mock and not self.api_key:
            print("No LLM API key found. Use mock mode or set OPENAI_API_KEY/ANTHROPIC_API_KEY.")
            return results

        bank_map = {r.id: r for r in bank}
        captured = [r for r in ledger if r.status == "captured"]
        
        # LLM only processes LOW-CONFIDENCE results:
        # - UNRESOLVED
        # - FUZZY_RULE (inherently ambiguous)
        # - BATCH with confidence < 0.7
        # High-confidence BATCH (>=0.7) and EXACT are kept as-is
        exact_results = [r for r in results if r.method == MatchMethod.EXACT]
        high_conf_batch = [r for r in results if r.method == MatchMethod.BATCH and r.confidence >= 0.7]
        needs_llm = [r for r in results if r.method == MatchMethod.UNRESOLVED or r.method == MatchMethod.FUZZY_RULE or (r.method == MatchMethod.BATCH and r.confidence < 0.7)]
        
        log.info(f"LLM reviewing {len(needs_llm)} settlements (unresolved + fuzzy + low-conf batch), keeping {len(exact_results)} EXACT + {len(high_conf_batch)} high-conf BATCH")
        
        # Used payments from EXACT and high-conf BATCH
        used_payments = {pid for r in exact_results + high_conf_batch for pid in r.matched_payment_ids}
        
        # Track which settlements need LLM and their valid combos
        contexts = []
        no_combo_settlements = []  # Settlements with no valid combos
        
        for result in needs_llm:
            bank_row = bank_map.get(result.settlement_id)
            if not bank_row:
                continue
            
            available = [r for r in captured if r.id not in used_payments]
            valid_combos = self._find_valid_combinations(available, bank_row.net_amount, max_results=15)
            
            if not valid_combos:
                no_combo_settlements.append(result.settlement_id)
                continue
            
            contexts.append(LLMContext(
                settlement_id=bank_row.id,
                settlement_amount=bank_row.net_amount,
                settlement_date=bank_row.settlement_date.isoformat() if bank_row.settlement_date else "",
                settlement_bank=bank_row.bank,
                settlement_description=bank_row.description,
                candidates=[LLMCandidate.from_ledger(r) for r in available],
                valid_combinations=valid_combos[:10]
            ))
        
        # Global assignment for LLM contexts
        selections = self._global_assign(contexts)
        
        # Build final results: EXACT + high-conf BATCH + LLM assignments + unresolved
        new_results = list(exact_results) + list(high_conf_batch)
        used_payments = {pid for r in exact_results + high_conf_batch for pid in r.matched_payment_ids}
        
        for ctx in contexts:
            selection = selections.get(ctx.settlement_id)
            if selection:
                selected = selection
                if any(pid in used_payments for pid in selected):
                    log.warning(f"LLM selection for {ctx.settlement_id} conflicts with existing assignments")
                    new_results.append(MatchResult(
                        settlement_id=ctx.settlement_id,
                        matched_payment_ids=[],
                        method=MatchMethod.UNRESOLVED,
                        confidence=0.0,
                        reasoning="LLM conflict with other assignments"
                    ))
                else:
                    for pid in selected:
                        used_payments.add(pid)
                    new_results.append(MatchResult(
                        settlement_id=ctx.settlement_id,
                        matched_payment_ids=selected,
                        method=MatchMethod.LLM,
                        confidence=0.85,
                        reasoning="LLM global assignment"
                    ))
            else:
                new_results.append(MatchResult(
                    settlement_id=ctx.settlement_id,
                    matched_payment_ids=[],
                    method=MatchMethod.UNRESOLVED,
                    confidence=0.0,
                    reasoning="LLM could not find valid non-conflicting assignment"
                ))
        
        # Add settlements with no valid combos as UNRESOLVED
        for sid in no_combo_settlements:
            new_results.append(MatchResult(
                settlement_id=sid,
                matched_payment_ids=[],
                method=MatchMethod.UNRESOLVED,
                confidence=0.0,
                reasoning="No valid payment combinations found"
            ))
        
        return new_results

    def _global_assign(self, contexts: List[LLMContext]) -> Dict[str, List[str]]:
        """Greedy global assignment: sort by confidence, assign best non-conflicting."""
        # Score all options for all contexts
        all_options = []
        for ctx in contexts:
            for i, combo in enumerate(ctx.valid_combinations):
                score, reasoning = self._score_combination(ctx, combo)
                all_options.append({
                    "settlement_id": ctx.settlement_id,
                    "combo": combo,
                    "score": score,
                    "reasoning": reasoning
                })
        
        # Sort by score descending
        all_options.sort(key=lambda x: x["score"], reverse=True)
        
        # Greedy assignment
        used = set()
        assignments = {}
        
        for opt in all_options:
            sid = opt["settlement_id"]
            if sid in assignments:
                continue  # Already assigned best option
            if any(pid in used for pid in opt["combo"]):
                continue  # Payment conflict
            assignments[sid] = opt["combo"]
            used.update(opt["combo"])
        
        return assignments

    def _get_all_options(self, contexts: List[LLMContext]) -> List[Dict]:
        """Get all scored options for all contexts (helper for threshold checking)."""
        all_options = []
        for ctx in contexts:
            for i, combo in enumerate(ctx.valid_combinations):
                score, reasoning = self._score_combination(ctx, combo)
                all_options.append({
                    "settlement_id": ctx.settlement_id,
                    "combo": combo,
                    "score": score,
                    "reasoning": reasoning
                })
        return all_options

    def _find_valid_combinations(self, candidates: List[LedgerRow], target: float, max_results: int = 20) -> List[List[str]]:
        from itertools import combinations
        
        valid = []
        filtered = [c for c in candidates if c.net_amount <= target * 3]
        
        for r in range(2, min(5, len(filtered) + 1)):
            for combo in combinations(filtered, r):
                total = sum(c.net_amount for c in combo)
                if abs(total - target) <= self.config.AMOUNT_TOLERANCE * 2:
                    valid.append([c.id for c in combo])
                    if len(valid) >= max_results:
                        return valid
        return valid

    def _score_combination(self, context: LLMContext, combo: List[str]) -> tuple:
        score = 0.0
        reasons = []
        
        def get_amount(pid: str) -> float:
            for c in context.candidates:
                if c.payment_id == pid:
                    return c.net_amount
            return 0.0
        
        # 1. Bank match (strong signal)
        if context.settlement_bank and context.settlement_bank not in ("UNKNOWN", "MULTI", None):
            bank_matches = sum(1 for pid in combo 
                             if any(c.payment_id == pid and c.bank == context.settlement_bank 
                                   for c in context.candidates))
            if bank_matches == len(combo):
                score += 3.0
                reasons.append(f"all {len(combo)} payments match bank {context.settlement_bank}")
            elif bank_matches > 0:
                score += 1.0 * bank_matches / len(combo)
                reasons.append(f"{bank_matches}/{len(combo)} payments match bank")
        
        # 2. Date proximity
        date_scores = []
        for pid in combo:
            cand = next((c for c in context.candidates if c.payment_id == pid), None)
            if cand and cand.settlement_date:
                try:
                    pay_date = cand.settlement_date[:10]
                    settle_date = context.settlement_date[:10]
                    diff = abs((pd_to_datetime(pay_date) - pd_to_datetime(settle_date)).days)
                    if diff <= 1:
                        date_scores.append(1.0)
                    elif diff <= 3:
                        date_scores.append(0.5)
                    else:
                        date_scores.append(0.1)
                except:
                    date_scores.append(0.1)
        if date_scores:
            avg_date = sum(date_scores) / len(date_scores)
            score += avg_date * 2.0
            reasons.append(f"avg date proximity: {avg_date:.1f}")
        
        # 3. Transaction ID pattern in description
        desc = context.settlement_description.upper()
        txn_matches = 0
        for pid in combo:
            cand = next((c for c in context.candidates if c.payment_id == pid), None)
            if cand and cand.bank_transaction_id:
                btid = str(cand.bank_transaction_id)
                if btid != "nan" and len(btid) >= 8 and btid[:8] in desc:
                    txn_matches += 1
        if txn_matches:
            score += txn_matches * 0.5
            reasons.append(f"{txn_matches} TXN ID matches in description")
        
        # 4. Method consistency (strong signal)
        methods = set()
        for pid in combo:
            cand = next((c for c in context.candidates if c.payment_id == pid), None)
            if cand:
                methods.add(cand.method)
        if len(methods) == 1:
            score += 2.0
            reasons.append(f"consistent method: {list(methods)[0]}")
        elif len(methods) == 2:
            score += 0.5
            reasons.append(f"2 methods: {methods}")
        
        # 5. Smaller combination strongly preferred (Occam's razor)
        size_penalty = (len(combo) - 2) * 1.0
        score -= size_penalty
        reasons.append(f"size penalty: {size_penalty}")
        
        # 6. Amount closeness
        total = sum(get_amount(pid) for pid in combo)
        diff = abs(total - context.settlement_amount)
        if diff <= 0.1:
            score += 1.0
            reasons.append("exact amount")
        elif diff <= 1.0:
            score += 0.5
            reasons.append(f"near-exact amount (diff {diff:.2f})")
        
        return score, "; ".join(reasons) if reasons else "heuristic scoring"

    def _call_llm(self, context: LLMContext) -> Optional[Dict]:
        prompt = context.to_prompt()
        
        try:
            if self.provider == "openai":
                return self._call_openai(prompt)
            elif self.provider == "anthropic":
                return self._call_anthropic(prompt)
            elif self.provider == "openrouter":
                return self._call_openrouter(prompt)
            elif self.provider == "nemotron":
                return self._call_nemotron(prompt)
        except Exception as e:
            log.warning(f"LLM call failed: {e}")
            return None
        
        return None

    def _call_openai(self, prompt: str) -> Optional[Dict]:
        import requests
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are a financial reconciliation expert. Output only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 300
            },
            timeout=30
        )
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        log.warning(f"OpenAI API error: {response.status_code} {response.text}")
        return None

    def _call_anthropic(self, prompt: str) -> Optional[Dict]:
        import requests
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 300,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        if response.status_code == 200:
            content = response.json()["content"][0]["text"]
            return json.loads(content)
        log.warning(f"Anthropic API error: {response.status_code} {response.text}")
        return None

    def _call_openrouter(self, prompt: str) -> Optional[Dict]:
        import requests
        base_url = os.getenv("ANTHROPIC_BASE_URL", "https://openrouter.ai/api/v1")
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/closeLoop",
                "X-Title": "CloseLoop Reconciliation"
            },
            json={
                "model": "anthropic/claude-3-haiku",
                "messages": [
                    {"role": "system", "content": "You are a financial reconciliation expert. Output only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 300
            },
            timeout=30
        )
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        log.warning(f"OpenRouter API error: {response.status_code} {response.text}")
        return None

    def _call_nemotron(self, prompt: str) -> Optional[Dict]:
        import requests
        response = requests.post(
            f"{self.nemotron_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "nvidia/nemotron-3-ultra-550b-a55b",
                "messages": [
                    {"role": "system", "content": "You are a financial reconciliation expert. Output only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 300
            },
            timeout=30
        )
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        log.warning(f"Nemotron API error: {response.status_code} {response.text}")
        return None


def pd_to_datetime(val):
    import pandas as pd
    return pd.to_datetime(val)