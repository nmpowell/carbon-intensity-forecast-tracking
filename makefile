# Virtualenv

install:
	pip install pip==23.0 pip-tools==6.12.3
	pip-sync

install-minimal:
	pip install pip==23.0 pip-tools==6.12.3
	pip-sync requirements-minimal.txt

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
