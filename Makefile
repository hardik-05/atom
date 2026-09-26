.PHONY: install fmt lint type test cov check clean db-verify

# Every target runs through `python3 -m`, not the bare console scripts. The
# scripts on PATH here are uv-installed tools with their own interpreters, so
# `pytest` and `mypy` would not see the project's dependencies at all.
PY := python3

install:
	$(PY) -m pip install -e ".[dev]"

fmt:
	ruff format atom tests
	ruff check --fix atom tests

lint:
	ruff check atom tests
	ruff format --check atom tests
	lint-imports

type:
	mypy --python-executable=$$(which $(PY)) atom

test:
	$(PY) -m pytest

cov:
	$(PY) -m pytest --cov --cov-report=term-missing

# Applies every migration to a fresh schema and asserts the constraints reject
# what they exist to reject. Needs ATOM_DATABASE_URL pointing at a database you
# do not mind dropping the `atom` schema in.
db-verify:
	psql "$$ATOM_DATABASE_URL" -v ON_ERROR_STOP=1 -q \
		-c 'DROP SCHEMA IF EXISTS atom CASCADE'
	for f in atom/persistence/migrations/0*.sql; do \
		psql "$$ATOM_DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$$f" || exit 1; \
	done
	psql "$$ATOM_DATABASE_URL" -v ON_ERROR_STOP=1 -q \
		-f atom/persistence/migrations/verify_constraints.sql

check: lint type test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
