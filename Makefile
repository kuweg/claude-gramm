# engram — build + test glue (DESIGN §7)
.PHONY: build test test-rust test-python lint backfill process dry-run clean

VENV := pipeline/.venv
PY   := $(VENV)/bin/python

build:
	cargo build --release
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PY) -m pip install -q -e pipeline

test: test-rust test-python

test-rust:
	cargo test
	cargo clippy --all-targets -- -D warnings

test-python:
	$(PY) -m pytest pipeline/tests -q

lint:
	cargo clippy --all-targets -- -D warnings

backfill:
	$(PY) -m engram backfill $(ARGS)

process:
	$(PY) -m engram process $(ARGS)

dry-run:
	$(PY) -m engram process --dry-run $(ARGS)

clean:
	cargo clean
	rm -rf $(VENV) pipeline/*.egg-info pipeline/src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
