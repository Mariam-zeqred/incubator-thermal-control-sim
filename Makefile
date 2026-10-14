.PHONY: install check test lint figures app clean

PY ?= python

install:
	$(PY) -m pip install -r requirements.txt

lint:
	$(PY) -m ruff check src tests scripts app
	$(PY) -m ruff format --check src tests scripts app

test:
	$(PY) -m pytest -q

# "make check" is the smoke test: lint + unit tests + regenerate every figure and results.json.
check: lint test figures

figures:
	$(PY) scripts/make_figures.py

app:
	$(PY) -m streamlit run app/streamlit_app.py

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
