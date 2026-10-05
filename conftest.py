"""Shared fixtures live in `testsupport/`, which mypy checks.

They are not defined here because mypy would see two `conftest` modules (this one and the
pipeline tests' one).
"""

pytest_plugins = ["testsupport.postgres"]
