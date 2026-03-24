.PHONY: \
	install uninstall reinstall \
	check check-format check-lint typecheck \
	fix \
	lint format \
	pre-commit

install:
	uv tool install --editable .

uninstall:
	uv tool uninstall kaleido-cli

reinstall: uninstall install

check-format:
	uvx ruff format --check .

check-lint:
	uvx ruff check .

check: check-format check-lint typecheck

lint:
	uvx ruff check --fix .

format:
	uvx ruff format .

typecheck:
	uvx --with . pyright .

fix: format lint

pre-commit: check
