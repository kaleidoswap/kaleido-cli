.PHONY: install uninstall reinstall

install:
	uv tool install --editable .

uninstall:
	uv tool uninstall kaleido-cli

reinstall: uninstall install
