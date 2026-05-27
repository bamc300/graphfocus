.PHONY: install dev test lint format clean serve

install:
	pip install -e .

dev:
	pip install -e ".[all,dev]"

test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=graphfocus --cov-report=html

lint:
	ruff check graphfocus/ tests/

format:
	ruff format graphfocus/ tests/

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

serve:
	uvicorn graphfocus.api.app:app --reload --port 8000

analyze:
	python -m graphfocus analyze .

languages:
	python -m graphfocus languages
