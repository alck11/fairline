"""
QA regression tests for WP-3 (src/wallet_features.py: _dominant_category /
features_for_wallet; src/wallet_scoring.py: build_basket).

Standalone, no pytest dependency (matches repo convention: run directly with
`python3 tests/test_wallet_basket_specialism.py`). Exits non-zero on first
failed assertion, prints "ALL PASSED" if everything the spec requires holds.

Traces to docs/architecture/decisions/0007-baskets-specialism-filter-not-per-category-scores.md
and docs/architecture/plan.md WP-3 acceptance criteria:
  - dominant_category/_share/_n are computed ONLY from the already point-in-time
    filtered `hist` (resolve_ts < as_of) -- no leakage.
  - tie-break is deterministic: most trades wins, ties broken by highest summed
    stake, remaining ties broken lexically by category name -- and this must
    not depend on PYTHONHASHSEED / dict-or-set iteration order.
  - hhi_category is unaffected by the new columns.
  - build_basket filters dominant_category == category AND
    dominant_category_share >= min_share AND
    dominant_category_n >= min_category_trades AND score >= min_score,
    all four boundaries inclusive (>=), then ranks by score desc and takes top_k.
  - a category with zero qualifying specialists returns [] gracefully (no error).
  - a wallet can structurally appear in at most one category's basket, since
    dominant_category is single-valued per (wallet, as_of) row.
  - a diversified wallet (no majority category) clears no share floor and
    appears in neither basket.

This file was added by QA (WP-3 has no existing automated tests, unlike WP-4/
WP-5's tests/test_risk_execution_*.py) to fill that coverage gap; it found no
bugs during this pass -- see docs/qa/report-WP-3.md for the full QA writeup.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd  # noqa: E402

from wallet_features import _dominant_category, _prep, features_for_wallet  # noqa: E402
from wallet_scoring import build_basket  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _ts(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _trade(wallet, category, resolve_ts, entry_ts="2026-01-01", size=100.0,
           entry_price=0.5, resolved_value=1.0, fee_paid=0.0):
    return dict(wallet=wallet, category=category, size=size, entry_price=entry_price,
                entry_ts=_ts(entry_ts), resolve_ts=_ts(resolve_ts),
                resolved_value=resolved_value, fee_paid=fee_paid)


def test_dominant_category_tiebreak_is_deterministic():
    # exact count tie AND exact stake-sum tie between "zeta" and "alpha" ->
    # lexical tie-break must pick "alpha", regardless of row insertion order.
    hist_a = pd.DataFrame({
        "category": ["zeta", "zeta", "alpha", "alpha", "beta"],
        "stake":    [10.0, 10.0, 10.0, 10.0, 5.0],
    })
    hist_b = pd.DataFrame({
        "category": ["alpha", "alpha", "zeta", "zeta", "beta"],
        "stake":    [10.0, 10.0, 10.0, 10.0, 5.0],
    })
    cat_a, share_a, n_a = _dominant_category(hist_a)
    cat_b, share_b, n_b = _dominant_category(hist_b)
    check(cat_a == "alpha", f"count+stake tie must resolve lexically to 'alpha', got {cat_a!r}")
    check(cat_a == cat_b and share_a == share_b and n_a == n_b,
          "tie-break result must not depend on row insertion order")

    # count tie but stake NOT tied -> higher-stake category wins even if lexically later
    hist_c = pd.DataFrame({
        "category": ["alpha", "alpha", "zeta", "zeta"],
        "stake":    [1.0, 1.0, 100.0, 100.0],
    })
    cat_c, _, _ = _dominant_category(hist_c)
    check(cat_c == "zeta", f"stake should break a count tie even against lexical order, got {cat_c!r}")


def test_dominant_category_tiebreak_stable_across_hash_seeds():
    # A dict/set-iteration-order-based tie-break would vary with PYTHONHASHSEED.
    # sorted()-based (as implemented) must not.
    script = (
        "import sys; sys.path.insert(0, 'src'); import pandas as pd; "
        "from wallet_features import _dominant_category; "
        "hist = pd.DataFrame({'category': ['zeta','zeta','alpha','alpha','beta'], "
        "'stake': [10.0,10.0,10.0,10.0,5.0]}); "
        "print(_dominant_category(hist)[0])"
    )
    outs = set()
    for seed in ["0", "1", "42", "random"]:
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        r = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True,
                            cwd=os.path.join(os.path.dirname(__file__), ".."), env=env)
        check(r.returncode == 0, f"subprocess failed with PYTHONHASHSEED={seed}: {r.stderr}")
        outs.add(r.stdout.strip())
    check(len(outs) == 1, f"tie-break result varies across PYTHONHASHSEED: {outs}")


def test_no_leakage_future_trades_excluded_from_dominant_category():
    as_of = pd.Timestamp("2026-02-01", tz="UTC")
    rows = [_trade("w1", "politics", resolve_ts=pd.Timestamp("2026-01-10", tz="UTC") + pd.Timedelta(days=i))
            for i in range(5)]
    # 100 future (post-as_of) trades in a different category and much larger volume;
    # these must NOT influence dominant_category/_share/_n.
    rows += [_trade("w1", "crypto",
                     entry_ts=pd.Timestamp("2026-02-05", tz="UTC") + pd.Timedelta(days=i),
                     resolve_ts=pd.Timestamp("2026-02-10", tz="UTC") + pd.Timedelta(days=i))
             for i in range(100)]
    prepped = _prep(pd.DataFrame(rows))
    feat = features_for_wallet(prepped, as_of)
    check(feat["dominant_category"] == "politics",
          f"LEAKAGE: future crypto trades leaked into dominant_category, got {feat['dominant_category']!r}")
    check(feat["dominant_category_n"] == 5, "dominant_category_n must count only pre-as_of trades")
    check(feat["n_resolved"] == 5, "n_resolved must count only pre-as_of trades")


def test_resolve_ts_equal_as_of_is_excluded():
    # resolve_ts < as_of is strict; resolve_ts == as_of must be excluded, same
    # boundary as the pre-existing filter (must not have changed).
    as_of = pd.Timestamp("2026-01-15", tz="UTC")
    rows = [_trade("w2", "politics", resolve_ts=as_of) for _ in range(10)]
    prepped = _prep(pd.DataFrame(rows))
    feat = features_for_wallet(prepped, as_of)
    check(feat is None, "trades with resolve_ts == as_of must be excluded, leaving < 5 hist rows -> None")


def test_build_basket_boundaries_are_inclusive():
    scored = pd.DataFrame({
        "wallet": ["exact_share", "below_share", "exact_n", "below_n",
                   "exact_score", "below_score"],
        "dominant_category": ["crypto"] * 6,
        "dominant_category_share": [0.5, 0.4999999, 0.9, 0.9, 0.9, 0.9],
        "dominant_category_n": [10, 10, 5, 4, 10, 10],
        "score": [80.0, 80.0, 80.0, 80.0, 70.0, 69.9999],
    })
    b_share = build_basket(scored, "crypto", min_score=0.0, min_category_trades=0)
    check("exact_share" in b_share and "below_share" not in b_share,
          f"share == min_share must pass (>=), got {b_share}")

    b_n = build_basket(scored[scored.wallet.isin(["exact_n", "below_n"])],
                        "crypto", min_score=0.0, min_share=0.0)
    check(b_n == ["exact_n"], f"n == min_category_trades must pass (>=), got {b_n}")

    b_score = build_basket(scored[scored.wallet.isin(["exact_score", "below_score"])],
                            "crypto", min_share=0.0, min_category_trades=0)
    check(b_score == ["exact_score"], f"score == min_score must pass (>=), got {b_score}")


def test_build_basket_empty_category_returns_empty_list_not_error():
    scored = pd.DataFrame({
        "wallet": ["w1"], "dominant_category": ["crypto"],
        "dominant_category_share": [0.9], "dominant_category_n": [10], "score": [90.0],
    })
    result = build_basket(scored, "a_category_no_wallet_specializes_in")
    check(result == [], f"unqualified category must return [] gracefully, got {result!r}")


def test_wallet_cannot_appear_in_two_baskets_and_diversified_wallet_in_neither():
    scored = pd.DataFrame({
        "wallet":                 ["crypto_spec", "politics_spec", "diversified"],
        "dominant_category":      ["crypto",      "politics",      "crypto"],
        "dominant_category_share": [0.9,           0.9,             0.4],
        "dominant_category_n":     [10,            10,              4],
        "score":                  [90.0,          90.0,            90.0],
    })
    crypto_basket = build_basket(scored, "crypto", min_score=0.0, min_category_trades=0)
    politics_basket = build_basket(scored, "politics", min_score=0.0, min_category_trades=0)
    check(set(crypto_basket).isdisjoint(politics_basket),
          f"a wallet must not appear in two baskets: {crypto_basket} vs {politics_basket}")
    check("diversified" not in crypto_basket and "diversified" not in politics_basket,
          "a diversified wallet (share < min_share) must appear in neither basket")
    check("crypto_spec" in crypto_basket and "politics_spec" in politics_basket,
          "genuine specialists must appear in their own category's basket")


if __name__ == "__main__":
    tests = [
        test_dominant_category_tiebreak_is_deterministic,
        test_dominant_category_tiebreak_stable_across_hash_seeds,
        test_no_leakage_future_trades_excluded_from_dominant_category,
        test_resolve_ts_equal_as_of_is_excluded,
        test_build_basket_boundaries_are_inclusive,
        test_build_basket_empty_category_returns_empty_list_not_error,
        test_wallet_cannot_appear_in_two_baskets_and_diversified_wallet_in_neither,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL: {t.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR: {t.__name__}: {type(e).__name__}: {e}")

    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print("\nALL PASSED")
