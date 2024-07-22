# isort . && black . && bandit -r . && pylint && pre-commit run --all-files
# Get changed files

FILES := $(wildcard activist/**/*.py)

# if you wrap everything in poetry run, it runs slower.
ifeq ($(origin VIRTUAL_ENV),undefined)
    VENV := poetry run
else
    VENV :=
endif

poetry.lock: pyproject.toml
	@echo "Installing dependencies"
	@poetry install --with dev

clean-pyc:
	@echo "Removing compiled files"
	find test -name '__pycache__' -exec rm -fr {} + || true
	find test -name '*.pyc' -exec rm -f {} + || true
	find activist -name '*.pyc' -exec rm -f {} + || true
# 	@find activist -name '*.pyc' -exec rm -f {} + || true
#	@find activist -name '*.pyo' -exec rm -f {} + || true
#	@find activist -name '__pycache__' -exec rm -fr {} + || true

clean-test:
	@echo "Removing coverage data"
	@rm -f .coverage || true
	@rm -f .coverage.* || true

clean: clean-pyc clean-test

# tests can't be expected to pass if dependencies aren't installed.
# tests are often slow and linting is fast, so run tests on linted code.
test: clean poetry.lock
	@echo "Running unit tests"
	$(VENV) pytest --doctest-modules activist
	# $(VENV) python -m unittest discover
	$(VENV) py.test tests -vv --cov=activist --cov-report=html --cov-fail-under 80
	$(VENV) bash basic_help.sh


.build_history:
	@mkdir -p .build_history

.build_history/isort: .build_history $(FILES)
	@echo "Formatting imports"
	$(VENV) isort .
	@touch .build_history/isort

.PHONY: isort
isort: .build_history/isort

.build_history/black: .build_history .build_history/isort $(FILES)
	@echo "Formatting code"
	$(VENV) metametameta poetry
	$(VENV) black activist --exclude .venv
	$(VENV) black tests --exclude .venv
	# $(VENV) black scripts --exclude .venv
	@touch .build_history/black

.PHONY: black
black: .build_history/black

.build_history/pre-commit: .build_history .build_history/isort .build_history/black
	@echo "Pre-commit checks"
	$(VENV) pre-commit run --all-files
	@touch .build_history/pre-commit

.PHONY: pre-commit
pre-commit: .build_history/pre-commit

.build_history/bandit: .build_history $(FILES)
	@echo "Security checks"
	$(VENV)  bandit activist -r
	@touch .build_history/bandit

.PHONY: bandit
bandit: .build_history/bandit

.PHONY: pylint
.build_history/pylint: .build_history .build_history/isort .build_history/black $(FILES)
	@echo "Linting with pylint"
	$(VENV) pylint activist --fail-under 9.8 --ignore-paths=test_TODO
	$(VENV) ruff --fix
	@touch .build_history/pylint

# for when using -j (jobs, run in parallel)
.NOTPARALLEL: .build_history/isort .build_history/black

check: mypy test pylint bandit pre-commit

.PHONY: publish_test
publish_test:
	rm -rf dist && poetry version minor && poetry build && twine upload -r testpypi dist/*

.PHONY: publish
publish: test
	rm -rf dist && poetry build

.PHONY: mypy
mypy:
	$(VENV) mypy activist --ignore-missing-imports --check-untyped-defs

.PHONY:
docker:
	docker build -t activist -f Dockerfile .

check_docs:
	$(VENV) interrogate activist --verbose
	$(VENV) pydoctest --config .pydoctest.json | grep -v "__init__" | grep -v "__main__" | grep -v "Unable to parse"

make_docs:
	pdoc activist --html -o docs --force

check_md:
	$(VENV) mdformat README.md docs/*.md
	# $(VENV) linkcheckMarkdown README.md # it is attempting to validate ssl certs
	$(VENV) markdownlint README.md --config .markdownlintrc

check_spelling:
	$(VENV) pylint activist --enable C0402 --rcfile=.pylintrc_spell
	$(VENV) codespell README.md --ignore-words=private_dictionary.txt
	$(VENV) codespell activist --ignore-words=private_dictionary.txt

check_changelog:
	# pipx install keepachangelog-manager
	$(VENV) changelogmanager validate

check_all: check_docs check_md check_spelling check_changelog

#audit:
#	# $(VENV) python -m activist audit
#	$(VENV) tool_audit single activist --version=">=2.0.0"