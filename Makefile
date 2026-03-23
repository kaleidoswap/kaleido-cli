.PHONY: install uninstall reinstall lint format typecheck pre-commit

install:
	uv tool install --editable .

uninstall:
	uv tool uninstall kaleido-cli

reinstall: uninstall install

lint:
	uvx ruff check --fix .

format:
	uvx ruff format .

typecheck:
	uvx pyright .

pre-commit: lint typecheck format
