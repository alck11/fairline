# Paper-first: live order placement is deliberately unimplemented and gated

Fairline ships with **no live order placement**. `Engine.place_live` raises by
design, and the entire stack — ingestion, detection, scoring, risk engine — runs
end-to-end on paper before a cent is at risk. The trade-off is time-to-market vs.
proving an edge risklessly, and we chose the latter: prediction-market edge is
small and slippage-sensitive, so a strategy that looks profitable at top-of-book
routinely isn't once you size into the book and pay fees. Paper mode is how you
find that out for free.

This is easy to mistake for unfinished work, so to be explicit: `place_live`
raising is **intended**, not a TODO to be "helpfully" completed. When live is
eventually implemented, two hardenings decided during design are mandatory:

- **The kill switch latches in live mode** — once the daily loss limit trips, a
  human must re-arm it. (Auto-reset at the UTC day roll is paper-only, so
  unattended replays aren't starved.) A kill switch that un-kills itself is a
  daily loss budget, not a kill switch.
- **Live cross-venue arbs may only execute against `verified` links** — a human
  must have confirmed the cross-venue match by reading both resolution rule-sets.
  Paper may trade unverified links; that is how the review queue is built without
  risk.

## Consequences

Live placement, when built, goes *inside* the existing risk gates (notional /
exposure / wallet caps, daily-loss kill switch, basket-consensus, atomic
all-legs-or-none arb handling) — never around them.
