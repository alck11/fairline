"""
incentives.py — Kalshi liquidity-incentive programmes and the MAKER-1 statistic.

MAKER-1 asks one question: **does resting orders on an incentivized Kalshi
market pay enough, before adverse selection, to be worth measuring what
adverse selection costs?** Every candidate this project has closed (ADR-0014,
0022, 0025, 0026, 0027, 0029) was a *taker* strategy. This is the first look at
the other side of the book.

Two things here are easy to get wrong, and both were got wrong on the first
attempt (2026-08-02 research doc, §4.2 correction):

**1. `period_reward` is in CENTI-CENTS, not cents.** Kalshi's API reference
describes the field verbatim as *"Total reward for the period in centi-cents"*
(`int64`). So `1000000` is **$100.00**, not $10,000 — a 100x error in the
direction that makes a candidate look fundable when it is not. Cross-checked
against Kalshi's Liquidity Incentive Program help page, which quotes reward
amounts of "$10-$1,000 per day": the observed pools fall inside that band under
the centi-cents reading and two orders of magnitude outside it under the cents
reading. `CENTI_CENTS_PER_DOLLAR` exists so this conversion is never inlined.

**2. `GET /incentive_programs` MUST be paginated to exhaustion.** A single
unpaginated call returns ~100 programmes that all happen to sit on
`KXEARNINGSMENTION*` series, which reads as "Kalshi does not incentivize
weather or crypto". That is false: paginated, there are ~2,900 active
programmes spanning `KXTEMP*` / `KXRAIN*` weather, `KX*MAXMON` / `KX*MINMON`
crypto, and `KXGDP*` econ. `programs()` paginates; do not hand-roll a call.

The scoring formula is Kalshi's published one — score = size x DF^(ticks from
best price), summed over levels and snapshots; payout = (your score / total
score) x pool. Everything in this module is pure and injectable except
`KalshiIncentiveSource`, which is a thin paginating reader over one endpoint.
"""
from __future__ import annotations

import math
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))

from ingest_kalshi import DEFAULT_BASE_URL, KalshiSource  # noqa: E402

#: Kalshi denominates `period_reward` in centi-cents (1/100th of a cent).
CENTI_CENTS_PER_DOLLAR = 10_000

#: Kalshi's historical price grid. Sub-penny levels began rolling out
#: 2026-07-09 (docs.kalshi.com/changelog); a series carrying them reports a
#: finer grid in its `price_ranges`, and `tick` must then be passed explicitly
#: or every "ticks from best" distance below is overstated.
DEFAULT_TICK = 0.01

HOURS_PER_YEAR = 365.0 * 24.0


@dataclass(frozen=True)
class IncentiveProgram:
    """One `GET /incentive_programs` row, with units resolved at the boundary."""

    program_id: str
    market_ticker: str
    incentive_type: str
    start: datetime
    end: datetime
    period_reward_centicents: int
    discount_factor_bps: int | None
    target_size: float | None
    description: str
    paid_out: bool

    @property
    def period_reward_usd(self) -> float:
        """Pool for this period, in dollars. See module docstring — centi-cents."""
        return self.period_reward_centicents / CENTI_CENTS_PER_DOLLAR

    @property
    def discount_factor(self) -> float:
        """DF in [0, 1]. Absent means no distance penalty, i.e. DF = 1.0."""
        if self.discount_factor_bps is None:
            return 1.0
        return self.discount_factor_bps / 10_000

    @property
    def period_hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0

    @property
    def event_ticker(self) -> str:
        """The event this programme's market is one strike of.

        `KXTEMPLAXH-26AUG0301-T63.99` -> `KXTEMPLAXH-26AUG0301`. Kalshi lists
        one temperature event as ~10 strikes and runs a SEPARATE incentive
        programme on each, so a single sampling instant yields 50 programmes
        across only 5 events.
        """
        return self.market_ticker.rsplit("-", 1)[0]

    @property
    def program_day(self) -> str:
        """The clustering unit for the gate: one EVENT, one UTC day.

        Deliberately not the market ticker. Ten strikes on one city-hour share
        a book, a pool structure and a weather outcome; they are one
        observation quoted ten ways, and clustering on the strike would inflate
        t by ~sqrt(10) ~ 3.2x. This is the exact ladder trap ADR-0029 built
        family clustering to avoid, and the first version of this property fell
        into it -- 50 programmes reported as 50 clusters when there were 5.

        Also not one snapshot: samples inside an event-day are one book state
        observed repeatedly, which at a 60s cadence would inflate t by a
        further ~sqrt(1440) ~ 38x.
        """
        return f"{self.event_ticker}@{self.start.astimezone(timezone.utc):%Y-%m-%d}"


