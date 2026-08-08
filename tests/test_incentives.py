"""
Tests for incentives.py — MAKER-1's scoring, pagination and gate logic.

The three properties worth pinning, because each one has already been got
wrong once or is the kind that fails silently:

  1. `period_reward` is centi-cents. A 100x unit error makes an unfundable
     candidate look fundable, and reads perfectly plausibly either way.
  2. `programs()` paginates. One unpaginated call returned a roster that
     omitted every weather and crypto series and looked complete.
  3. The gate has THREE verdicts. Collapsing UNDERPOWERED into NO-GO is how
     ADR-0022 and ADR-0027 produced nulls this project could not act on.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from incentives import (  # noqa: E402
    CENTI_CENTS_PER_DOLLAR,
    DEFAULT_TICK,
    HOURS_PER_YEAR,
    IncentiveProgram,
    KalshiIncentiveSource,
    SideBook,
    kalshi_side_score,
    level_score,
    my_score_share,
    parse_program,
    reference_price,
    reward_yield,
    run_gate,
)

UTC = timezone.utc


def make_program(**over) -> IncentiveProgram:
    base = {
        "program_id": "p1",
        "market_ticker": "KXTEMPNYCH-26AUG0221-T80.99",
        "incentive_type": "liquidity",
        "start": datetime(2026, 8, 3, 0, 0, tzinfo=UTC),
        "end": datetime(2026, 8, 3, 1, 0, tzinfo=UTC),
        "period_reward_centicents": 1_200_000,
        "discount_factor_bps": 5000,
        "target_size": 1000.0,
        "description": "new_event",
        "paid_out": False,
    }
    base.update(over)
    return IncentiveProgram(**base)


# --------------------------------------------------------------------------
# 1. units
# --------------------------------------------------------------------------

def test_period_reward_is_centi_cents_not_cents():
    """1,000,000 is $100.00. Read as cents it is $10,000 — the error that
    made the first pass at this research rank a candidate on a pool 100x too
    large."""
    prog = make_program(period_reward_centicents=1_000_000)
    assert prog.period_reward_usd == pytest.approx(100.0)
    assert CENTI_CENTS_PER_DOLLAR == 10_000


def test_observed_pools_fall_inside_kalshis_published_band():
    """Kalshi's help page quotes reward amounts of "$10-$1,000 per day". Every
    pool observed live on 2026-08-02 sits inside that band under the
    centi-cents reading; under a cents reading they would span $1,500-$100,000
    a day. This is the independent cross-check on the unit, not a restatement
    of it."""
    observed = [150_000, 200_000, 250_000, 1_000_000, 1_200_000, 1_400_000,
                10_000_000]
    for cc in observed:
        assert 10.0 <= make_program(period_reward_centicents=cc).period_reward_usd <= 1_000.0


def test_discount_factor_bps_to_fraction():
    assert make_program(discount_factor_bps=5000).discount_factor == 0.5
    # absent means no distance penalty, not zero credit for distant orders
    assert make_program(discount_factor_bps=None).discount_factor == 1.0


def test_parse_program_rejects_missing_reward():
    """The pool is the whole statistic; its absence is an error, not a zero."""
    row = {"id": "x", "market_ticker": "T", "start_date": "2026-08-03T00:00:00Z",
           "end_date": "2026-08-03T01:00:00Z"}
    with pytest.raises(ValueError):
        parse_program(row)


def test_parse_program_reads_fixed_point_target_size_string():
    row = {"id": "x", "market_ticker": "T", "incentive_type": "liquidity",
           "start_date": "2026-08-03T00:00:00Z", "end_date": "2026-08-03T01:00:00Z",
           "period_reward": 1_200_000, "discount_factor_bps": 5000,
           "target_size_fp": "1000.00", "incentive_description": "new_event",
           "paid_out": False}
    prog = parse_program(row)
    assert prog.target_size == 1000.0
    assert prog.period_reward_usd == pytest.approx(120.0)
    assert prog.period_hours == pytest.approx(1.0)


def test_parse_program_rejects_bool_reward():
    """bool is an int subclass in Python; True must not become 1 centi-cent."""
    row = {"id": "x", "market_ticker": "T", "start_date": "2026-08-03T00:00:00Z",
           "end_date": "2026-08-03T01:00:00Z", "period_reward": True}
    with pytest.raises(ValueError):
        parse_program(row)


# --------------------------------------------------------------------------
# 2. pagination
# --------------------------------------------------------------------------

def _row(pid: str, ticker: str) -> dict:
    return {"id": pid, "market_ticker": ticker, "incentive_type": "liquidity",
            "start_date": "2026-08-03T00:00:00Z", "end_date": "2026-08-03T01:00:00Z",
            "period_reward": 1_200_000, "discount_factor_bps": 5000,
            "target_size_fp": "1000.00", "incentive_description": "",
            "paid_out": False}


def test_programs_paginates_to_exhaustion():
    """The regression that matters: page 1 is all earnings-mention markets and
    the weather programmes only appear on page 2. A non-paginating reader
    reports "no weather series" and is believed."""
    pages = [
        {"incentive_programs": [_row("a", "KXEARNINGSMENTIONDKNG-1")],
         "next_cursor": "c1"},
        {"incentive_programs": [_row("b", "KXTEMPNYCH-1")], "next_cursor": "c2"},
        {"incentive_programs": [_row("c", "KXBTCMAXMON-1")], "next_cursor": ""},
    ]
    calls = []

    def fetch(path, **params):
        calls.append(params.get("cursor"))
        return pages[len(calls) - 1]

    progs = KalshiIncentiveSource(fetch).programs()
    assert [p.market_ticker for p in progs] == [
        "KXEARNINGSMENTIONDKNG-1", "KXTEMPNYCH-1", "KXBTCMAXMON-1"]
    assert calls == [None, "c1", "c2"]


def test_programs_deduplicates_repeated_ids():
    """A cursor that repeats a page must not double-count a pool."""
    pages = [
        {"incentive_programs": [_row("a", "T1"), _row("b", "T2")], "next_cursor": "c1"},
        {"incentive_programs": [_row("b", "T2"), _row("c", "T3")], "next_cursor": ""},
    ]
    it = iter(pages)
    progs = KalshiIncentiveSource(lambda path, **p: next(it)).programs()
    assert [p.program_id for p in progs] == ["a", "b", "c"]


def test_programs_stops_on_a_cursor_that_never_clears():
    """A server that always returns the same cursor and the same rows must
    terminate on the no-fresh-rows check, not spin to MAX_PAGES."""
    calls = []

    def fetch(path, **params):
        calls.append(1)
        return {"incentive_programs": [_row("a", "T1")], "next_cursor": "same"}

    progs = KalshiIncentiveSource(fetch).programs()
    assert len(progs) == 1
    assert len(calls) == 2  # first page, then one page with nothing fresh


# --------------------------------------------------------------------------
# 3. scoring
# --------------------------------------------------------------------------

def test_level_score_full_credit_at_best_and_df_per_tick():
    levels = [(0.50, 400.0), (0.49, 600.0), (0.48, 200.0)]
    # 400*1 + 600*0.5 + 200*0.25 = 750
    assert level_score(levels, best=0.50, discount_factor=0.5) == pytest.approx(750.0)


def test_level_score_tick_distance_is_rounded_not_truncated():
    """(0.99 - 0.98)/0.01 is 0.9999... in binary floating point. Truncating
    puts a one-tick order at zero ticks and inflates the competing score,
    which deflates our share and biases the gate toward NO-GO."""
    s = level_score([(0.98, 100.0)], best=0.99, discount_factor=0.5)
    assert s == pytest.approx(50.0)


def test_empty_side_scores_zero_and_is_a_real_state():
    """Several incentivized strikes were observed live with one side entirely
    unquoted. That is zero competing score, not missing data."""
    book = SideBook.from_levels([], discount_factor=0.5)
    assert book.score == 0.0 and book.best is None and book.total_size == 0.0


def test_finer_tick_reduces_penalty_for_the_same_prices():
    """Sub-penny series (rolled out 2026-07-09) put the same price further
    from best in ticks; passing the default 1c grid on such a series
    understates the distance."""
    levels = [(0.48, 100.0)]
    # 2 ticks on a 1c grid (100 * 0.5^2 = 25); 4 on a half-cent grid
    # (100 * 0.5^4 = 6.25). Same price, same book, four times the penalty.
    coarse = level_score(levels, best=0.50, discount_factor=0.5, tick=DEFAULT_TICK)
    fine = level_score(levels, best=0.50, discount_factor=0.5, tick=0.005)
    assert coarse == pytest.approx(25.0)
    assert fine == pytest.approx(6.25)
    assert coarse > fine


# --------------------------------------------------------------------------
# 4. the statistic
# --------------------------------------------------------------------------

def test_reward_yield_share_and_annualisation():
    prog = make_program(period_reward_centicents=1_200_000)  # $120, 1 hour
    yes = SideBook(best=0.50, total_size=1000.0, score=1000.0)
    no = SideBook(best=0.50, total_size=1000.0, score=1000.0)
    s = reward_yield(prog, yes=yes, no=no, ts=prog.start, resting_notional=2000.0)
    assert s is not None
    # $2,000 at $0.50 is 4,000 contracts; competing (pooled) is 2,000
    assert s.my_size == pytest.approx(4000.0)
    assert s.competing_score == pytest.approx(2000.0)
    assert s.score_share == pytest.approx(4000.0 / 6000.0)
    assert s.payout_usd == pytest.approx(120.0 * 2 / 3)
    # period yield over a 1h window, annualised by 8,760
    # per OCCUPIED hour: the 1h window is not multiplied by 8,760 here
    assert s.hourly_yield == pytest.approx(s.period_yield / 1.0)


def test_pooled_denominator_is_the_conservative_default():
    """Kalshi does not document per-side normalisation; Polymarket US does.
    Defaulting to a pooled denominator must yield LESS, so a NO-GO under it is
    safe and a GO is not inflated by the assumption."""
    prog = make_program()
    yes = SideBook(best=0.50, total_size=1000.0, score=1000.0)
    no = SideBook(best=0.50, total_size=5000.0, score=5000.0)
    pooled = reward_yield(prog, yes=yes, no=no, ts=prog.start)
    per_side = reward_yield(prog, yes=yes, no=no, ts=prog.start, per_side_pool=True)
    assert pooled is not None and per_side is not None
    assert pooled.hourly_yield < per_side.hourly_yield


def test_unquoted_side_returns_none_rather_than_zero():
    """Averaging a fabricated zero into the cluster mean would bias the gate
    toward NO-GO. An unquoted side is unmeasurable, not unprofitable."""
    prog = make_program()
    yes = SideBook(best=None, total_size=0.0, score=0.0)
    no = SideBook(best=0.99, total_size=1500.0, score=1500.0)
    assert reward_yield(prog, yes=yes, no=no, ts=prog.start) is None


def test_target_met_requires_both_sides():
    prog = make_program(target_size=1000.0)
    ok = reward_yield(prog, ts=prog.start,
                      yes=SideBook(0.50, 1200.0, 1200.0),
                      no=SideBook(0.50, 1100.0, 1100.0))
    one_sided = reward_yield(prog, ts=prog.start,
                             yes=SideBook(0.50, 1200.0, 1200.0),
                             no=SideBook(0.50, 10.0, 10.0))
    assert ok is not None and ok.target_met_both_sides
    assert one_sided is not None and not one_sided.target_met_both_sides


def test_program_day_clusters_by_programme_and_day_not_by_snapshot():
    a = make_program(program_id="a", market_ticker="KXTEMPNYCH-1")
    b = make_program(program_id="b", market_ticker="KXTEMPNYCH-1",
                     start=a.start + timedelta(days=1),
                     end=a.end + timedelta(days=1))
    c = make_program(program_id="c", market_ticker="KXTEMPCHIH-1")
    assert a.program_day != b.program_day  # same market, different day
    assert a.program_day != c.program_day  # same day, different market


# --------------------------------------------------------------------------
# 5. the gate
# --------------------------------------------------------------------------

def _samples(day_yields: dict[str, list[float]]):
    """Values are given ANNUALISED for readability and stored as the hourly
    rate the gate consumes, so run_gate's scale-up returns them unchanged at
    occupancy 1.0."""
    out = []
    for d, (day, ys) in enumerate(day_yields.items()):
        # each cluster gets its own calendar day: concurrent events at one
        # instant are not independent, and run_gate now enforces that.
        base = make_program().start + timedelta(days=d)
        for i, y in enumerate(ys):
            prog = make_program(program_id=day, market_ticker=day,
                                start=base, end=base + timedelta(hours=1))
            s = reward_yield(prog, ts=base + timedelta(seconds=60 * i),
                             yes=SideBook(0.50, 2000.0, 2000.0),
                             no=SideBook(0.50, 2000.0, 2000.0))
            assert s is not None
            out.append(type(s)(**{**s.__dict__, "program_day": day,
                                  "hourly_yield": y / HOURS_PER_YEAR}))
    return out


def test_gate_underpowered_below_minimum_clusters():
    """5 clusters at a spectacular yield is still not a study."""
    res = run_gate(_samples({f"d{i}": [0.90] for i in range(5)}),
                   threshold=0.15, min_clusters=20)
    assert res.n_clusters == 5
    assert res.verdict == "UNDERPOWERED"


def test_gate_go_requires_both_threshold_and_t():
    res = run_gate(_samples({f"d{i}": [0.40 + 0.001 * i] for i in range(25)}),
                   threshold=0.15, min_clusters=20)
    assert res.verdict == "GO" and res.t >= 2.0 and res.mean >= 0.15


def test_gate_no_go_only_when_a_go_sized_effect_is_excluded():
    """The ADR-0029 discipline: a NO-GO must have its 95% CI entirely below
    the threshold, not merely a mean below it."""
    res = run_gate(_samples({f"d{i}": [0.01 + 0.0005 * i] for i in range(25)}),
                   threshold=0.15, min_clusters=20)
    assert res.verdict == "NO-GO"
    assert res.go_excluded and res.ci_hi < 0.15


def test_gate_returns_underpowered_not_no_go_when_ci_covers_threshold():
    """The exact failure ADR-0022 and ADR-0027 made: a mean below the
    threshold with a CI that still covers it is NOT a NO-GO."""
    # Mean just under the threshold but with enough cluster-to-cluster spread
    # that the interval still reaches it. The tight-and-low case is a genuine
    # NO-GO and is covered by the test above; this is the case those two ADRs
    # mislabelled as one.
    noisy = {f"d{i}": [1.0 if i % 2 else -0.8] for i in range(25)}
    res = run_gate(_samples(noisy), threshold=0.15, min_clusters=20)
    assert res.mean < 0.15
    assert res.ci_hi > 0.15
    assert res.verdict == "UNDERPOWERED"
    assert not res.go_excluded


def test_gate_clusters_snapshots_rather_than_counting_them():
    """1,440 snapshots of one book state is one observation. If the gate
    counted samples, k would be 2,880 here and t would be inflated by ~38x."""
    res = run_gate(_samples({"d1": [0.20] * 1440, "d2": [0.20] * 1440}),
                   threshold=0.15, min_clusters=2)
    assert res.n_samples == 2880
    assert res.n_clusters == 2


def test_gate_on_no_samples_is_underpowered():
    res = run_gate([], threshold=0.15)
    assert res.verdict == "UNDERPOWERED" and res.n_clusters == 0


def test_occupancy_scales_the_yield_but_not_the_t_statistic():
    """Occupancy multiplies every cluster mean by the same constant, so it
    moves the reported yield and its CI together and leaves t untouched. A
    half-occupied roster halves the yield; it does not halve the evidence."""
    data = {f"d{i}": [0.40 + 0.001 * i] for i in range(25)}
    full = run_gate(_samples(data), threshold=0.15, min_clusters=20, occupancy=1.0)
    half = run_gate(_samples(data), threshold=0.15, min_clusters=20, occupancy=0.5)
    assert half.mean == pytest.approx(full.mean / 2)
    assert half.t == pytest.approx(full.t)
    assert half.mean_hourly == pytest.approx(full.mean_hourly)


def test_occupancy_can_flip_a_go_to_a_no_go():
    """The whole point of the amendment: a yield that clears the bar only by
    assuming the capital never sits idle must not be reported as a GO."""
    data = {f"d{i}": [0.20 + 0.0005 * i] for i in range(25)}
    assert run_gate(_samples(data), threshold=0.15, min_clusters=20,
                    occupancy=1.0).verdict == "GO"
    assert run_gate(_samples(data), threshold=0.15, min_clusters=20,
                    occupancy=0.05).verdict == "NO-GO"


def test_default_notional_is_the_amended_two_hundred():
    """Pinned so a revert to the pre-registered $2,000 -- which made the
    modelled position a majority of the reward auction -- fails a test."""
    from incentives import DEFAULT_NOTIONAL
    assert DEFAULT_NOTIONAL == 200.0
    prog = make_program()
    s = reward_yield(prog, ts=prog.start,
                     yes=SideBook(0.50, 2000.0, 2000.0),
                     no=SideBook(0.50, 2000.0, 2000.0))
    assert s is not None and s.resting_notional == 200.0


def test_gate_rejects_a_single_instant_however_many_programmes():
    """The bug this guard exists for: Kalshi runs ~50 concurrent programmes
    across ~5 events, so one sampling pass produced 37 "clusters" and a GO
    verdict off a single moment of market state."""
    prog = make_program()
    one_instant = []
    for i in range(40):
        p = make_program(program_id=f"p{i}", market_ticker=f"KXTEMPNYCH-26AUG0301-T{i}")
        s = reward_yield(p, ts=prog.start,
                         yes=SideBook(0.50, 100.0, 100.0),
                         no=SideBook(0.50, 100.0, 100.0))
        assert s is not None
        one_instant.append(s)
    res = run_gate(one_instant, threshold=0.15, min_clusters=20, min_days=5)
    assert res.n_days == 1
    assert res.verdict == "UNDERPOWERED"


def test_strikes_on_one_event_collapse_to_one_cluster():
    """Ten strikes on KXTEMPLAXH-26AUG0301 are one weather outcome quoted ten
    ways. Clustering on the strike inflates t by ~sqrt(10)."""
    progs = [make_program(program_id=f"s{i}",
                          market_ticker=f"KXTEMPLAXH-26AUG0301-T{60 + i}.99")
             for i in range(10)]
    assert len({p.event_ticker for p in progs}) == 1
    assert len({p.program_day for p in progs}) == 1


# ---------------------------------------------------------------------------
# 6. Kalshi's ACTUAL scoring rules (help.kalshi.com Liquidity Incentive
#    Program). These differ from `level_score` in two ways that move the
#    yield in OPPOSITE directions, which is why the approximation could not
#    be corrected by a single scaling factor.
# ---------------------------------------------------------------------------
def test_reference_price_is_where_cumulative_size_reaches_a_fifth_of_target():
    # target 1000 -> need 200 cumulative. 50 + 100 = 150 (<200), +80 = 230.
    levels = [(0.60, 50.0), (0.59, 100.0), (0.58, 80.0), (0.57, 500.0)]
    assert reference_price(levels, 1000.0) == 0.58


def test_reference_price_is_best_when_top_of_book_is_thick():
    levels = [(0.60, 5000.0), (0.59, 10.0)]
    assert reference_price(levels, 1000.0) == 0.60


def test_reference_price_none_when_side_never_reaches_a_fifth():
    assert reference_price([(0.60, 10.0)], 1000.0) is None


def test_orders_better_than_reference_price_are_not_penalised():
    # Everything at or above ref gets 1.0x; nothing is scored at a negative
    # tick distance just because it is above the reference price.
    levels = [(0.60, 100.0), (0.59, 100.0), (0.58, 100.0)]
    ref = reference_price(levels, 1000.0)
    assert ref == 0.59, "cumulative size reaches 200 at 0.59, not 0.58"
    # 0.60 and 0.59 are at-or-better than ref -> full credit (100 + 100);
    # 0.58 is one tick worse -> 100 * 0.5.
    got = kalshi_side_score(levels, target_size=1000.0, discount_factor=0.5)
    assert got == pytest.approx(250.0)


def test_credit_stops_at_target_size():
    """A whale does not earn in proportion to size beyond target."""
    thin = kalshi_side_score([(0.60, 1000.0)], target_size=1000.0,
                             discount_factor=0.5)
    whale = kalshi_side_score([(0.60, 19560.0)], target_size=1000.0,
                              discount_factor=0.5)
    assert thin == pytest.approx(1000.0)
    assert whale == pytest.approx(1000.0), "size past target must not score"


def test_kalshi_score_and_level_score_disagree_on_a_real_book():
    """The two scorers are not interchangeable — this is the whole point.

    Reproduces the shape of the KXTEMPLAXH row that produced the implausible
    headline yield: a very deep top level against a target of 1,000.
    """
    levels = [(0.99, 19560.0), (0.98, 500.0)]
    approx = level_score(levels, best=0.99, discount_factor=0.5)
    exact = kalshi_side_score(levels, target_size=1000.0, discount_factor=0.5)
    assert approx == pytest.approx(19560.0 + 250.0)
    assert exact == pytest.approx(1000.0)
    assert exact < approx


def test_empty_side_scores_zero_under_kalshi_rules_too():
    assert kalshi_side_score([], target_size=1000.0, discount_factor=0.5) == 0.0


def test_share_collapses_when_the_book_already_exceeds_target():
    """Resting behind a whale buys almost nothing — the naive model's error."""
    share = my_score_share([(0.99, 19560.0)], my_price=0.99, my_size=202.0,
                           target_size=1000.0, discount_factor=0.5)
    naive = 202.0 / (202.0 + 1574.01)   # what the approximation reported
    assert share < 0.02, "credit is capped at target, not additive"
    assert share < naive / 5


def test_share_is_large_when_we_are_the_only_resting_order():
    share = my_score_share([], my_price=0.50, my_size=500.0,
                           target_size=1000.0, discount_factor=0.5)
    assert share == pytest.approx(1.0)


def test_share_is_pro_rata_within_a_shared_price_level():
    share = my_score_share([(0.50, 300.0)], my_price=0.50, my_size=100.0,
                           target_size=1000.0, discount_factor=0.5)
    assert share == pytest.approx(0.25)


def test_worse_price_earns_less_than_best_price():
    at_best = my_score_share([(0.60, 400.0)], my_price=0.60, my_size=100.0,
                             target_size=1000.0, discount_factor=0.5)
    behind = my_score_share([(0.60, 400.0)], my_price=0.58, my_size=100.0,
                            target_size=1000.0, discount_factor=0.5)
    assert behind < at_best


def test_zero_size_earns_no_share():
    assert my_score_share([(0.5, 100.0)], my_price=0.5, my_size=0.0,
                          target_size=1000.0, discount_factor=0.5) == 0.0
