.PHONY: install fmt lint type test cov check clean

install:
	python -m pip install -e ".[dev]"

fmt:
	ruff format atom tests
	ruff check --fix atom tests

lint:
	ruff check atom tests
	ruff format --check atom tests
	lint-imports

type:
	mypy --python-executable=$$(which python3) atom

test:
	pytest

cov:
	pytest --cov --cov-report=term-missing

check: lint type test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