def _ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_program(row: dict[str, Any]) -> IncentiveProgram:
    """Row -> IncentiveProgram. Raises ValueError on a shape this cannot trust.

    `target_size_fp` is a fixed-point *string* ("1000.00"), not a number;
    float() on it is correct, but silently accepting a missing `period_reward`
    is not — the pool is the whole statistic, so its absence is an error
    rather than a zero.
    """
    try:
        reward = row["period_reward"]
        if not isinstance(reward, int) or isinstance(reward, bool):
            raise ValueError(f"period_reward must be an int, got {reward!r}")
        target_raw = row.get("target_size_fp")
        return IncentiveProgram(
            program_id=str(row["id"]),
            market_ticker=str(row["market_ticker"]),
            incentive_type=str(row.get("incentive_type", "")),
            start=_ts(row["start_date"]),
            end=_ts(row["end_date"]),
            period_reward_centicents=reward,
            discount_factor_bps=row.get("discount_factor_bps"),
            target_size=float(target_raw) if target_raw is not None else None,
            description=str(row.get("incentive_description", "")),
            paid_out=bool(row.get("paid_out", False)),
        )
    except (KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"unexpected incentive_programs row shape: {e}") from e


class KalshiIncentiveSource:
    """Paginating reader for `GET /incentive_programs`.

    Unauthenticated — confirmed live 2026-08-02. Takes a `fetch(path, **params)`
    callable so tests can inject a fake without touching the network; the
    default is backed by `KalshiSource`, which already carries the retry and
    backoff policy this project's other adapters use (ADR-0006 US-2).
    """

    #: A hard stop so a server that never clears `next_cursor` cannot spin
    #: forever. At limit=200 this covers ~40k programmes against ~2.9k live.
    MAX_PAGES = 200

    def __init__(self, fetch: Callable[..., dict] | None = None, *,
                 base_url: str = DEFAULT_BASE_URL) -> None:
        if fetch is None:
            fetch = KalshiSource(base_url=base_url).get_json
        self._fetch = fetch

    def programs(self, *, status: str | None = None, incentive_type: str | None = None,
                 limit: int = 200) -> list[IncentiveProgram]:
        """Every programme matching the filters, paginated to exhaustion.

        Deduplicates on `id`: a cursor that repeats a page would otherwise
        double-count a pool, and double-counting the denominator of a yield is
        exactly the kind of silent error this project keeps finding.
        """
        out: list[IncentiveProgram] = []
        seen: set[str] = set()
        cursor: str | None = None
        for _ in range(self.MAX_PAGES):
            page = self._fetch("/incentive_programs", limit=limit, status=status,
                               type=incentive_type, cursor=cursor)
            rows = page.get("incentive_programs") or []
            fresh = 0
            for row in rows:
                prog = parse_program(row)
                if prog.program_id in seen:
                    continue
                seen.add(prog.program_id)
                out.append(prog)
                fresh += 1
            cursor = page.get("next_cursor") or None
            if cursor is None or fresh == 0:
                break
        return out


def level_score(levels: Sequence[tuple[float, float]], *, best: float | None,
                discount_factor: float, tick: float = DEFAULT_TICK) -> float:
    """Kalshi's liquidity score for one side: sum of size x DF^(ticks from best).

    `best` is the best price on that side; an order sitting there scores its
    full size (DF^0 = 1). Distance is measured in ticks and rounded, because
    the prices arrive as floats parsed from decimal strings and
    `(0.99 - 0.98) / 0.01` is not exactly 1.0 in binary floating point —
    truncating instead of rounding would push a 1-tick order to 0 ticks and
    silently inflate the competing score.

    An empty book scores 0, which is a real state on these markets rather than
    a missing value: several incentivized strikes were observed with one side
    entirely unquoted.
    """
    if not levels or best is None:
        return 0.0
    total = 0.0
    for price, size in levels:
        ticks = abs(round((best - price) / tick))
        total += size * (discount_factor ** ticks)
    return total


#: Kalshi sets the Reference Price at the first level where cumulative resting
#: size reaches this fraction of Target Size.
REFERENCE_FRACTION = 0.2


