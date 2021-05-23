PROJECT = "desec_dns_api"

.PHONY: all clean sdist bdist_wheel test coverage html upload testupload

all: sdist bdist_wheel

clean:
	rm -rf .pytest_cache/
	rm -rf build/
	rm -rf ${PROJECT}.egg-info/
	rm -rf dist/
	rm -rf htmlcov/
	rm -rf .coverage

sdist:
	python3 setup.py sdist

bdist_wheel:
	python3 setup.py bdist_wheel

test:
	pytest --flake8 tests/

coverage:
	pytest --cov=${PROJECT} tests/

html:
	pytest --cov-report html:htmlcov --cov=${PROJECT} tests/

upload: sdist bdist_wheel
	twine upload -s -i contact@gerbonara.io --config-file ~/.pypirc --skip-existing --repository pypi dist/*

testupload: sdist bdist_wheel
	twine upload --config-file ~/.pypirc --skip-existing --repository testpypi dist/*
