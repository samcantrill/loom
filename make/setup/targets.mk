.PHONY: setup-help install

setup-help:
	@printf 'Loom setup targets\n'
	@printf '\n'
	@printf 'Setup:\n'
	@printf '  make install       Install all dependency groups\n'

install:
	uv sync --all-groups
