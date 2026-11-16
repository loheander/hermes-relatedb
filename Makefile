.PHONY: test install

test:
	uv run pytest tests/

install:
	uv sync
