# CloseLoop — AI Finance Controller (Reconciliation Agent)

Built for Razorpay Buildathon — Track 04: AI Finance Controller

CloseLoop closes one finance-ops loop: it reconciles a Razorpay payment
ledger against a bank settlement statement, resolving as many settlements
as it safely can with deterministic rules, escalating genuine ambiguity to
an LLM, and honestly flagging what it cannot resolve at all.

## Results (current run)

| Metric | Value |
|---|---|
| Total settlements | 14 |
| Resolved | 13 (92.86%) |
| Correct matches | 13 |
| Incorrect matches | **0** |
| Unresolved (honest exception) | 1 |
| Accuracy vs. ground truth | 92.86% |

Method breakdown (final):

| Method | Count | What it means |
|---|---|---|
| BATCH | 8 | Resolved deterministically — exact or subset-sum match within tolerance, single bank, unambiguous |
| LLM | 5 | Cross-bank / multi-candidate settlements resolved via LLM global assignment |
| UNRESOLVED | 1 | No valid combination of any ledger payment reconciles this amount — routed to human review |

**Zero confident wrong matches.** Every resolved settlement matches ground
truth exactly. The one unresolved case is reported honestly rather than
guessed.

## Architecture: tiered matching

```
Bank Settlement
      │
      ▼
 Tier 1: EXACT ──── 1:1 amount + date match, <1ms, deterministic
      │ no unique match
      ▼
 Tier 2: BATCH ──── subset-sum search (2-5 payments), 10-100ms
      │ no unique match / ambiguous
      ▼
 Tier 3: FUZZY_RULE ── widened date/amount windows, still rule-based
      │ still ambiguous
      ▼
 Tier 4: LLM ──── global reasoning over remaining candidates, 0.5-2s
      │
      ▼
 UNRESOLVED (if nothing fits) → exception queue, human review
```

**Why tiers, not "just use an LLM for everything":**
Cheap, deterministic rules run first because they're fast, free, and fully
auditable — an exact amount+date match is a fact, not a judgment call.
Every tier only claims a match when it is the *unique* candidate that
fits; if two or more combinations are equally valid, the tier declines to
guess and passes the settlement downstream. This means Tier 4 (the
expensive, probabilistic step) only ever sees settlements that genuinely
need semantic reasoning — in this run, that's 5 of 14, not all 14.

**Note on internal labels:** `FUZZY_RULE` is an intermediate confidence
label only. Any settlement scoring below the escalation threshold (0.7)
at Tier 2/3 is automatically escalated to Tier 4. It never appears as a
*final* method in the report — final output only shows `EXACT`, `BATCH`,
`LLM`, or `UNRESOLVED`.

## Data methodology

- **Real API data**: A portion of the ledger comes from actual Razorpay
  test-mode API calls — real `payment` objects with real fee/tax
  deduction, real bank codes, real transaction references — not invented
  from scratch.
- **Synthetic extension**: Additional payments were generated to reach a
  workable batch size (60 ledger rows), mirroring Razorpay's real response
  schema exactly (same fields, same fee/tax math, same ID formats).
- **Derived bank statement**: The bank settlement file is not independent
  synthetic data — it's *derived* from the ledger, the way a real bank
  statement is derived from real transactions: net amount (amount − fee −
  tax), 1-2 day settlement lag, truncated/garbled descriptions, and
  multi-payment batching (2-4 payments per credit) to simulate how banks
  report aggregated settlements rather than itemized ones.
- **Ground truth**: Every settlement's correct payment mapping was
  recorded at generation time (`data/ground_truth.csv`), since we
  constructed the batching ourselves. This lets us report *accuracy*
  against a known-correct answer, not just an internal match rate.

## The one exception: what it means

`BATCH_XBANK_6` — target amount (₹188,776.03) could not be reconciled by any tier,
including the LLM's global assignment pass. Verified: even against the full,
unconstrained 60-payment ledger, **no subset of any payments sums to this
amount within tolerance**. This is a genuine data gap — not an artifact of
sequential matching or greedy payment consumption. It is reported as
`UNRESOLVED`, not guessed. In a production system this would route to a
human reconciler with the reasoning trace attached, rather than being
silently marked "resolved" with a wrong answer.

## Production considerations

This project validates matching logic in **batch mode against known
ground truth** — the correct first step before any production deployment.
It intentionally does not attempt to be a live production system:

| Aspect | What we built | Production real-time |
|---|---|---|
| Purpose | Development/validation | Live operations |
| Data | Historical, static, labeled | Streaming, incomplete, noisy |
| Feedback | Ground truth available | No ground truth — that's the actual problem |
| Latency | Batch (seconds) | Sub-second to minutes |
| Accuracy metric | Precision/recall vs. truth | Operational: exception rate, SLA, auditability |
| LLM role | Validation / benchmarking | Decision support for exceptions |

In a live system, there is no ground truth to check matches against in
real time — the LLM's role shifts from *validating known-correct
structure* to *flagging genuine exceptions for human review*.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Runs without any API key (falls back to mock mode for the LLM tier). For
real LLM-backed Tier 4 matching, set `LLM_PROVIDER` and the corresponding
API key in a `.env` file (see `config.py` for supported providers).

## Tests

```bash
python -m pytest test_matcher.py -v
```

8/8 passing, including match rate, accuracy vs. ground truth, no-duplicate-
payment invariants, and confidence score validity.

## Known limitations

- **Schema-specific input format**: The loader currently expects ledger/bank
  CSVs in Razorpay's native schema (see `data/razorpay_ledger.csv` for the
  exact column format, including nested fields like
  `acquirer_data.bank_transaction_id`). Running against a third-party
  gateway's export today would require renaming columns to match. A
  lightweight column-mapping config (aliasing arbitrary source columns to
  our required fields before validation) would generalize this — scoped
  out here for time, but a small, well-contained addition on top of the
  existing `data_loader.py` validation step.
- Batch size in this run is 14 settlements / 60 payments — a stress test
  at larger scale is included (`stress_test.py`, `data/stress_*.csv`) to
  check throughput does not degrade at higher volume.
- Sequential/greedy payment consumption during matching means processing
  order could, in principle, affect which settlement claims a shared
  candidate first — the single UNRESOLVED case (`BATCH_XBANK_6`) was
  verified against the full unconstrained ledger and confirmed as a
  genuine data gap (no valid combo exists even on a fresh ledger), so this
  is not an artifact of order-dependence.
- LLM tier reasoning quality depends on the provider/model configured;
  mock mode is provided so the pipeline is fully runnable without any API
  key for demonstration purposes.