def reference_price(levels: Sequence[tuple[float, float]],
                    target_size: float) -> float | None:
    """The price Kalshi measures distance from — NOT the best price.

    Walking the book from best, this is the first level at which cumulative
    resting size reaches one-fifth of Target Size. On a thick top-of-book it
    equals `best`; on a thin one it sits several ticks deeper, and every order
    at or better than it earns full credit.

    Returns None when the side never accumulates a fifth of target, in which
    case no order on that side has a defined distance.
    """
    if not levels or target_size <= 0:
        return None
    need = target_size * REFERENCE_FRACTION
    cum = 0.0
    for price, size in sorted(levels, key=lambda ps: -ps[0]):
        cum += size
        if cum >= need:
            return price
    return None


def kalshi_side_score(levels: Sequence[tuple[float, float]], *,
                      target_size: float, discount_factor: float,
                      tick: float = DEFAULT_TICK) -> float:
    """Score one side the way Kalshi's published LIP rules score it.

    Differs from `level_score` in the two ways its docstring could not know
    about, both taken from Kalshi's Liquidity Incentive Program help page:

      1. **Distance is measured from the Reference Price**, not the best
         price. Orders at or better than it take the full 1.0 multiplier.
      2. **Only size that helps reach Target Size is scored.** Credit stops
         once cumulative size reaches target, so a whale resting 19,560
         contracts against a target of 1,000 does not earn 19x anyone else —
         `level_score` gave it exactly that, inflating the competing score and
         understating our share.

    `level_score` is kept for the snapshots collected before migration 004,
    which have no stored levels and therefore cannot be scored this way. The
    two are not interchangeable and the gate reports which one it used.
    """
    if not levels or target_size <= 0:
        return 0.0
    ref = reference_price(levels, target_size)
    if ref is None:
        return 0.0
    total = 0.0
    remaining = target_size
    for price, size in sorted(levels, key=lambda ps: -ps[0]):
        if remaining <= 0:
            break
        counted = min(size, remaining)
        remaining -= counted
        # At or better than the reference price -> full credit. `round` for the
        # same binary-float reason level_score documents.
        ticks = max(0, round((ref - price) / tick))
        total += counted * (discount_factor ** ticks)
    return total


def my_score_share(levels: Sequence[tuple[float, float]], *,
                   my_price: float, my_size: float, target_size: float,
                   discount_factor: float, tick: float = DEFAULT_TICK) -> float:
    """Our share of one side's score once our own order joins the book.

    **This is the correction that matters most, and getting it wrong is what
    made the headline yield absurd.** The naive model adds our size on top of
    a competing score and takes `mine / (mine + competing)`. That is right
    when credit is unbounded, and wrong here: Kalshi scores only the depth
    that helps reach Target Size, so credit is a FIXED pool of roughly
    `target_size` contracts that all resting orders divide. Resting 202
    contracts behind 19,560 already-resting ones does not buy 11% of the
    reward — it buys about 1%, because the first 1,000 contracts by price
    priority absorb essentially all the credit before ours is reached.

    Our order is merged into its price level and the level's counted size is
    split pro rata. Kalshi does not publish an intra-level allocation rule;
    pro rata is the neutral choice. Time priority would be strictly worse for
    us (we arrive last), so this remains the optimistic end of the range.
    """
    if my_size <= 0 or target_size <= 0:
        return 0.0
    merged: dict[float, float] = {}
    for price, size in levels:
        merged[price] = merged.get(price, 0.0) + size
    merged[my_price] = merged.get(my_price, 0.0) + my_size

    ref = reference_price(list(merged.items()), target_size)
    if ref is None:
        return 0.0

    mine = total = 0.0
    remaining = target_size
    for price in sorted(merged, reverse=True):
        if remaining <= 0:
            break
        level_size = merged[price]
        counted = min(level_size, remaining)
        remaining -= counted
        weight = discount_factor ** max(0, round((ref - price) / tick))
        total += counted * weight
        if price == my_price:
            # Pro-rata split of this level's counted depth.
            mine += counted * (my_size / level_size) * weight
    return mine / total if total > 0 else 0.0


@dataclass(frozen=True)
class SideBook:
    """One side of one book at one instant, already scored."""

    best: float | None
    total_size: float
    score: float

    @classmethod
    def from_levels(cls, levels: Sequence[tuple[float, float]], *,
                    discount_factor: float, tick: float = DEFAULT_TICK) -> SideBook:
        best = max((p for p, _ in levels), default=None) if levels else None
        return cls(
            best=best,
            total_size=sum(s for _, s in levels),
            score=level_score(levels, best=best, discount_factor=discount_factor,
                              tick=tick),
        )


