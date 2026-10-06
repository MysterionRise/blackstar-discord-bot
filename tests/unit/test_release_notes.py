"""Tests for scripts/release_notes.py, which builds GitHub Release notes."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("release_notes", ROOT / "scripts/release_notes.py")
assert _spec is not None and _spec.loader is not None
release_notes_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_notes_module)
release_notes = release_notes_module.release_notes
main = release_notes_module.main

CHANGELOG = """# Changelog

Intro text.

## [0.2.0] - 2026-11-01

### Added

- Second release feature

## [0.1.0] - Unreleased

### Fixed

- First release fix
"""


def test_extracts_a_section_between_two_versions():
    assert release_notes(CHANGELOG, "0.2.0") == "### Added\n\n- Second release feature"


def test_extracts_the_last_section_with_an_unreleased_suffix():
    assert release_notes(CHANGELOG, "0.1.0") == "### Fixed\n\n- First release fix"


def test_does_not_match_a_version_prefix():
    with pytest.raises(ValueError, match=r"no '## \[0.2\]' section"):
        release_notes(CHANGELOG, "0.2")


def test_missing_version_is_an_error():
    with pytest.raises(ValueError, match="no '## \\[9.9.9\\]' section"):
        release_notes(CHANGELOG, "9.9.9")


def test_empty_section_is_an_error():
    with pytest.raises(ValueError, match="empty"):
        release_notes("## [1.0.0]\n\n## [0.9.0]\n- x\n", "1.0.0")


def _project(tmp_path, version, changelog=CHANGELOG):
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    return tmp_path


def test_main_prints_notes_for_a_matching_tag(tmp_path, capsys):
    assert main(["v0.2.0"], root=_project(tmp_path, "0.2.0")) == 0
    assert capsys.readouterr().out == "### Added\n\n- Second release feature\n"


def test_main_refuses_a_tag_that_does_not_match_the_version(tmp_path, capsys):
    """A tag must not publish code that reports a different version."""
    assert main(["v0.3.0"], root=_project(tmp_path, "0.2.0")) == 1
    assert "does not match pyproject.toml version 0.2.0" in capsys.readouterr().err


def test_main_fails_when_the_changelog_has_no_section(tmp_path, capsys):
    assert main(["v0.3.0"], root=_project(tmp_path, "0.3.0")) == 1
    assert "no '## [0.3.0]' section" in capsys.readouterr().err


def test_main_requires_exactly_one_tag(tmp_path):
    assert main([], root=_project(tmp_path, "0.2.0")) == 2


def test_real_changelog_has_notes_for_the_current_version():
    """The repository's own CHANGELOG.md and pyproject.toml must stay releasable."""
    version = release_notes_module.project_version((ROOT / "pyproject.toml").read_text())
    notes = release_notes((ROOT / "CHANGELOG.md").read_text(), version)
    assert "### Added" in notes
