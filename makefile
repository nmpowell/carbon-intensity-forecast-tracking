# Virtualenv

# Requirements for scraping and analysis
install:
	pip install pip==23.0 pip-tools==6.12.3
	pip-sync

# Requirements for development and testing
install-dev:
	pip install pip==23.0 pip-tools==6.12.3
	pip-sync requirements-dev.txt

# Static analysis

check: black isort flake8 mypy test

mypy:
	mypy .

black:
	black --check .

isort:
	isort --check .

flake8:
	flake8

# Testing

test:
	pytest -v tests
