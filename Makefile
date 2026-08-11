.PHONY: install run scan demo test check

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt

run:
	. .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000

scan:
	. .venv/bin/activate && python -m scripts.scan_once

demo:
	. .venv/bin/activate && python -m scripts.seed_demo

test:
	. .venv/bin/activate && python -m unittest discover -s tests -v

check:
	python3 -m compileall app scripts tests

