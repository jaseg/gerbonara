
PYTHON ?= python
PYTEST ?= pytest

.PHONY: clean
clean: doc-clean
	find . -name '*.pyc' -delete
	rm -rf *.egg-info
	rm -f .coverage
	rm -f coverage.xml

.PHONY: test
test:
	$(PYTEST)

.PHONY: test-coverage
test-coverage:
	rm -f .coverage
	rm -f coverage.xml
	$(PYTEST) --cov=./ --cov-report=xml 

.PHONY: install
install:
	PYTHONPATH=. $(PYTHON) setup.py install

sdist:
	python3 setup.py sdist

bdist_wheel:
	python3 setup.py bdist_wheel

upload: sdist bdist_wheel
	twine upload -s -i contact@gerbonara.io --config-file ~/.pypirc --skip-existing --repository pypi dist/*

testupload: sdist bdist_wheel
	twine upload --config-file ~/.pypirc --skip-existing --repository testpypi dist/*

