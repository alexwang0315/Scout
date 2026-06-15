PYTHON ?= python3

.PHONY: install test governance rollback

install:
	$(PYTHON) -m pip install -U pip
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest -q tests/test_example_scout_skill_schemas.py
	$(PYTHON) scripts/codex_checklist_validate.py

governance:
	$(PYTHON) scripts/codex_checklist_validate.py

rollback:
	@echo "Rollback hook placeholder: wire this to your deploy system or feature flag manager."
