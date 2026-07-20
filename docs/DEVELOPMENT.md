# Development Guide

This guide covers the development setup, tooling, and workflow for fairline.

## Quick Start

```bash
make setup       # One-time setup: creates .venv, installs all deps
source .venv/bin/activate

# Before committing:
make lint        # Auto-fix linting issues
make format      # Format code
make type-check  # Type checking
make test        # Run tests
```

Or use the individual tools:
```bash
ruff check --fix src tests
ruff format src tests
mypy src
pytest tests -v
```

## Setup

### Prerequisites
- Python 3.12+ (check with `python3 --version`)
- PostgreSQL 15+ with TimescaleDB (for tests with a real DB)

### Full Setup
```bash
# Clone and enter the repo
git clone <repo>
cd fairline

# Create virtual environment and install everything
make setup

# Verify setup
python src/store.py          # Demo: store.py
python src/ingest_kalshi.py  # Demo: ingest_kalshi.py
make test                    # Run tests
```

### Install Development Tools Only
If you already have a venv:
```bash
make install-dev
pre-commit install
```

## Development Tools

### Linting & Formatting

**ruff** — Fast Python linter and formatter (modern replacement for flake8/pylint/black/isort)

```bash
make lint      # ruff check --fix (auto-fixes violations)
make format    # ruff format + black (format code)
make type-check  # mypy (type checking)
```

Configuration: `pyproject.toml` [tool.ruff]
- Line length: 100 characters
- Target: Python 3.12+
- Rules: E, W, F, I, C4, UP, B, A, C90, SIM, RUF

### Type Checking

**mypy** — Static type checker

```bash
make type-check
mypy src       # Full check
mypy src/store.py  # Single file
```

Configuration: `pyproject.toml` [tool.mypy]
- `check_untyped_defs = true` — flag functions missing type hints
- `strict_optional = true` — strict None checking

### Security Scanning

**bandit** — Security issue detector

```bash
make security-check
bandit -r src -c pyproject.toml
```

Looks for: SQL injection, hardcoded secrets, insecure crypto, etc.

### Testing

**pytest** — Test framework

```bash
make test              # Run all tests
make test-parallel     # Run in parallel (faster on multi-core)
make coverage          # Coverage report

pytest tests -v                       # Verbose
pytest tests -k test_foo              # Single test
pytest tests -m integration -v        # Integration tests only
pytest tests -v --co                  # List tests without running
```

Configuration: `pyproject.toml` [tool.pytest] or `pytest.ini`

**pytest-cov** — Coverage reporting

```bash
pytest tests --cov=src --cov-report=html --cov-report=term-missing
open htmlcov/index.html
```

### Pre-commit Hooks

**pre-commit** — Git hooks that run checks before commit

```bash
# Install hooks (run once)
make pre-commit-install

# Run manually on all files
make pre-commit-run

# Skip hooks (not recommended)
git commit --no-verify
```

Hooks run:
- Trailing whitespace, end-of-file fixes
- ruff lint + format
- mypy type check
- bandit security scan
- pydocstyle (docstring format)

See `.pre-commit-config.yaml` for the full list.

## Code Organization

```
fairline/
├── src/
│   ├── store.py              # Persistence layer (WP-1)
│   ├── ingest.py             # Data interface (ADR-0006)
│   ├── ingest_kalshi.py      # Kalshi adapter (WP-3)
│   ├── run_kalshi_ingest.py  # CLI entry point
│   ├── prob_fn.py            # Model interface (WP-2, ADR-0009)
│   ├── backtest.py           # Backtest harness (WP-4)
│   ├── ev_detector.py        # EV/Kelly math (parked)
│   ├── risk_execution.py     # Paper engine (WP-4)
│   ├── fees.py               # Fee models
│   └── ...
├── tests/
│   ├── test_store.py         # store.py tests
│   ├── test_ingest_kalshi.py # KalshiSource tests (fixture-based)
│   ├── test_*.py             # One per module
│   └── fixtures/             # Recorded API responses, test data
├── schema/
│   ├── 001_schema.sql        # Base tables
│   └── 002_kalshi_ev.sql     # MVP tables (WP-1)
├── docs/
│   ├── architecture/
│   │   ├── overview.md       # System architecture
│   │   ├── plan.md           # Implementation plan
│   │   └── decisions/        # ADRs (0001–0010)
│   ├── product/              # Requirements, roadmap
│   └── research/             # Background research
├── pyproject.toml            # Modern Python packaging config
├── requirements.txt          # Production deps
├── requirements-dev.txt      # Dev tools
├── Makefile                  # Convenient make targets
├── CONTRIBUTING.md           # Contributing guide
└── .pre-commit-config.yaml   # Git hooks
```

## Writing Code

### Style Guide

**General Principles**
- Fail loud: raise exceptions, don't silently drop data
- Explicit over implicit: type hints where they clarify
- Comments for the *why*, not the *what*: code names itself
- No premature abstractions: three similar lines ≥ shared helper

**Imports**
```python
# Order: stdlib → third-party → local (ruff sorts these)
import json
from datetime import datetime
from typing import Protocol

import pandas as pd
from psycopg import Connection

from ingest import MarketRow
```

**Type Hints**
```python
# Public functions: full type hints
def upsert_market(conn: Connection, row: MarketRow) -> int:
    """Store a market, return market_id."""

# Private helpers: hints are nice but not required
def _parse_field(s: str | None) -> float | None:
    return float(s) if s else None

# Use Protocol for interfaces (ADR-0009)
class ProbFn(Protocol):
    name: str
    def __call__(self, market: MarketRef, as_of: datetime) -> float: ...
```

