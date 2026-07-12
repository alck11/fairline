"""
wallet_scoring.py — frame copyability as supervised learning.

Question the model answers: "given a wallet's features AT TIME t, what is its
forward 30-day realized ROI on trades it ENTERS after t?"

Three traps this code is built to avoid:
  1. Leakage    — features use only resolve_ts < t; label uses entry_ts > t.
  2. Survivorship— a wallet that stops trading gets label 0, not dropped.
  3. Overfitting — time-ordered CV with a purge gap, never random k-fold.

The composite score in wallet_features.py is the baseline. Only adopt the
model if it beats that baseline out-of-time. Non-stationarity is brutal here;
expect decay and retrain on a rolling window.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from wallet_features import _prep, build_feature_panel

FEATURE_COLS = ["n_resolved", "win_rate", "realized_pnl", "roi", "sharpe",
                "max_drawdown", "avg_hold_hours", "hhi_category",
                "pnl_7d", "pnl_30d", "pnl_90d", "longest_loss_streak"]


def forward_label(trades: pd.DataFrame, wallet: str,
                  as_of: pd.Timestamp, horizon_days: int = 30) -> float:
    """Realized ROI of trades the wallet ENTERED in (as_of, as_of+horizon].

    Uses pnl/stake of those trades once resolved. A silent wallet -> 0.0,
    which is the correct label (you'd have copied nothing / made nothing)."""
    df = _prep(trades)
    end = as_of + pd.Timedelta(days=horizon_days)
    fut = df[(df["wallet"] == wallet) &
             (df["entry_ts"] > as_of) & (df["entry_ts"] <= end)]
    if fut.empty:
        return 0.0
    stake = fut["stake"].sum()
    return float(fut["pnl"].sum() / stake) if stake > 0 else 0.0


def build_training_table(trades: pd.DataFrame,
                         as_of_dates: list[pd.Timestamp],
                         horizon_days: int = 30) -> pd.DataFrame:
    """Point-in-time features (X) joined to forward labels (y)."""
    panel = build_feature_panel(trades, as_of_dates)
    panel["y_fwd_roi"] = [
        forward_label(trades, r.wallet, r.as_of, horizon_days)
        for r in panel.itertuples()
    ]
    return panel


def purged_time_splits(as_of_dates: list[pd.Timestamp], n_splits: int = 4,
                       embargo_steps: int = 1):
    """Yield (train_dates, test_dates) expanding-window splits, skipping
    `embargo_steps` as-of slots between train and test so a label's forward
    horizon never overlaps the training window. With a monthly grid and a
    30-day label horizon, embargo_steps=1 (skip one month) is the right gap."""
    dates = sorted(as_of_dates)
    fold = max(1, (len(dates) - embargo_steps) // (n_splits + 1))
    for k in range(1, n_splits + 1):
        cut = k * fold
        train = dates[:cut]
        test_start = cut + embargo_steps
        test = dates[test_start:test_start + fold]
        if train and test:
            yield train, test


def train_xgb(table: pd.DataFrame, n_splits: int = 4):
    """Time-aware training with early stopping. Returns (model, cv_scores).

    Requires xgboost; rank correlation (Spearman) is the metric that matters
    for copy selection — you care about ordering wallets, not exact ROI."""
    import xgboost as xgb
    from scipy.stats import spearmanr

    table = table.dropna(subset=FEATURE_COLS + ["y_fwd_roi"])
    dates = sorted(table["as_of"].unique())
    scores, model = [], None

    for train_d, test_d in purged_time_splits(list(dates), n_splits):
        tr = table[table["as_of"].isin(train_d)]
        te = table[table["as_of"].isin(test_d)]
        if len(tr) < 50 or len(te) < 20:
            continue
        model = xgb.XGBRegressor(
            n_estimators=400, max_depth=4, learning_rate=0.03,
            subsample=0.8, colsample_bytree=0.8,
            reg_lambda=1.0, early_stopping_rounds=40, n_jobs=4,
        )
        model.fit(tr[FEATURE_COLS], tr["y_fwd_roi"],
                  eval_set=[(te[FEATURE_COLS], te["y_fwd_roi"])], verbose=False)
        pred = model.predict(te[FEATURE_COLS])
        rho = spearmanr(pred, te["y_fwd_roi"]).correlation
        scores.append(float(rho) if rho == rho else 0.0)

    return model, scores


# ---------------------------------------------------------------------------
# basket construction: never bet the farm on one wallet
# ---------------------------------------------------------------------------
def build_basket(scored: pd.DataFrame, category: str, *, top_k: int = 8,
                 min_score: float = 70.0, min_share: float = 0.5,
                 min_category_trades: int = 5) -> list[str]:
    """Top-k wallets specialized in `category` whose composite score clears a
    floor (ADR-0007: a specialism filter over the single Score, not
    per-category scores). A wallet enters this basket only if `category` is
    its dominant_category (a majority of its resolved trades), which keeps
    ranking survivors by the overall `score` honest — for a specialist, the
    Score is mostly that category's performance anyway.

    Trade signal fires only when >=80% of the basket agrees on an outcome
    (enforced in your execution layer, not here)."""
    pool = scored[
        (scored["dominant_category"] == category)
        & (scored["dominant_category_share"] >= min_share)
        & (scored["dominant_category_n"] >= min_category_trades)
        & (scored["score"] >= min_score)
    ].copy()
    pool = pool.sort_values("score", ascending=False)
    return pool["wallet"].head(top_k).tolist()


if __name__ == "__main__":
    from wallet_features import composite_score

    rng = np.random.default_rng(11)
    n = 12000
    categories = ["politics", "sports", "crypto"]
    wallets = [f"0x{i:03x}" for i in range(120)]
    skill = {w: rng.normal(0, 0.15) for w in wallets}     # latent per-wallet edge
    # Give each wallet a "home" category it trades most of the time, with some
    # cross-category noise mixed in — uniformly-random categories per trade
    # would make almost every wallet diversified and every basket empty
    # (ADR-0007 / plan.md WP-3 demo note).
    home_category = {w: categories[i % len(categories)] for i, w in enumerate(wallets)}
    entry = pd.Timestamp("2026-01-01", tz="UTC") + pd.to_timedelta(rng.integers(0, 330, n), "D")
    w = rng.choice(wallets, n)
    home_col = np.array([home_category[x] for x in w])
    is_noise = rng.random(n) < 0.2
    category_col = np.where(is_noise, rng.choice(categories, n), home_col)
    price = rng.uniform(0.2, 0.8, n).round(2)
    # win prob nudged by latent skill -> learnable but noisy signal
    pwin = np.clip(price + [skill[x] for x in w] + rng.normal(0, 0.1, n), 0.02, 0.98)
    demo = pd.DataFrame({
        "wallet": w, "category": category_col,
        "size": rng.integers(10, 400, n).astype(float),
        "entry_price": price, "entry_ts": entry,
        "resolved_value": (rng.uniform(0, 1, n) < pwin).astype(float),
        "fee_paid": rng.uniform(0, 1.5, n).round(2),
    })
    demo["resolve_ts"] = demo["entry_ts"] + pd.to_timedelta(rng.integers(1, 200, n), "h")

    grid = [pd.Timestamp("2026-03-01", tz="UTC") + pd.Timedelta(days=30 * k) for k in range(9)]
    table = build_training_table(demo, grid)
    print(f"training rows: {len(table)}   mean fwd ROI: {table['y_fwd_roi'].mean():.3f}")
    try:
        model, cv = train_xgb(table)
        print(f"out-of-time Spearman per fold: {[round(c, 3) for c in cv]}")
    except ImportError:
        print("(install xgboost + scipy to run the model; composite score works without it)")

    # --- basket demo (ADR-0007): a specialism filter over the single Score ---
    # `table` already carries dominant_category/_share/_n from features_for_wallet
    # (selection metadata, deliberately excluded from FEATURE_COLS above).
    latest = table[table["as_of"] == grid[-1]].copy()
    scored = composite_score(latest)
    print(f"\nbasket demo as_of={grid[-1].date()}  ({len(scored)} scored wallets)")
    baskets = {}
    for cat in ["crypto", "politics"]:
        basket = build_basket(scored, cat)
        baskets[cat] = basket
        by_wallet = scored.set_index("wallet")
        all_match = all(by_wallet.loc[wl, "dominant_category"] == cat for wl in basket)
        print(f"basket[{cat}] ({len(basket)} wallets, all dominant_category=={cat}: {all_match}): {basket}")

    disjoint = set(baskets["crypto"]).isdisjoint(baskets["politics"])
    print(f"crypto and politics baskets are non-empty and disjoint: "
          f"{bool(baskets['crypto']) and bool(baskets['politics']) and disjoint}")
