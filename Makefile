.PHONY: help setup install install-dev test lint format type-check clean coverage pre-commit-install docs

help:
	@echo "fairline — Kalshi prediction-market research stack"
	@echo ""
	@echo "Setup:"
	@echo "  make setup              Create virtual environment and install dependencies"
	@echo "  make install            Install production dependencies"
	@echo "  make install-dev        Install dev dependencies (linting, testing, pre-commit)"
	@echo ""
	@echo "Development:"
	@echo "  make lint               Run linter (ruff) with fixes"
	@echo "  make format             Format code (ruff + black)"
	@echo "  make type-check         Run type checker (mypy)"
	@echo "  make security-check     Run security scanner (bandit)"
	@echo "  make test               Run tests"
	@echo "  make test-parallel      Run tests in parallel"
	@echo "  make coverage           Run tests with coverage report"
	@echo "  make pre-commit-install Install git pre-commit hooks"
	@echo "  make pre-commit-run     Run pre-commit on all files"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean              Remove generated files, caches, and artifacts"
	@echo "  make clean-all          Also remove virtual environment"

# Setup
setup:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip setuptools wheel
	.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
	@echo "✓ Virtual environment created at .venv"
	@echo "✓ Run: source .venv/bin/activate"

install:
	.venv/bin/pip install -r requirements.txt

install-dev:
	.venv/bin/pip install -r requirements-dev.txt

# Linting and code quality
lint:
	.venv/bin/ruff check --fix src tests

format:
	.venv/bin/ruff check --fix src tests
	.venv/bin/ruff format src tests
	.venv/bin/black src tests --line-length 100

type-check:
	.venv/bin/mypy src

security-check:
	.venv/bin/bandit -r src -c pyproject.toml

# Testing
test:
	.venv/bin/pytest tests -v

test-parallel:
	.venv/bin/pytest tests -v -n auto

coverage:
	.venv/bin/pytest tests --cov=src --cov-report=html --cov-report=term-missing
	@echo "✓ Coverage report: htmlcov/index.html"

# Git hooks
pre-commit-install:
	.venv/bin/pre-commit install
	@echo "✓ Pre-commit hooks installed"

pre-commit-run:
	.venv/bin/pre-commit run --all-files

# Cleanup
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete
	rm -rf dist build *.egg-info
	@echo "✓ Cleaned up caches and artifacts"

clean-all: clean
	rm -rf .venv
	@echo "✓ Also removed virtual environment"

# Demo runs (repo convention: python3 src/<file>.py)
demo-store:
	.venv/bin/python src/store.py

demo-ingest:
	.venv/bin/python src/ingest_kalshi.py

demo-fees:
	.venv/bin/python src/fees.py

demo-ev:
	.venv/bin/python src/ev_detector.py

demo-risk:
	.venv/bin/python src/risk_execution.py
