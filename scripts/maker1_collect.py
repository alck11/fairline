"""
scripts/maker1_collect.py — MAKER-1 forward-observation collector.

    python3 scripts/maker1_collect.py --series KXTEMP --interval 60 --hours 24

Samples Kalshi's live liquidity-incentive roster and the L2 book on every
market carrying one, scores both sides with the programme's own discount
factor, and writes one `book_snapshot` row per (programme, instant).

**This is the only study in this repo that cannot be re-run from history.**
Kalshi archives settled markets back to 2021 (ADR-0023) but serves no archive
of past book state or past programme rosters, so an instant not sampled is
gone. Hence: a daemon, idempotent writes, and a collector that logs and
continues rather than aborting a multi-day run on one bad HTTP response.

Zero capital risk — read-only, unauthenticated, no order ever placed.

**AMENDED 2026-08-05: the series filter no longer defaults to KXTEMP.**

The original default targeted Kalshi's hourly city-temperature programmes,
because four of the five KXTEMP cities (NYC, Chicago, LAX, Austin) are in
`weather_ingest.STATIONS` with station mappings verified 595/595 against
Kalshi's own settlements by ADR-0029 -- convenient for modelling the
underlying. That convenience does not matter for a liquidity-incentive yield
study, and it cost a day of collection:

  * KXTEMP's last programme ended **2026-08-04 23:00 UTC** and none were
    scheduled after it. The series had 13,448 programmes in the roster's
    history and **zero** live. Programmes had been posted at every hour of
    the day, so this was not a diurnal gap.
  * A study keyed to one series is hostage to Kalshi's rotation schedule.
    The roster still carried ~$311k across 4,304 live programmes at that
    moment; only our chosen slice of it was empty.

So the collector now sweeps the whole roster and keeps the `--top-n` largest
pools. Selection is on **pool size, known before the book is fetched and
independent of the yield being measured** -- ranking on anything the book
tells us (yield, spread, depth) would be selection on the outcome.

Cadence also moved 60s -> 300s. Re-sampling one programme every 60s adds
almost no information (it is one book state observed repeatedly, the very
thing the gate's clustering exists to discount) whereas covering more
programmes adds independent event-days. Measured cost of a 400-programme
pass: ~4.4s roster + ~52s of books at 7.7 books/sec, inside a 300s budget.

This does NOT shorten the >= 5 distinct-UTC-day requirement; it only makes
those days likely to actually happen instead of stalling on an empty roster.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

import store  # noqa: E402
from incentives import (  # noqa: E402
    DEFAULT_TICK,
    IncentiveProgram,
    KalshiIncentiveSource,
    SideBook,
)
from ingest_kalshi import KalshiAPIError, KalshiSource  # noqa: E402

_STOP = False


def _handle_signal(signum, frame):  # pragma: no cover - signal path
    global _STOP
    _STOP = True
    print(f"\n[{datetime.now(timezone.utc):%H:%M:%S}] signal {signum} — "
          f"finishing this pass, then stopping", flush=True)


def upsert_program(conn, prog: IncentiveProgram) -> None:
    """Idempotent programme upsert; refreshes `last_seen_at` and `paid_out`."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incentive_program (
                program_id, market_ticker, incentive_type, start_at, end_at,
                period_reward_centicents, discount_factor_bps, target_size,
                description, paid_out)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (program_id) DO UPDATE SET
                paid_out     = EXCLUDED.paid_out,
                last_seen_at = now()
            """,
            (prog.program_id, prog.market_ticker, prog.incentive_type,
             prog.start, prog.end, prog.period_reward_centicents,
             prog.discount_factor_bps, prog.target_size, prog.description,
             prog.paid_out),
        )


def write_snapshot(conn, prog: IncentiveProgram, ts: datetime,
                   yes: SideBook, no: SideBook,
                   yes_levels=None, no_levels=None) -> None:
    """One scored book state. ON CONFLICT DO NOTHING keeps restarts safe.

    The raw levels ride along because Kalshi scores distance from a Reference
    Price derived from the cumulative size profile, which the scored reduction
    cannot reconstruct (migration 004). A snapshot stored without them can
    never be re-scored, and this study cannot re-collect the past.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO book_snapshot (
                program_id, ts, yes_best, yes_total_size, yes_score,
                no_best, no_total_size, no_score, yes_levels, no_levels)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (program_id, ts) DO NOTHING
            """,
            (prog.program_id, ts, yes.best, yes.total_size, yes.score,
             no.best, no.total_size, no.score,
             Json(yes_levels) if yes_levels is not None else None,
             Json(no_levels) if no_levels is not None else None),
        )


def collect_pass(conn, source: KalshiSource, incentives: KalshiIncentiveSource,
                 *, series_prefix: str, tick: float, top_n: int = 0,
                 levels_depth: int = 12, verbose: bool = True) -> int:
    """One sweep of the live roster. Returns snapshots written.

    Every per-market failure is caught and logged rather than raised: a
    multi-day collector that dies on one 429 loses every instant after it, and
    those instants are unrecoverable.
    """
    now = datetime.now(timezone.utc)
    try:
        progs = incentives.programs(status="active", incentive_type="liquidity")
    except (KalshiAPIError, ValueError) as e:
        print(f"[{now:%H:%M:%S}] roster fetch failed: {e}", flush=True)
        return 0

    if series_prefix:
        progs = [p for p in progs if p.market_ticker.startswith(series_prefix)]

    # `status=active` has so far always coincided with the live window, but the
    # two are not the same claim and only one of them is what we mean.
    progs = [p for p in progs if p.start <= now <= p.end]

    # Ex-ante selection by pool size. This ranks on a quantity known BEFORE the
    # book is fetched and independent of the yield being measured, so it cannot
    # select on the outcome -- it is the choice a <$10k bankroll would actually
    # make, not a filter on results. Ranking on anything derived from the book
    # (yield, spread, depth) would be exactly the p-hack this project keeps
    # writing ADRs about.
    if top_n and len(progs) > top_n:
        progs = sorted(progs, key=lambda p: -p.period_reward_usd)[:top_n]

    written = 0
    for prog in progs:
        try:
            upsert_program(conn, prog)
            book = source.orderbook(f"{prog.market_ticker}-YES")
        except (KalshiAPIError, ValueError) as e:
            if verbose:
                print(f"  skip {prog.market_ticker}: {type(e).__name__}: {e}",
                      flush=True)
            continue
        df = prog.discount_factor
        # `orderbook()` returns this side's bids and, as asks, the OTHER
        # side's bids already converted to (1 - q). The score is defined on
        # resting orders as posted, so the ask side is converted back rather
        # than scored at its complement — DF^ticks is symmetric but `best` is
        # not, and scoring 0.98-complements against a 0.02 best would put
        # every no-side order at the wrong tick distance.
        yes_levels = list(book.bids)
        no_levels = [(round(1.0 - p, 4), s) for p, s in book.asks]
        yes = SideBook.from_levels(yes_levels, discount_factor=df, tick=tick)
        no = SideBook.from_levels(no_levels, discount_factor=df, tick=tick)
        write_snapshot(
            conn, prog, now, yes, no,
            yes_levels=[[float(p), float(s)] for p, s in yes_levels[:levels_depth]],
            no_levels=[[float(p), float(s)] for p, s in no_levels[:levels_depth]])
        written += 1

    conn.commit()
    if verbose:
        print(f"[{now:%H:%M:%S}] {len(progs)} programme(s), "
              f"{written} snapshot(s) written", flush=True)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="",
                    help="market-ticker prefix filter; '' collects everything")
    ap.add_argument("--levels-depth", type=int, default=12,
                    help="how many book levels per side to persist (004); "
                         "must reach past the 1/5-of-target reference price")
    ap.add_argument("--top-n", type=int, default=400,
                    help="keep only the N largest live pools (0 = no cap); "
                         "ranked ex ante on pool size, never on the book")
    ap.add_argument("--interval", type=int, default=300,
                    help="seconds between passes (default 300)")
    ap.add_argument("--hours", type=float, default=24.0,
                    help="how long to run before exiting (default 24)")
    ap.add_argument("--tick", type=float, default=DEFAULT_TICK,
                    help="price grid; pass a finer value on sub-penny series")
    ap.add_argument("--once", action="store_true", help="single pass, then exit")
    args = ap.parse_args(argv)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    conn = store.connect()
    source = KalshiSource()
    incentives = KalshiIncentiveSource()
    deadline = datetime.now(timezone.utc) + timedelta(hours=args.hours)
    total = passes = 0
    try:
        while not _STOP:
            started = time.monotonic()
            try:
                total += collect_pass(conn, source, incentives,
                                      series_prefix=args.series, tick=args.tick,
                                      top_n=args.top_n,
                                      levels_depth=args.levels_depth)
                passes += 1
            except psycopg.Error as e:
                # Neon (and any managed Postgres) can administratively drop an
                # idle connection at any point in a multi-day run -- this is
                # not a bad-data event like the per-market catch above, it's
                # routine infrastructure churn. The first version of this
                # script had no handler here: one AdminShutdown killed the
                # whole 10-day collection and it sat dead, silently, for
                # about a day before anyone noticed. A missed instant is
                # unrecoverable (see module docstring), so staying up matters
                # more than any single pass.
                now = datetime.now(timezone.utc)
                print(f"[{now:%H:%M:%S}] db connection lost "
                      f"({type(e).__name__}: {e}) -- reconnecting", flush=True)
                try:
                    conn.close()
                except psycopg.Error:
                    pass
                try:
                    conn = store.connect()
                    print(f"[{now:%H:%M:%S}] reconnected", flush=True)
                except psycopg.Error as e2:
                    print(f"[{now:%H:%M:%S}] reconnect failed: {e2} -- "
                          f"will retry next interval", flush=True)
            if args.once or datetime.now(timezone.utc) >= deadline:
                break
            # Sleep the REMAINDER of the interval, so a slow pass does not
            # stretch the sampling cadence: the gate's 38x t-inflation warning
            # assumes a known snapshots-per-day, and a drifting clock makes
            # that count a function of network latency.
            time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    finally:
        try:
            conn.close()
        except psycopg.Error:
            pass
    print(f"\n{passes} pass(es), {total} snapshot(s) written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
