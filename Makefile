.PHONY: setup dev contracts check test full release
setup:
	python3 tools/bootstrap.py
dev:
	python3 tools/dev.py
contracts:
	python3 tools/export_contracts.py
check:
	python3 tools/check.py --affected
test:
	python3 tools/check.py --affected
full:
	python3 tools/check.py --full --jobs 3
release:
	python3 tools/check.py --release --jobs 3
