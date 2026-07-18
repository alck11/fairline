# Directional EV: from paper-only experiment to the MVP's primary strategy

> **Updated 2026-07-17 for the Kalshi pivot.** Directional EV was originally the
> *third, experimental, paper-only* strategy behind arbitrage and copy-trading.
> After the venue pivot it is **the MVP's primary — and only active — strategy**
> (arb and copy-trade are parked). The original boundaries below still hold, with
> **one reconciled**: the probability model is no longer *purely* injected from
> outside — a weather `prob_fn` is now built in-repo. It is still consumed through
> an injection *contract* (ADR-0009), and it is still **paper-first (ADR-0001)**.
> The original text is preserved below the update for the record.

## What changed, and what did not

**Promoted:** directional EV is the strategy fairline now exists to validate:
model probability vs. Kalshi's weather/economics price, longer-horizon,
non-latency, and — uniquely — **backtestable** on free Kalshi history (research
Parts 6–7). "Experimental, must earn co-equal status" is retired; it is the lead.

**Reconciled boundary — the model is partly built here.** The original rule was
"the probability model is injected, never built here." The MVP deliberately builds
a **weather `prob_fn` v1** in-repo (WP-8), because a real edge verdict needs a real
model, not an external black box. This is reconciled, not abandoned, by keeping the
*interface* injected:

- The `prob_fn` is still a **parameter**, defined by a stable contract
  (ADR-0009: `prob_fn(market, as_of) -> p ∈ [0,1]`, point-in-time). `ev_detector`
  and the harness depend on the contract, never on a specific model.
- A **placeholder** (`MidpriceProbFn`) implements the same contract and is what the
  whole pipeline is proven against *before* the real model exists — and doubles as
  the US-6 always-market-price baseline.
- Whether the real model is built in-repo, sourced, or swapped later is now an
  implementation detail behind the contract. "Injected" now means "supplied through
  the contract," not "authored elsewhere."

**Still binding (unchanged):**
- **Paper-first.** No live execution in the MVP; `place_live` raises (ADR-0001).
  The harness runs the strategy over *history* (a backtest), and forward paper is a
  gated post-MVP step before any live IBKR path.
- **A directional signal is not an Opportunity.** `DirectionalSignal` stays out of
  `arb_opportunity`; it now persists to its own `directional_signal` table
  (ADR-0010) — the dedicated audit table the original ADR flagged as follow-up.
- **Same risk gates.** Execution goes through the one `Engine` (notional, exposure,
  daily-loss kill switch) via an additive `Engine.execute_signal`.
- **Longer-horizon target.** Weather/econ, not latency-competitive 5-minute crypto.
- **Point-in-time honesty.** The model may read only pre-`as_of` data; enforced by
  the US-7 leakage audit (inherits ADR-0003's leakage discipline).

## Consequences

- The `prob_fn` interface contract (ADR-0009) becomes load-bearing: both build
  tracks (plumbing and weather model) depend on it, so it is defined in week 1.
- Fractional-Kelly-by-default and depth-aware sizing (built in `ev_detector`) stay
  — full Kelly on an unproven model is how bankrolls die.
- The honest-motivation caveat from the original (viral bot-profit threads are
  unverifiable, survivorship-biased) is *why* the MVP's deliverable is a
  fee-aware, leakage-audited, baseline-relative **verdict**, not a live bot.

---

## Original decision (preserved — pre-pivot context)

Fairline adds a third strategy alongside arbitrage and copy-trading:
**directional EV** — backing one side of a market when an injected probability
model disagrees with the price (`src/ev_detector.py`). Unlike the other two it
is explicitly **experimental**: paper-only, and not co-equal until it proves an
edge the same way everything else must (ADR-0001).

Honesty about the motivation: the prompt was a set of viral bot-profit threads
(BTC 5-minute bots, a weather bot) whose PnL claims are unverifiable and
survivorship-biased — the exact failure mode ADR-0003 exists to avoid. We are
adopting the *shape* of the strategy (model probability vs. market price on
short-horizon/niche categories), not the evidence.

Boundaries that keep the experiment honest:

- **The probability model is injected, never built here.** `prob_fn` is a
  parameter, like the matcher's `embedder`/`confirmer`. Fairline owns the EV
  math, depth-aware sizing, and fractional-Kelly cap (quarter-Kelly default —
  full Kelly on an unproven model is how bankrolls die).
- **A directional signal is not an Opportunity.** The vocabulary and audit
  trail stay separate: `DirectionalSignal`, never written to `arb_opportunity`.
  A dedicated `signal` table is deliberate follow-up work, not done yet.
- **Same risk gates.** Execution goes through the one `Engine` — notional,
  exposure, daily-loss kill switch — like every other strategy.
- Latency-competitive markets (5-minute crypto) are a poor fit for our
  snapshot-based stack; longer-horizon mispricings (weather-style) are the
  intended target.
