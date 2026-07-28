# ADR-0021 — cross-city forecast-error correlation checked against NOAA/IEM data: mixed, not decisive

- **Status:** Accepted
- **Date:** 2026-07-28
- **Follows:** [ADR-0020](0020-flb1-tail-risk-is-concentrated-and-unmeasurable-from-68-days.md) —
  runs the check that ADR-0020 flagged as answerable now, without new Kalshi
  history: do the two dates that produced FLB-1's only observed losses look
  like a genuine correlated weather event, or an artifact of one thin market?
- **Tool:** `scripts/weather_tail_correlation_check.py`, against NOAA/IEM data
  (WP-6, [ADR-0011](0011-weather-data-source-iem-first-ndfd-deferred.md)) —
  not subject to Kalshi's ~68-day ceiling, so this window is a free choice,
  not a constraint.

## Decision

**Neither of ADR-0020's two readings wins outright. The evidence is genuinely
mixed, one bust date per reading, and that mix is itself the useful result:
it rules out a clean story in either direction and sets the actual next
requirement — geographic clustering, not aggregate correlation, should drive
any real position sizing if this is ever paper-traded.**

## What was checked

Six stations (KNYC, KLAX, KMDW as the KXHIGHCHI proxy, KMIA, KDEN, and KBOS —
added ad hoc for this script since Boston isn't in `weather_ingest.STATIONS`),
daily tmax, 2026-05-01 through 2026-07-27 (88 days, no Kalshi-side limit).
Three checks:

**1. Deseasonalized cross-city anomaly correlation** (tmax minus a trailing
14-day mean, so shared May→July warming doesn't masquerade as "correlation"):

```
            KNYC   KLAX   KMDW   KMIA   KDEN   KBOS
KNYC        1.00   0.32   0.49  -0.29  -0.31   0.83
KLAX        0.32   1.00   0.13  -0.09  -0.19   0.28
KMDW        0.49   0.13   1.00  -0.22   0.05   0.43
KMIA       -0.29  -0.09  -0.22   1.00   0.28  -0.33
KDEN       -0.31  -0.19   0.05   0.28   1.00  -0.28
KBOS        0.83   0.28   0.43  -0.33  -0.28   1.00
```

**KNYC–KBOS is 0.83 — genuinely strongly correlated**, as expected for two
Northeast stations sharing synoptic systems. KMDW sits in between (0.43–0.49
with the Northeast pair). **KLAX, KMIA, KDEN are weakly or negatively
correlated with the Northeast cluster** (−0.09 to 0.32) — the West/South/
Mountain cities are closer to genuinely independent draws. **This means the
five "zero-loss" cities are not one undifferentiated diversification pool**:
KNYC specifically shares real exposure with KBOS; the other three don't.

**2 & 3. The two actual bust dates, every station:**

| date | KNYC anomaly | KLAX | KMDW | KMIA | KDEN | KBOS | KNYC fc-err | KLAX | KMDW | KMIA | KDEN | KBOS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-05-26 | +0.3 | −1.3 | **+13.1** | −1.9 | **+12.6** | +6.7 | −5.0 | +5.0 | −3.0 | +0.0 | +5.0 | **−1.0** |
| 2026-06-07 | +12.4 | +3.6 | +8.9 | −2.1 | +11.4 | **+13.9** | −1.0 | +5.0 | +7.0 | +0.0 | −1.0 | **+8.0** |

(anomaly = actual tmax minus trailing-14-day mean; fc-err = observed minus a
~24–30h-lead MOS forecast, the diagnostic proxy described below.)

**These two dates tell different stories, and the difference is the finding.**

**2026-05-26 looks like the benign reading.** Chicago and Denver had *huge*
14-day anomalies (+13.1°F, +12.6°F) — a real heat event — but their
short-lead **forecast errors were modest** (−3.0°F, +5.0°F): the ~30h-out
forecast had already caught it. Boston's own short-lead error that day was
**−1.0°F — essentially accurate.** No station's short-lead forecast missed by
more than 5°F. A Kalshi bucket busting on a well-forecast day, with no city's
short-lead error exceeding 5°F, is much more consistent with **narrow strike
boundaries in a thin market** than with a genuine surprise — supporting
ADR-0020's reading 1 (liquidity/microstructure artifact) for this date
specifically.

**2026-06-07 looks like the concerning reading.** Most stations ran hot
against their 14-day baseline (KNYC +12.4, KMDW +8.9, KDEN +11.4, KBOS +13.9 —
a broad warm anomaly, Miami the exception), and **short-lead forecast errors
were elevated at multiple stations, not just Boston**: KBOS +8.0°F (the
largest), but KMDW +7.0°F and KLAX +5.0°F alongside it. Boston's bucket
flipped because its miss was largest, not because it was the only city that
missed — **this is a real, moderately correlated regional under-forecast**,
and a marginally worse version of the same event, or a narrower bucket at
Chicago, plausibly flips a second city's ladder on the same day. This
supports ADR-0020's reading 2 (genuine, currently-unpriced tail risk).

## What this settles, and what it doesn't

**Settles:** this isn't a case where the data clearly vindicates either
"it's just noise" or "it's a real hidden risk" — one bust date supports each
reading. That itself answers the open question in ADR-0020: **the tail risk
is real enough, at least sometimes, that it cannot be dismissed as pure
market-microstructure noise** — 2026-06-07 was a genuine multi-city forecast
miss, and it is exactly the mechanism that would eventually produce a
multi-position loss on a worse day.

**Does not settle:** how *often* an event like 2026-06-07 becomes severe
enough to break multiple cities' buckets *simultaneously* rather than one.
Two data points (one supporting, one not) over 88 days cannot estimate a
frequency, and that is precisely the limitation ADR-0020 named: this needs
more calendar time, ideally spanning a full seasonal cycle including whatever
season produces the most extreme forecast busts (likely winter storms or
early-season heat waves, neither present in this May–July window) — and
that requires forward observation, not a longer look at Kalshi's own
settled-market history, which the venue simply does not retain past ~68 days
([ADR-0016](0016-wp0-history-ceiling-is-a-venue-property.md)/
[ADR-0018](0018-authenticated-access-confirms-the-history-ceiling.md)).

**Actionable regardless of that:** any real deployment of this strategy
should size positions by **geographic cluster, not by city count.** Treating
KNYC and KBOS as two independent diversifying legs is wrong — they share 0.83
correlation. KLAX, KMIA, and KDEN are the genuinely independent legs. A
6-city book is closer to a 4-cluster book (Northeast, West, South, Mountain)
for risk purposes.

## Method caveats, stated plainly

- **The forecast-error check is a diagnostic approximation, not a production
  signal.** `weather_ingest.py`'s own docstring is explicit that deriving a
  proper daily-max *forecast* (vs. the raw hourly `tmp` MOS carries) is "a
  WP-7/WP-8 concern, deliberately not done here." This script takes the
  maximum hourly forecast value on the target date from a single ~30h-prior
  MOS cycle as a stand-in — reasonable for a two-date case study, not
  rigorous enough to build a signal on.
- **KMDW stands in for KXHIGHCHI** and **KBOS is uncurated** (added ad hoc,
  following `weather_ingest.py`'s own documented convention but not
  spot-checked against Kalshi's actual resolution rules) — matching that
  module's existing caveat that station-to-series mappings need confirmation
  before any production use. Fine for this diagnostic; not a claim about
  Kalshi's official resolution station.
- **n=88 days, one season.** The correlation matrix is a real measurement,
  not a guess, but it's a summer-only estimate; winter storm systems could
  show entirely different cross-city correlation structure.

## Consequence

No change to the fork ADR-0016 already identified. This adds a second,
independent reason forward paper is the only way to actually resolve FLB-1's
tail risk (the first was the retrieval ceiling): **the risk-defining event
type is confirmed to occur — 2026-06-07 wasn't noise — but its frequency and
worst-case severity are not estimable from 88 days.** If the user chooses
forward paper, size any real position by the geographic clusters this ADR
identified, not by naive city count.
