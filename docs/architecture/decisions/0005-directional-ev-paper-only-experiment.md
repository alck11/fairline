# Directional EV is an experimental, paper-only third strategy

Fairline adds a third strategy alongside arbitrage and copy-trading:
**directional EV** — backing one side of a market when an injected probability
model disagrees with the price (`src/ev_detector.py`). Unlike the other two it
is explicitly **experimental**: paper-only, and not co-equal until it proves an
edge the same way everything else must (ADR-0001).

Honesty about the motivation: the prompt was a set of viral bot-profit threads
(BTC 5-minute bots, a weather bot) whose PnL claims are unverifiable and
survivorship-biased — the exact failure mode ADR-0003 exists to avoid. We are
adopting the *shape* of the strategy (model probability vs. market price on
short-horizon/niche categories), not the evidence. See
`docs/research/2026-07-11-polymarket-cli-and-ev-references.md` for the source
assessment.

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