#: Default resting notional, AMENDED 2026-08-02 from the pre-registered $2,000
#: before any outcome data was collected. The amendment is recorded rather than
#: quietly applied, because silently retuning a pre-registration after seeing
#: data is the failure this project's ADRs exist to prevent.
#:
#: $2,000 was chosen before the books were measured. Once measured, the
#: incentivized KXTEMP strikes carried total resting size of ~2,000-5,000
#: contracts and competing *scores* of 120-1,400. At $0.44 a contract, $2,000
#: buys 4,545 contracts — so the modelled position was a *majority* of the
#: reward auction (median share 67.9%), and the statistic silently assumed we
#: could take that share without anyone responding. $200 keeps the position at
#: roughly 5% of observed depth, where price-taking is a defensible
#: approximation. The reflexivity does not vanish; it stops dominating.
DEFAULT_NOTIONAL = 200.0


@dataclass(frozen=True)
class YieldSample:
    """The MAKER-1 statistic at one instant, for one programme.

    The headline figure is `hourly_yield` — return per hour of capital
    *actually resting inside a live programme*. It is deliberately NOT
    annualised here. Annualising a 58-minute programme window by 8,760 assumes
    the capital rolls straight into another programme the moment this one ends,
    which is an occupancy assumption about the roster, not a property of this
    sample. `run_gate` applies a measured occupancy instead.
    """

    program_id: str
    program_day: str
    ts: datetime
    my_size: float
    my_price: float
    competing_score: float
    score_share: float
    payout_usd: float
    resting_notional: float
    period_yield: float
    hourly_yield: float
    target_met_both_sides: bool


def reward_yield(program: IncentiveProgram, *, yes: SideBook, no: SideBook,
                 ts: datetime, resting_notional: float = DEFAULT_NOTIONAL,
                 quote_price: float | None = None,
                 per_side_pool: bool = False,
                 tick: float = DEFAULT_TICK) -> YieldSample | None:
    """Ex-ante reward yield for resting `resting_notional` at the best price.

    Returns None when the book gives no price to quote at — an unquoted side
    is not a zero yield, it is an unmeasurable one, and averaging a fabricated
    zero into the cluster mean would bias the gate toward NO-GO.

    **`per_side_pool` is the load-bearing assumption and it defaults to the
    conservative reading.** Kalshi's help page states payout = (your score /
    *all participants'* scores) x pool without saying whether the two sides of
    a market are normalised separately. Polymarket US documents per-side
    normalisation; Kalshi does not. Defaulting to `False` puts *both* sides'
    scores in the denominator, which makes the share smaller and the yield
    lower. If this assumption is wrong, the true yield is higher than reported
    — so a NO-GO produced under it is safe and a GO is not overstated by it.

    The yield is deliberately **gross of adverse selection**, which cannot be
    measured without trading. That is the whole reason the gate threshold sits
    well above the risk-free rate rather than at zero.
    """
    price = quote_price if quote_price is not None else yes.best
    if price is None or price <= 0:
        return None

    my_size = resting_notional / price
    competing = yes.score if per_side_pool else (yes.score + no.score)
    denom = my_size + competing
    if denom <= 0:
        return None

    share = my_size / denom
    payout = program.period_reward_usd * share
    period_yield = payout / resting_notional
    hours = program.period_hours
    hourly = period_yield / hours if hours > 0 else float("nan")

    target = program.target_size
    target_met = bool(
        target is not None and yes.total_size >= target and no.total_size >= target
    )
    return YieldSample(
        program_id=program.program_id,
        program_day=program.program_day,
        ts=ts,
        my_size=my_size,
        my_price=price,
        competing_score=competing,
        score_share=share,
        payout_usd=payout,
        resting_notional=resting_notional,
        period_yield=period_yield,
        hourly_yield=hourly,
        target_met_both_sides=target_met,
    )


@dataclass(frozen=True)
class GateResult:
    """A clustered verdict, with the third outcome ADR-0029 made mandatory."""

    n_samples: int
    n_clusters: int
    n_days: int
    mean_hourly: float
    occupancy: float
    mean: float
    se: float
    t: float
    ci_lo: float
    ci_hi: float
    threshold: float
    min_clusters: int
    target_met_fraction: float
    verdict: str

    @property
    def go_excluded(self) -> bool:
        """True iff the 95% CI lies entirely below the GO threshold."""
        return self.ci_hi < self.threshold


