PYTHON ?= python
PYTEST ?= pytest
SPHINX_BUILD ?= sphinx-build

.DEFAULT_GOAL := help

.PHONY: clean docs test test-coverage install sdist bdist_wheel upload testupload help

all: docs sdist bdist_wheel

clean:  ## Clean up project directory
	find . -name '*.pyc' -delete
	rm -rf *.egg-info
	rm -f .coverage
	rm -f coverage.xml
	rm -rf docs/_build

docs:  ## Generate documentation
	sphinx-build -E docs docs/_build

test:  ## Run tests
	$(PYTEST)

test-coverage:  ## Generate coverage
	rm -f .coverage
	rm -f coverage.xml
	$(PYTEST) --cov=./ --cov-report=xml 

install:  ## Install locally
	PYTHONPATH=. $(PYTHON) setup.py install

sdist:  ## Build source distribution
	python3 setup.py sdist

bdist_wheel:  ## Build binary distribution
	python3 setup.py bdist_wheel

upload: sdist bdist_wheel  ## Upload Python package to PyPI
	twine upload -s -i gerbonara@jaseg.de --config-file ~/.pypirc --skip-existing --repository pypi dist/*

testupload: sdist bdist_wheel  ## Upload Python package to test PyPI
	twine upload --config-file ~/.pypirc --skip-existing --repository testpypi dist/*

help:  ## Display this help
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
