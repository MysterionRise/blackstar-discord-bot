"""The package version must come from pyproject.toml alone."""

import tomllib
from pathlib import Path

import blackstar_bot

ROOT = Path(__file__).resolve().parents[2]


def test_package_version_matches_pyproject():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert blackstar_bot.__version__ == pyproject["project"]["version"]