def run_gate(samples: Sequence[YieldSample], *, threshold: float = 0.15,
             min_clusters: int = 20, min_days: int = 5,
             occupancy: float = 1.0) -> GateResult:
    """Cluster on programme-day, test the cluster means, return a verdict.

    Three outcomes, not two (ADR-0029): **GO** if the mean clears `threshold`
    with t >= 2; **NO-GO** only if a GO-sized effect is *excluded* — the 95% CI
    upper bound sits below the threshold; **UNDERPOWERED** otherwise. ADR-0022
    and ADR-0027 both produced nulls this project could not act on because they
    could not separate "no effect" from "not enough data". Returning NO-GO for
    a CI that still covers the threshold would repeat that.

    **`occupancy` is the amendment.** The pre-registered statistic annualised a
    58-minute programme window by 8,760, which assumes capital rolls straight
    from one programme into the next with no idle time. It cannot: $200 rests
    in one market at a time, and the roster is only sometimes offering one to
    rest in. `occupancy` is the measured fraction of sampling instants at which
    a qualifying programme existed, and it scales every cluster mean by the
    same constant — so it moves the reported yield and the CI together and
    leaves `t` unchanged. At `occupancy=1.0` this reduces exactly to the naive
    annualisation, which is why that value is the honest *upper bound* rather
    than the default expectation.
    """
    if not samples:
        return GateResult(0, 0, 0, float("nan"), occupancy, float("nan"),
                          float("nan"), float("nan"), float("nan"),
                          float("nan"), threshold, min_clusters,
                          float("nan"), "UNDERPOWERED")

    scale = HOURS_PER_YEAR * occupancy
    per: dict[str, list[float]] = {}
    for s in samples:
        per.setdefault(s.program_day, []).append(s.hourly_yield)
    mean_hourly = sum(s.hourly_yield for s in samples) / len(samples)
    cluster_means = [scale * sum(v) / len(v) for v in per.values()]

    k = len(cluster_means)
    mean = sum(cluster_means) / k
    if k > 1:
        var = sum((c - mean) ** 2 for c in cluster_means) / (k - 1)
        se = math.sqrt(var / k)
        t = mean / se if se > 0 else float("nan")
        # 1.96 is the normal approximation. At k >= 20 (the pre-registered
        # minimum) the t-distribution's 97.5th percentile is 2.09, so this is
        # very slightly narrow; the verdict logic below only ever *widens*
        # the underpowered region as a result, never the GO region.
        half = 1.96 * se
        ci_lo, ci_hi = mean - half, mean + half
    else:
        se = t = ci_lo = ci_hi = float("nan")

    met = sum(1 for s in samples if s.target_met_both_sides) / len(samples)
    n_days = len({s.ts.astimezone(timezone.utc).date() for s in samples})

    # `min_days` exists because concurrent events are not independent
    # observations. Kalshi runs 50 programmes across 5 events at any instant,
    # so ONE sampling pass clears a 20-cluster bar while containing a single
    # moment of market state. Calendar spread is what makes the clusters
    # independent, and it is the thing a forward study is actually buying.
    if k < min_clusters or n_days < min_days:
        verdict = "UNDERPOWERED"
    elif mean >= threshold and t >= 2.0:
        verdict = "GO"
    elif ci_hi < threshold:
        verdict = "NO-GO"
    else:
        verdict = "UNDERPOWERED"

    return GateResult(len(samples), k, n_days, mean_hourly, occupancy, mean,
                      se, t, ci_lo, ci_hi, threshold, min_clusters, met,
                      verdict)


if __name__ == "__main__":  # pragma: no cover - synthetic demo, no network
    df = 0.5
    prog = IncentiveProgram(
        program_id="demo", market_ticker="KXTEMPNYCH-DEMO-T80.99",
        incentive_type="liquidity",
        start=datetime(2026, 8, 3, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc),
        period_reward_centicents=1_200_000, discount_factor_bps=5000,
        target_size=1000.0, description="new_event", paid_out=False)
    print(f"pool ${prog.period_reward_usd:.2f} over {prog.period_hours:.2f}h, "
          f"DF={prog.discount_factor}")
    yes = SideBook.from_levels([(0.50, 400.0), (0.49, 600.0)], discount_factor=df)
    no = SideBook.from_levels([(0.48, 900.0)], discount_factor=df)
    print(f"yes score {yes.score:.1f} (400 at best + 600 one tick out x0.5)")
    s = reward_yield(prog, yes=yes, no=no, ts=prog.start)
    assert s is not None
    print(f"share {s.score_share:.2%}  payout ${s.payout_usd:.2f}  "
          f"per occupied hour {s.hourly_yield:.2%}")
    print(run_gate([s], occupancy=0.5))
