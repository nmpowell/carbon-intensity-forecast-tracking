# Virtualenv

install:
	pip install pip==23.0 pip-tools==6.12.3
	pip-sync

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
