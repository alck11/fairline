# Professional Tooling Setup

This document describes the professional development tooling added to fairline on 2026-07-19.

## Overview

fairline now includes enterprise-grade Python tooling for:
- **Code quality** (linting, formatting, type checking)
- **Testing** (unit + integration, coverage reporting)
- **Security** (vulnerability scanning)
- **Automation** (pre-commit hooks, CI/CD)
- **Documentation** (development guide, contributing guidelines)

All configuration is centralized in `pyproject.toml` (modern Python packaging standard).

## What Was Added

### Configuration Files

| File | Purpose |
|------|---------|
| **pyproject.toml** | Modern Python packaging config; single source of truth for all tool settings |
| **requirements.txt** | Production dependencies (sync'd with pyproject.toml) |
| **requirements-dev.txt** | Development/testing dependencies |
| **.pre-commit-config.yaml** | Git hooks that run linters before each commit |
| **.editorconfig** | Editor-agnostic settings for formatting (tabs, line ending, etc.) |
| **.python-version** | Specifies Python 3.10 for pyenv/asdf users |
| **pytest.ini** | Pytest fallback config (primary is in pyproject.toml) |
| **Makefile** | Convenient make targets for common tasks |

### Documentation

| File | Purpose |
|------|---------|
| **CONTRIBUTING.md** | Contributing workflow, code style, PR process |
| **docs/DEVELOPMENT.md** | Full development guide (setup, tools, testing, debugging) |
| **TOOLING.md** | This file — overview of the tooling setup |

### CI/CD

| File | Purpose |
|------|---------|
| **.github/workflows/ci.yml** | GitHub Actions: runs linting, type-check, tests on every push |

### Updated

| File | Changes |
|------|---------|
| **README.md** | Added setup shortcuts, professional tooling table |
| **requirements.txt** | Clarified structure, added comments |
| **.gitignore** | Expanded to cover caches, artifacts, IDEs |

## Tools Installed

### Primary Tools

#### ruff (v0.5.0+) — Linting & Formatting
- Fast Rust-based linter (10–100x faster than flake8)
- Replaces: flake8, pylint, black, isort (all in one)
- Rules: E, W, F, I, C4, UP, B, A, C90, SIM, RUF
- **Usage:** `make lint`, `make format`, or `ruff check --fix src tests`
- Config: `pyproject.toml` [tool.ruff]

#### mypy (v1.11.0+) — Type Checking
- Static type checker for Python
- Enforces type hints on functions, catches type errors before runtime
- **Usage:** `make type-check` or `mypy src`
- Config: `pyproject.toml` [tool.mypy]

#### pytest (v8.0.0+) — Testing
- Modern test framework, no boilerplate needed
- Fixture-based (no network calls in CI — responses are recorded)
- Parallel execution with pytest-xdist
- **Usage:** `make test`, `make test-parallel`, or `pytest tests -v`
- Config: `pyproject.toml` [tool.pytest]

#### black (v24.4.0+) — Code Formatting
- Opinionated Python code formatter
- Used as a fallback (ruff is primary)
- **Usage:** `make format` or `black src tests --line-length 100`
- Config: `pyproject.toml` [tool.black]

#### pre-commit (v3.7.0+) — Git Hooks
- Runs linters/checks before commits, prevents bad code from being committed
- Includes: ruff (lint + format), mypy, bandit, pydocstyle, trailing whitespace, YAML checks, etc.
- **Usage:** `make pre-commit-install` (one-time), then automatic on each commit
- Config: `.pre-commit-config.yaml`

#### bandit (v1.7.5+) — Security Scanning
- Scans for common security issues: SQL injection, hardcoded secrets, insecure crypto
- **Usage:** `make security-check` or `bandit -r src -c pyproject.toml`
- Config: `pyproject.toml` [tool.bandit] (can be configured)

### Supporting Tools

- **pytest-cov** — Coverage reporting (`make coverage`)
- **pytest-xdist** — Parallel test execution (`make test-parallel`)
- **isort** — Import sorting (run via ruff, dual-mode for compatibility)
- **python-dotenv** — Load environment variables from `.env` files
- **pgserver** — Test-only; auto-creates throwaway Postgres for tests

## Quick Start

### One-Time Setup
```bash
make setup
source .venv/bin/activate
make pre-commit-install
```

### Before Every Commit
```bash
make lint        # Auto-fix linting
make format      # Format code
make type-check  # Type checking
make test        # Run tests
```

Or let pre-commit hooks do it automatically on commit.

### Running Individual Tools
```bash
ruff check --fix src tests              # Linting with auto-fix
ruff format src tests                   # Formatting only
mypy src                                # Type checking
pytest tests -v                         # Run tests
pytest tests --cov=src                  # With coverage
bandit -r src -c pyproject.toml         # Security scan
```

### Other Make Targets
```bash
make help                   # Show all targets
make lint                   # Auto-fix linting issues
make format                 # Format code with black
make type-check             # Type check with mypy
make test                   # Run tests
make test-parallel          # Tests in parallel
make coverage               # Coverage report
make security-check         # Security scan
make clean                  # Remove caches/artifacts
make clean-all              # Also remove .venv
make pre-commit-install     # Install git hooks
make pre-commit-run         # Run hooks on all files
```

## Configuration

All tool settings are in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py310"
# ... rules, imports, etc.

[tool.mypy]
python_version = "3.10"
check_untyped_defs = true
# ... type checking options

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["-v", "--strict-markers", "--tb=short"]
# ... test configuration

[tool.black]
line-length = 100
target-version = ["py310"]
# ... formatter options

[tool.coverage.run]
branch = true
source = ["src"]
# ... coverage options
```

For `.pre-commit-config.yaml`, individual hooks are configured; critical ones:
- ruff (lint + format)
- mypy (type checking)
- bandit (security)
- pydocstyle (docstrings)

## CI/CD: GitHub Actions

`.github/workflows/ci.yml` runs on every push to `main` or `develop`:

1. **Lint** — ruff, black format check, mypy, bandit (fails if issues found)
2. **Test** — pytest on Python 3.10, 3.11, 3.12 (in parallel)
3. **Coverage** — pytest-cov, uploads to codecov.io
4. **Pre-commit** — runs full pre-commit suite

Skips in CI (run locally): mypy, bandit (slow; can be conditional)

## Code Style

The setup enforces:

### Python Formatting
- **Line length:** 100 characters (black/ruff standard)
- **Indentation:** 4 spaces
- **Imports:** sorted by ruff (stdlib → third-party → local), PEP 8
- **Quotes:** double quotes (ruff default, configurable with skip-string-normalization)

### Type Hints
- Public functions: full type hints
- Private functions: hints encouraged but not required
- Classes: on `__init__`, `__call__`, etc.
- `Protocol` for interfaces (ADR-0009)

### Comments
- Only on the *why*, not the *what*
- No multi-line comment blocks (ruff flags these)
- Docstrings: one-line for simple functions, multi-line for public APIs

### Error Handling
- **Fail loud:** raise exceptions, never silently drop errors
- **Validate at boundaries:** user input, API responses, database reads
- **Trust internals:** no defensive checks between trusted code

## Workflow

### Making Changes
1. Make code changes
2. Run `make lint`, `make format`, `make type-check`
3. Run `make test`
4. Commit (pre-commit hooks run automatically)
5. Push (GitHub Actions runs CI)

### In CI (GitHub Actions)
1. Lint (ruff, black, mypy, bandit)
2. Test (Python 3.10, 3.11, 3.12)
3. Coverage (upload to codecov)
4. Pre-commit (all hooks)

### Failing Checks
- **Ruff:** `make lint` auto-fixes most issues; review and commit
- **Black:** `make format` fixes formatting
- **MyPy:** Fix type hints based on error message
- **Pytest:** Fix the test or the code
- **Bandit:** Security issue — must be addressed or explicitly ignored

## Development Guides

- **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** — Full dev setup and workflows
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — PR process and code style
- **[README.md](README.md)** — Setup and quick start

## Notes

### Why This Setup?

1. **Professional standard** — Fortune 500 Python projects use ruff, mypy, pytest
2. **Fast feedback** — Pre-commit hooks catch issues before pushing
3. **Consistency** — One config file (pyproject.toml), no tool-by-tool setup
4. **Maintainable** — Clear code, type hints catch bugs, tests prevent regressions
5. **Scalable** — As the codebase grows, these tools scale with it

### ruff vs. pylint/flake8

ruff replaces flake8 + pylint + black + isort in one tool:
- **100x faster** (written in Rust)
- **Fewer config files** (one tool, one config)
- **Modern rules** (including simplifications and upgrades like pyupgrade)
- **Same strictness** (E, W, F rules are identical to flake8)

### mypy Strictness

The setup uses `check_untyped_defs = true` (flag functions without type hints) but not `strict = true` (too aggressive for a research codebase). If you want to be stricter, set `strict = true` in `[tool.mypy]`.

### Pre-commit Performance

Pre-commit runs on every commit. To skip:
```bash
git commit --no-verify
```

To make it faster, you can run slower checks (mypy, bandit) only in CI, not on commit. Update `.pre-commit-config.yaml` if desired.

## Troubleshooting

### "I broke the build with a linting change"
Run locally first:
```bash
make lint
make type-check
make test
```

### "I want to skip a linting rule on one line"
```python
x = dangerous_operation()  # noqa: E501
```

For type checking:
```python
x = 42  # type: ignore
```

### "My type hint is too complex"
Use `typing.TypeVar` or `typing.Generic` for cleaner signatures. Or mark the line `# type: ignore` and add a comment explaining why.

### "Tests are slow"
```bash
make test-parallel  # Run with -n auto (uses all cores)
pytest tests -k test_fast  # Run only fast tests
```

### "I want to check coverage on a single file"
```bash
pytest tests --cov=src.store --cov-report=term-missing
```

## Further Reading

- [python-packaging.readthedocs.io](https://python-packaging.readthedocs.io/) — pyproject.toml spec
- [docs.astral.sh/ruff](https://docs.astral.sh/ruff/) — ruff documentation
- [mypy.readthedocs.io](https://mypy.readthedocs.io/) — mypy documentation
- [pytest.org](https://pytest.org/) — pytest documentation
- [pre-commit.com](https://pre-commit.com/) — pre-commit documentation

