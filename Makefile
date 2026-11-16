.PHONY: test sync install setup-git index-specs

PLUGIN_NAME := relatedb-memory
PLUGIN_FILES := plugin.yaml __init__.py config_schema.py cli.py README.md relatedb_memory skills

test:
	uv run pytest tests/

sync:
	uv sync

install:
	@root="$${HERMES_HOME:-$$HOME/.hermes}"; \
	installed=0; \
	for profile in "$$root" "$$root"/profiles/*; do \
		[ -d "$$profile" ] || continue; \
		dest="$$profile/plugins/$(PLUGIN_NAME)"; \
		mkdir -p "$$dest"; \
		rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' $(PLUGIN_FILES) "$$dest/"; \
		echo "Installed $(PLUGIN_NAME) plugin to $$dest"; \
		installed=$$((installed + 1)); \
	done; \
	if [ "$$installed" -eq 0 ]; then \
		echo "No Hermes profile directories found under $$root" >&2; \
		exit 1; \
	fi

# Render the committed Relate graph snapshot readably in `git diff` (needs jq).
setup-git:
	git config diff.relate-json.textconv "jq ."

# Refresh docs/context-graph/ from docs/adr/, specs/ and the package modules.
index-specs: setup-git
	uv run python tools/index_specs.py
