.PHONY: test install setup-git index-specs

test:
	uv run pytest tests/

install:
	uv sync

# Render the committed Relate graph snapshot readably in `git diff` (needs jq).
setup-git:
	git config diff.relate-json.textconv "jq ."

# Refresh docs/context-graph/ from docs/adr/, specs/ and the package modules.
index-specs: setup-git
	uv run python tools/index_specs.py
