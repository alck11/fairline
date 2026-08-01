# ADR-0022 — roadmap.md's v0.3 econ line would hit the same wall as MRAIN-1/HURSEAS-1: 14 release-events total, not enough to gate

- **Status:** **Retracted 2026-07-31 by [ADR-0025](0025-flb1-gate-retested-on-full-history-stable-no-go.md)** — econ series were re-tested against `/historical/markets`: 145 gate-band families (10x this ADR's 14-event total), net ROI +0.20%, t=0.23. The verdict changes from "underpowered, can't tell" to **"powered, and there is no edge"** — a decisive NO-GO, not an open question. Do not use this ADR's "can't tell yet" framing; use ADR-0025's.
- **Date:** 2026-07-28
- **Warns against:** `docs/product/roadmap.md` v0.3 "Econ `prob_fn`" (6–12
  dev-days, "gated on its own calibration study") before it is started, using
  data already on hand from [ADR-0016](0016-wp0-history-ceiling-is-a-venue-property.md)/
  [ADR-0019](0019-flb1-decile-study-real-but-sub-gate-edge-no-go.md) — no new
  fetching needed.

## Decision

**Do not start v0.3 as currently scoped.** A WP-7-style calibration gate needs
independent *release events*, not raw market count. Counted directly: **14
distinct release-events total, across all four reachable econ series
combined, in the entire ~68-day retrievable window** —
KXCPIYOY 2, KXPAYROLLS 2, KXJOBLESSCLAIMS 9, KXFEDDECISION 1. WP-7's own
weather gate ([ADR-0014](0014-wp7-gate-result-no-go.md)) used **68 dates for
one series alone** and still needed a same-day follow-up robustness check
before its NO-GO was trusted. Fourteen events, split across four
structurally-different economic indicators that can't legitimately be pooled
into one homogeneous study, is the same underpowered shape ADR-0016 already
retired MRAIN-1 and HURSEAS-1 for — monthly-or-slower release cadence
colliding with Kalshi's history ceiling.

## Why this wasn't obvious from the roadmap alone

`roadmap.md` estimates v0.3 at 6–12 dev-days and gates it on "its own
calibration study," mirroring Track B's structure — reasonable when written
(2026-07-17, before this session's WP-0 findings existed). The 184
resolved-market count ADR-0016 already reported for these four series looked
plausible for a study at a glance; it's the **release-event** count, not the
market count, that determines statistical power (each release spawns ~2–20
strike-ladder markets, same structure as weather's daily ladders spawning
~12 strikes per date) — and that number is small enough to see the problem
immediately once counted directly, which took reusing data already fetched
for [ADR-0019](0019-flb1-decile-study-real-but-sub-gate-edge-no-go.md)/
[ADR-0021](0021-weather-tail-correlation-mixed-evidence-not-decisive.md),
not a new API pull.

## Consequence

If econ directional EV is still wanted, it needs a different design than the
one in `roadmap.md` — not a WP-7-style historical Brier-skill gate (there
isn't enough history to run one credibly), but something that doesn't depend
on Kalshi's settled-market retention: a live/forward calibration check
(accumulate release-events going forward, the same forward-paper mechanism
[ADR-0016](0016-wp0-history-ceiling-is-a-venue-property.md) already proposed
for FLB-1), or a model built and validated primarily on the underlying
economic data series themselves (CPI/payrolls/claims history is long and
free from BLS/FRED, unlike Kalshi's own market history) with Kalshi prices
used only at inference time, not for backtesting the edge claim.

This does not reopen or close anything already decided — WP-7/weather stays
NO-GO, FLB-1 stays a real-but-small-and-risky candidate pending the user's
forward-paper-or-stop decision. It adds one fact to that decision: **the
next item already sitting in the roadmap has the same problem, so choosing
"stop the weather/FLB-1 line" does not leave a ready-to-build alternative
sitting in v0.3** — that line needs redesign work of its own before it's
buildable, not just a green light.
