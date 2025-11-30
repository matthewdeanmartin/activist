ifeq ($(origin VIRTUAL_ENV),undefined)
    VENV := uv run
else
    VENV :=
endif

uv.lock: pyproject.toml
	@echo "Installing dependencies"
	@uv sync


# tests can't be expected to pass if dependencies aren't installed.
# tests are often slow and linting is fast, so run tests on linted code.
test: uv.lock
	@echo "Running unit tests"
	$(VENV) pytest --doctest-modules activist
	# $(VENV) python -m unittest discover
	$(VENV) py.test tests -vv --cov=activist --cov-report=html --cov-fail-under 80
	$(VENV) bash basic_help.sh


isort:  
	@echo "Formatting imports"
	$(VENV) isort .

black:  isort 
	@echo "Formatting code"
	$(VENV) metametameta poetry
	$(VENV) black activist --exclude .venv
	$(VENV) black tests --exclude .venv
	# $(VENV) black scripts --exclude .venv

pre-commit:  isort black
	@echo "Pre-commit checks"
	$(VENV) pre-commit run --all-files

bandit:  
	@echo "Security checks"
	$(VENV)  bandit activist -r

.PHONY: pylint
pylint:  isort black 
	@echo "Linting with pylint"
	$(VENV) pylint activist --fail-under 9.8 --ignore-paths=test_TODO
	$(VENV) ruff --fix

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


get_policies:
	python -m policy_fetcher --server-list servers.txt