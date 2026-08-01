# ADR-0023 — retraction: the "~68-day hard ceiling" was a query-family gap, not a venue property. `/historical/*` reaches back to 2021.

- **Status:** Accepted — **corrects ADR-0016 and ADR-0018's central conclusion**
- **Date:** 2026-07-28
- **Retracts:** the load-bearing claim of
  [ADR-0016](0016-wp0-history-ceiling-is-a-venue-property.md) ("the
  retrievable-history ceiling is a property of the venue, not of the query
  path") and [ADR-0018](0018-authenticated-access-confirms-the-history-ceiling.md)
  ("authenticated access confirms the identical ceiling").
- **Downstream, partially retracts:** the data premise (not the methodology)
  of [ADR-0017](0017-flb1-gate-bias-is-real-but-not-in-reachable-markets.md),
  [ADR-0019](0019-flb1-decile-study-real-but-sub-gate-edge-no-go.md),
  [ADR-0020](0020-flb1-tail-risk-is-concentrated-and-unmeasurable-from-68-days.md),
  [ADR-0021](0021-weather-tail-correlation-mixed-evidence-not-decisive.md),
  [ADR-0022](0022-v03-econ-calibration-gate-is-also-underpowered.md).
- **Found by:** a `dev-team:product-manager` agent, commissioned to refresh the
  2026-07-17 venue-landscape doc, flagged this as a documentation gap it could
  not test itself (no execution environment) — see
  `docs/research/2026-07-28-venue-landscape-refresh.md`. Verified directly,
  live, in this session before writing anything down.

## What was wrong

ADR-0016 and ADR-0018 concluded Kalshi's settled-market history is
unretrievable past ~68 days, tested three ways (paginated listing, direct
event-by-ticker lookup, `/markets?event_ticker=`) and once more authenticated.
**All four tests queried the same endpoint family: `/markets`, `/events`, and
their authenticated equivalents — Kalshi's *live-tier* endpoints.** Kalshi
separately documents (`docs.kalshi.com/getting_started/historical_data`,
fetched by the PM agent, confirmed live here) a **`/historical/*` endpoint
family** — `/historical/markets`, `/historical/trades`,
`/historical/markets/{ticker}/candlesticks`, `/historical/cutoff` — explicitly
for data **older** than the live-tier window. `src/ingest_kalshi.py`'s own
module docstring already named this boundary (*"the `/historical/markets/
{ticker}/candlesticks` variant 404s for markets that haven't crossed Kalshi's
historical-archive cutoff yet"*) — written while building `KalshiSource`, and
never followed up on. **The four "independent" confirmations in ADR-0016/0018
were four ways of asking the same question of the same tier, not four
independent checks of the venue.**

## What was actually tested here, live, before writing this down

```
GET /historical/cutoff
  -> market_settled_ts: 2026-05-28T00:00:00Z   (61 days before today, 2026-07-28 —
     matches the ~66-68 day live-tier ceiling ADR-0016/0018 measured almost exactly)

GET /historical/markets?series_ticker=KXHIGHNY   (paginated to exhaustion, 9 pages)
  -> 8,896 markets. Oldest close: 2021-08-07 — Kalshi's actual inception, not a
     rolling window. 1,816 days, not ~68.

GET /historical/markets/{HIGHNY-21AUG06-T86}/candlesticks, /historical/trades
  -> real data survives on the OLDEST market in that set: 1 candle, 50 trades,
     yes_price_dollars = 0.9900. Not just a settlement result — actual traded
     prices, five years back.

GET /historical/markets?series_ticker=KXNOBELPEACE   -> 24 resolved, 1 distinct event
GET /historical/markets?series_ticker=KXHURCTOT      -> 28 resolved, 4 distinct events,
                                                          2022-11 through 2025-12
GET /historical/markets?series_ticker=KXRAINNYCM     -> 168 resolved, 27 distinct
                                                          events, 2024-03 through 2026-05
```

The two series ADR-0016 declared to have **zero** retrievable resolved
history — the basis for killing HURSEAS-1 and DROUGHT-1 outright — both have
real resolved history via `/historical/markets`. `KXRAINNYCM` alone, on its
own, has **27x** the distinct-event count ADR-0016 reported for the entire
MRAIN-1 candidate ("1 resolved monthly cycle").

## What actually reopens, and what still doesn't

**MRAIN-1 — the biggest reversal.** ADR-0016 killed it specifically on power
("~2 monthly cycles × 11 stations ≈ 18–22 independent station-months... very
likely underpowered"), while noting *"it directly satisfies ADR-0014's own
named revisit condition"* and has the right mechanism. One series
(`KXRAINNYCM`) alone now shows **27 independent events over 2+ years** — before
extending to the other ~10 monthly-rain series the 2026-07-25 research doc
catalogued. MRAIN-1's own pre-registered gate (Brier skill ≥5%, n≥400 across
≥3 station-months) looks newly reachable. **This is the strongest candidate
for a fresh look, and the power objection that killed it is gone.**

**HURSEAS-1 — reopens, but weakly.** — **Re-checked 2026-07-31 by [ADR-0026](0026-hurseas1-still-dead-but-now-for-the-right-reason.md): confirmed dead. 4 seasons is the real ceiling (all 3 relevant tickers cover the identical Atlantic-basin annual count, not independent data), and annual cadence caps this regardless of API tier — unlike MRAIN-1, this one stays closed.** 4 independent hurricane seasons
(2022–2025) instead of 0. ADR-0016's own standard for this candidate was that
even "one season" (n=1) makes a powered gate impossible; 4 is a real
improvement but is still a small-n regime for anything claiming statistical
confidence. Worth a cheap re-check, not a confident reversal.

**KXNOBELPEACE stays effectively dead.** 1 distinct event even across the
full historical window — it's an annual award; more years of API access
doesn't change that it resolves once a year. DROUGHT-1 (not directly
re-tested here, same series-shape as MRAIN-1's weekly cadence) should be
re-checked the same way before assuming ADR-0016's verdict still holds.

**FLB-1's "emotional" target basket** — ADR-0017 reported 4 resolved markets
across 3 series from the live-tier probe. Almost certainly undercounted the
same way; not re-tested here, but should be before trusting that number.

**FLB-1's weather-ladder decile study (ADR-0019/0020/0021) is the other major
one.** It ran on 68 days / 2,411 markets from the live tier. `KXHIGHNY` alone
has **8,896 markets across 5 years** via `/historical/markets`, with real
traded prices confirmed surviving. This is precisely the missing piece
ADR-0020/0021 named as unresolvable: *"this needs more calendar time, ideally
spanning a full seasonal cycle including whatever season produces the most
extreme forecast busts... and that requires forward observation, not a
longer look at Kalshi's own settled-market history, which the venue simply
does not retain past ~68 days."* **That last clause was wrong.** The tail-risk
question ADR-0020/0021 left open — how often does a 2026-06-07-style
correlated forecast miss get severe enough to break multiple cities at once —
may be directly answerable by re-running the same decile/correlation study
across five years of `/historical/markets` data instead of 88 days, covering
every season including whichever ones produce genuine forecast busts.

**What does NOT change:** WP-7's own weather calibration verdict
([ADR-0014](0014-wp7-gate-result-no-go.md)) already used real ingested data
(408 KXHIGHNY markets with candles, via the store/PIT pipeline, not the
live-tier settled-market listing this ADR is about) and is not built on the
premise being retracted here. It stands.

## Why this was missed, stated plainly

Rule of the project's own standing discipline: verify from a second, different
route, not by re-reading the first check. ADR-0018's stated purpose was to
test whether *authentication* reaches deeper history; it re-ran the identical
query shape with auth headers attached and found the identical answer —
correctly showing authentication doesn't matter for the live tier, but
mistaking that for "the ceiling doesn't move by any mechanism," when a
completely different endpoint family was sitting undocumented-but-discoverable
in this project's own code comments the whole time. Three "independent"
checks in ADR-0016 that were actually three phrasings of one question created
false confidence. The retraction was found by an agent doing a documentation
review with no execution environment — it could read Kalshi's docs and this
project's own code side by side and notice the mismatch; verifying it needed
nothing more than trying the endpoint, which nobody had.

## Consequence

The forward-paper-or-stop fork ADR-0016 framed is **not necessarily still the
only option.** MRAIN-1 in particular may now be cheaply testable against real
multi-year historical data before any forward-paper time commitment. This
does not mean any candidate is now a GO — it means several "dead, no further
work possible" verdicts were wrong about *why* they were blocked, and the
actual next step is re-running the specific studies against `/historical/*`
data, not resuming the forward-paper-or-stop decision as previously framed.
