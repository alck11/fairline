# Contributing to fairline

Thank you for your interest in contributing to fairline. This document provides guidelines and procedures for participating in development.

## Code of Conduct

- Be respectful and professional
- Focus on the code, not the person
- Treat disagreements as learning opportunities
- Help keep this a welcoming environment for all contributors

## Setup

### Quick Start

```bash
make setup       # Creates .venv, installs all dependencies
source .venv/bin/activate
make lint        # Auto-fix linting issues
make test        # Run the test suite
```

### Manual Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
```

## Development Workflow

### 1. Before You Start

- Read [docs/architecture/overview.md](docs/architecture/overview.md) for the system architecture
- Check [CONTEXT.md](CONTEXT.md) for domain language
- Review relevant ADRs in [docs/architecture/decisions/](docs/architecture/decisions/)

### 2. Making Changes

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Write code** following the style guide (below)

3. **Run linting and tests** before committing:
   ```bash
   make lint        # Auto-fix with ruff
   make format      # Format with black
   make type-check  # Type check with mypy
   make test        # Run tests
   ```

4. **Write or update tests** — new features must have tests
   - Tests go in `tests/test_*.py` (one per module)
   - Fixtures go in `tests/fixtures/`
   - Use `pytest` patterns (repo convention: `python3 tests/test_<file>.py` standalone)

5. **Commit with clear messages**:
   ```bash
   git commit -m "Brief summary

   Longer explanation if needed. Reference ADRs, WP numbers, or issues.
   
   Co-Authored-By: Your Name <your.email@example.com>"
   ```

### 3. Code Style

#### General Principles
- **Fail loud:** never silently no-op or drop errors
- **Be explicit:** type hints where they clarify, comments only for the *why*
- **Test at the boundary:** validate input, trust internal code
- **No premature abstractions:** three similar lines is better than a shared helper

#### Linting & Formatting

All code is automatically checked and formatted by:
- **ruff** — fast linter (E, W, F, I, C4, UP, B, A, C90, SIM, RUF rules)
- **black** — code formatter (100 char line, single-quoted strings)
- **mypy** — type checker (check_untyped_defs, strict_optional)
- **isort** — import sorting (black-compatible)

Pre-commit hooks run automatically on `git commit`. To run manually:

```bash
make lint      # Run ruff with --fix
make format    # Run ruff format + black
make type-check  # Run mypy
make security-check  # Run bandit
```

#### Python Style

```python
# Imports: stdlib, then third-party, then local (ruff sorts these)
import json
from datetime import datetime
from typing import Protocol

import pandas as pd
from psycopg import Connection

from ingest import MarketRow

# Type hints are expected on public functions
def upsert_market(conn: Connection, row: MarketRow) -> int:
    """Store a market row, return market_id.
    
    Idempotent on (venue, external_id): re-running with the same market
    updates the row in place, never duplicates.
    """
    # One-line comment on the why, not the what — the code says what it does
    # Only comment when the why is non-obvious (constraints, tradeoffs, workarounds)
    pass

# Private helpers: leading underscore
def _parse_field(value: str | None) -> float | None:
    """Parse a field that might be missing."""
    pass
```

#### Docstring Style

- **Public APIs:** one-line summary, then multi-line explanation if needed
- **Private functions:** minimal (the name should be clear)
- **No examples in docstrings** — put them in tests or the module docstring

```python
def candlesticks(self, token_id: str, *, start: datetime, end: datetime) -> list[Candle]:
    """Fetch candlesticks for a token in a time range.
    
    start and end must be timezone-aware datetimes (UTC recommended).
    Returns candlesticks in chronological order, oldest first.
    """
```

### 4. Testing

#### What to Test

- **Unit tests:** parsing, math, edge cases (no network, no DB)
- **Integration tests:** round-trip through the store, fixture API responses
- **Accept fixture responses, not live network** (CI must be deterministic)

#### Running Tests

```bash
make test              # Run all tests
make test-parallel     # Run in parallel (faster)
make coverage          # Coverage report (htmlcov/index.html)

pytest tests -v -k test_foo  # Single test
pytest tests -v -m integration  # Integration tests only
```

#### Test Organization

```python
# tests/test_ingest_kalshi.py
def test_candlesticks_parses_valid_response():
    """Happy path: candlesticks() returns Candles from valid JSON."""
    pass

def test_candlesticks_rejects_out_of_range_ohlc():
    """Validation: price outside [0,1] raises KalshiAPIError."""
    pass

def test_candlesticks_with_no_trades_uses_bid_ask_midpoint():
    """Fallback: when price fields are null, use yes_bid/yes_ask midpoint."""
    pass

@pytest.mark.integration
def test_roundtrip_market_and_candles_to_store():
    """Integration: markets and candles survive write/read to Postgres."""
    pass
```

### 5. Submitting a PR

1. **Push your branch** and open a PR against `main`
2. **Write a clear PR description** — what changed, why, what was tested
3. **Link any related issues** or ADRs
4. **Ensure CI passes** (lint, type-check, tests)
5. **Request review** from the project owner
6. **Respond to feedback** — keep the conversation professional

#### PR Template

```markdown
## Summary
One-sentence summary of what this PR does.

## Why
Why is this change needed? (context, problem, decision)

## Changes
- Bullet list of changes
- Mentions of ADRs or WPs if relevant

## Testing
- [x] Unit tests for parsing logic
- [x] Integration test with real fixture response
- [x] Manual demo verification

## Checklist
- [x] Linting passes (ruff, mypy, bandit)
- [x] Tests pass locally and in CI
- [x] No breaking changes to public APIs
- [x] CONTEXT.md or ADRs updated if docs needed
```

## Common Tasks

### Adding a dependency

1. Add to `pyproject.toml` (`dependencies` or `dev`)
2. Update `requirements.txt` or `requirements-dev.txt`
3. Reinstall: `pip install -r requirements.txt -r requirements-dev.txt`

### Running demos

```bash
make demo-store    # python src/store.py
make demo-ingest   # python src/ingest_kalshi.py
make demo-fees     # python src/fees.py
make demo-ev       # python src/ev_detector.py
```

### Cleaning up

```bash
make clean        # Remove caches and artifacts
make clean-all    # Also remove .venv
```

## Tools Reference

| Tool | Purpose | Config |
|------|---------|--------|
| **ruff** | Linting + formatting (E, W, F, I, B, etc.) | `pyproject.toml` [tool.ruff] |
| **black** | Code formatter (backup, ruff is primary) | `pyproject.toml` [tool.black] |
| **mypy** | Static type checking | `pyproject.toml` [tool.mypy] |
| **pytest** | Test runner | `pyproject.toml` [tool.pytest] |
| **pre-commit** | Git hooks framework | `.pre-commit-config.yaml` |
| **bandit** | Security scanning | `pyproject.toml` [tool.bandit] |

## Architecture & Decisions

The design is documented in:
- **[docs/architecture/overview.md](docs/architecture/overview.md)** — system context, data model, contracts
- **[docs/architecture/plan.md](docs/architecture/plan.md)** — implementation plan (WP-1 through WP-8)
- **[docs/architecture/decisions/](docs/architecture/decisions/)** — ADR-0001 through ADR-0010

When making a decision that affects structure or approach, document it in an ADR rather than burying it in comments. Use the template at [docs/architecture/decisions/](docs/architecture/decisions/).

## Questions?

- Read [CONTEXT.md](CONTEXT.md) for domain language
- Check the [README.md](README.md) for setup and usage
- Look at recent commits and PRs for examples of accepted patterns
- Open a discussion or issue if unsure

Thank you for contributing!
