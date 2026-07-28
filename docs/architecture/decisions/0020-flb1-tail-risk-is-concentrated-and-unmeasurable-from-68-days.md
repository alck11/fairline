# ADR-0020 — FLB-1's losses are concentrated in one thin series and one weather event; the real blocker is unmeasured tail risk, not the ROI threshold

- **Status:** Accepted
- **Date:** 2026-07-28
- **Follows:** [ADR-0019](0019-flb1-decile-study-real-but-sub-gate-edge-no-go.md) —
  answers the user's direct pushback on that ADR's verdict: *"we cannot trade
  on 0.88 ROI?"*

## Decision

**The +1.5% pre-registered threshold was the wrong lens to argue this on, and
arguing on turnover/annualization instead doesn't rescue FLB-1 either — it
surfaces a sharper, unresolved problem: every observed loss in the sample is
concentrated in one thin series and, more troublingly, two of the three land
on the *same calendar date*.** That is the signature of a correlated weather
event, not independent bad luck, and 67 days of one summer cannot contain
enough of those events to price the risk. **Still NO-GO — now for a tail-risk
reason a backtest of this length cannot resolve, not a magnitude reason.**

## Why the 1.5% bar doesn't settle the question either way

ADR-0017/2026-07-25's `+1.5%` gate was set with slow, once-or-twice-a-year
"emotional" markets in mind, where a trade's annualized return ≈ its one-shot
return. Weather ladders resolve **daily**, across 6 cities in parallel — a
flat per-trade percentage is the wrong comparison for a strategy that can turn
capital over roughly weekly, and naive compounding of 0.88% at that frequency
produces very large numbers. **That naive math is also wrong, for a different
reason:** it assumes i.i.d. draws, and this bet's payoff shape — win ~1.1
cents on ~99.9% of trades, lose ~99 cents on the rest — is exactly the shape
where compounding assumptions break first. The full-Kelly fraction implied by
these odds for one isolated bet is **88.3% of bankroll**, which is itself the
signal that something about treating this as a simple percentage is wrong:
Kelly is telling you the win probability so dominates the arithmetic that
naive sizing logic wants to bet almost everything on a single 1-in-1000
tail event. No one trades that plan; the honest response is to distrust the
naive framing, not to execute it.

## The finding that actually matters

Recomputed the exact loss count in the `[0.90, 0.99)` weather bucket rather
than trusting the 0.125% implied by the ADR-0019 headline number:

**3 losses out of 2,407 observations, and all 3 are `KXLOWTBOS`:**

| series | family (date) | price | outcome |
|---|---|---|---|
| KXLOWTBOS | KXLOWTBOS-26JUN07 | 0.980 | loss |
| KXLOWTBOS | KXLOWTBOS-26MAY26 | 0.990 | loss |
| KXLOWTBOS | KXLOWTBOS-26MAY26 | 0.990 | loss |

**KXHIGHNY, KXHIGHLAX, KXHIGHCHI, KXHIGHMIA, KXHIGHDEN — ~2,005 observations
combined — have zero losses.** That is *why* their individual per-series
t-stats in ADR-0019 were absurd (22 to 177): a t-stat computed on zero
observed failures isn't measuring certainty, it's measuring "this sample never
contained the event that would break the estimate."

**Two of the three losses share a single date** (`KXLOWTBOS-26MAY26`) — two
different strikes on the same day's ladder, both busting together. That is the
structural signature of one weather anomaly hitting multiple buckets at once,
not two independent draws. Whether that specific anomaly could hit *multiple
cities* simultaneously on a worse day is exactly what this dataset cannot
show, because it never happened to in this window.

**Two readings, genuinely indistinguishable from what's in front of us:**

1. **Benign:** `KXLOWTBOS` is the thinnest series measured anywhere in this
   project (6/12 strikes quoted vs. 8–11/12 for the other five —
   2026-07-25 landscape doc), so its last-traded price before close may be a
   stale, wide-spread quote rather than a genuine near-99% probability. On
   this reading the five major cities are the real signal and Boston is noise.
2. **The one that should carry more weight:** the same-date clustering is
   exactly what a real forecast bust looks like, and the five "clean" cities
   simply weren't tested by one in this window. A rule-of-three check on their
   zero-loss record gives a plausible upper bound on the true loss rate of
   **~0.15%** — not meaningfully different from the 0.125% the whole pooled
   sample already shows. **Zero observed losses is not evidence of a lower
   true rate here; it's evidence the sample is too short to have seen one.**

Neither reading can be confirmed or ruled out with the data on hand. **Marking
this explicitly: Assuming a stale-liquidity artifact is at least as plausible
as a genuine tail signal — the correlation-check below is aimed at resolving
this, not confirming a foregone conclusion.**

## What this changes about "what's next"

Not a new fork — it sharpens the one already open. ADR-0016 framed the choice
as forward paper (6–12 months to a verdict) vs. stop, motivated by the
68-day retrieval ceiling. This finding gives that same conclusion a second,
independent reason: **the risk that determines whether this trade is
"small consistent edge" or "rare portfolio-wide loss" is defined by an event
type — a correlated, multi-city or multi-day forecast bust — that a 68-day
single-summer sample structurally cannot contain, no matter how the data is
sliced.** More history from the same API wouldn't fix this even if it were
available; it needs a different kind of check.

**One thing does not require waiting on forward paper**, and does not need any
new Kalshi history: whether major-city forecast errors actually co-move on bad
days is measurable *right now* from NOAA/IEM data this project already
ingested (WP-6, [ADR-0011](0011-weather-data-source-iem-first-ndfd-deferred.md)).
That is the immediate next step, run separately below rather than guessed at.
