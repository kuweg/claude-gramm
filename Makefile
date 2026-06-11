# engram — build + test glue (DESIGN §7)
.PHONY: build install uninstall test test-rust test-python lint backfill process dry-run clean

VENV   := pipeline/.venv
PY     := $(VENV)/bin/python
BINDIR := $(HOME)/.local/bin
PARSER := $(CURDIR)/target/release/engram-parse

build:
	cargo build --release
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PY) -m pip install -q -e pipeline

# Symlink engram-parse onto your PATH so the Python side can find it.
install: build
	@mkdir -p $(BINDIR)
	ln -sf $(PARSER) $(BINDIR)/engram-parse
	@echo "linked $(BINDIR)/engram-parse -> $(PARSER)"
	@case ":$$PATH:" in *":$(BINDIR):"*) ;; \
	  *) echo "NOTE: $(BINDIR) is not on your PATH — add it to your shell profile:"; \
	     echo '      export PATH="$(BINDIR):$$PATH"' ;; esac

uninstall:
	rm -f $(BINDIR)/engram-parse
	@echo "removed $(BINDIR)/engram-parse"

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