**Comments**
```python
# GOOD: explains why, not what
# Kalshi's yes+no ≈ 1 pricing (not exactly 1 due to fees), so NO = 1 − YES
no_price = 1.0 - yes_price

# BAD: restates the code
result = yes_price - 1.0  # subtract from 1
```

**Error Handling**
```python
# GOOD: fail loud with context
if not (0.0 <= price <= 1.0):
    raise ValueError(f"price out of range for {ticker}: {price}")

# BAD: silently return None or default
if price < 0 or price > 1:
    return None  # loses the error signal

# GOOD: wrap low-level exceptions in a domain exception
try:
    candle = Candle(...)
except (KeyError, TypeError, ValueError) as e:
    raise KalshiAPIError(f"malformed response: {e}") from e
```

### Testing

**Test Organization**
```python
# tests/test_ingest_kalshi.py — one file per module

def test_candlesticks_happy_path():
    """Happy path: valid response → list of Candles."""

def test_candlesticks_validates_ohlc_range():
    """Validation: price outside [0,1] raises KalshiAPIError."""

def test_candlesticks_fallback_yes_bid_yes_ask():
    """Fallback: when price fields are null, use bid/ask midpoint."""

@pytest.mark.integration
def test_roundtrip_market_to_store():
    """Integration: write and read back, idempotent."""

@pytest.mark.slow
def test_large_backtest_performance():
    """Performance: 1000 markets × 365 days in <10s."""
```

**Test Patterns**
- **Fixture-based:** use recorded API responses (no live network)
- **Deterministic:** same input → same output, always
- **Isolated:** each test can run alone, in any order
- **Fast:** unit tests < 100ms, integration < 1s
- **Clear:** test name says what and why; assertion message says what failed

**Running Tests**
```bash
make test                         # All tests
make test-parallel                # Parallel execution
make coverage                     # With coverage report

pytest tests/test_store.py        # Single file
pytest tests -k test_upsert       # Name filter
pytest tests -m integration       # Mark filter
```

## Common Workflows

### Adding a Feature

1. **Read the ADRs** for the component you're changing
2. **Write a test first** that should pass after your feature
3. **Implement the feature** to make the test pass
4. **Run linting and type-check** before committing
5. **Commit with a clear message** referencing the WP/ADR

### Fixing a Bug

1. **Write a test that reproduces the bug** (fails before fix, passes after)
2. **Fix the bug** (minimal change)
3. **Run all tests** to ensure you didn't break anything
4. **Commit with "fix:" prefix** and explain the root cause

### Refactoring

1. **Ensure all tests pass** before starting
2. **Make mechanical changes** (rename, reorganize) without logic changes
3. **Test after each step** to catch mistakes early
4. **Commit frequently** — refactoring is a series of small, safe commits

### Adding a Dependency

1. **Add to `pyproject.toml`** under `dependencies` or `dev`
2. **Run `pip install -r requirements.txt -r requirements-dev.txt`** to update
3. **Commit both files** (pyproject.toml and requirements files)

## Database Setup (for integration tests)

### Option 1: Automatic (pgserver)
If `DATABASE_URL` isn't set, tests auto-create a throwaway Postgres:
```bash
pip install pgserver  # Test-only dependency
make test             # Uses pgserver automatically
```

### Option 2: Manual (production-like)
```bash
# Install PostgreSQL 15+ with TimescaleDB extension
# Then create a database:
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/fairline
psql "$DATABASE_URL" -c 'CREATE DATABASE fairline'

# Apply schema (in order):
psql "$DATABASE_URL" -f schema/001_schema.sql
psql "$DATABASE_URL" -f schema/002_kalshi_ev.sql

# Run tests against the real DB
make test
```

## Troubleshooting

### "ruff not found"
```bash
pip install ruff>=0.5.0
# Or: make install-dev
```

### "mypy errors on a valid type"
Check the error message — mypy is usually right. If it's a false positive:
```python
x: SomeType = value  # type: ignore[assignment]
```

### "Tests pass locally but fail in CI"
- Check Python version (CI uses 3.12, 3.11)
- Check if network is needed (CI doesn't allow it — use fixtures)
- Check for timezone issues (use UTC always)
- Check for temp file cleanup (tests should clean after themselves)

### "Pre-commit hooks take too long"
Run them in a separate step, not on every commit:
```bash
git commit --no-verify  # Skip hooks
# Then run manually later:
make pre-commit-run
```

### "I need to update pre-commit hooks"
```bash
pre-commit autoupdate
git add .pre-commit-config.yaml
git commit -m "chore: update pre-commit hooks"
```

## Performance & Profiling

### Profiling Tests
```bash
pytest tests --durations=10  # 10 slowest tests
pytest tests --profile       # With pytest-benchmark
```

### Profiling Code
```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# ... code to profile ...

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative').print_stats(20)  # Top 20 by time
```

## Continuous Integration

GitHub Actions runs on every push to `main` or `develop`:
- Lint (ruff, black, mypy, bandit)
- Test (Python 3.10, 3.11, 3.12)
- Coverage (upload to codecov)
- Pre-commit hooks

See `.github/workflows/ci.yml` for details.

To run the same checks locally:
```bash
make lint
make type-check
make security-check
make test
```

## Further Reading

- [CONTRIBUTING.md](../CONTRIBUTING.md) — PR workflow
- [docs/architecture/overview.md](./architecture/overview.md) — System design
- [docs/architecture/plan.md](./architecture/plan.md) — Implementation roadmap
- [CONTEXT.md](../CONTEXT.md) — Domain language
