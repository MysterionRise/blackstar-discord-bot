"""Print the CHANGELOG.md section for a release tag, refusing a mismatched version.

Used by .github/workflows/release.yml:

    python scripts/release_notes.py v0.2.0 > release_notes.md

The hand-written Keep a Changelog file is the release record, so the notes come
from it rather than from commit messages. The tag must match the version in
pyproject.toml, so a tag cannot publish code that claims a different version.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def release_notes(changelog_text: str, version: str) -> str:
    """Return the body of the ``## [version]`` section of a Keep a Changelog file."""
    heading = re.compile(rf"^## \[{re.escape(version)}\](?:\s.*)?$")
    body: list[str] | None = None
    for line in changelog_text.splitlines():
        if body is None:
            if heading.match(line):
                body = []
            continue
        if line.startswith("## "):
            break
        body.append(line)

    if body is None:
        msg = f"CHANGELOG.md has no '## [{version}]' section"
        raise ValueError(msg)
    notes = "\n".join(body).strip()
    if not notes:
        msg = f"CHANGELOG.md section for {version} is empty"
        raise ValueError(msg)
    return notes


def project_version(pyproject_text: str) -> str:
    """Return ``[project].version`` from pyproject.toml content."""
    version = tomllib.loads(pyproject_text)["project"]["version"]
    if not isinstance(version, str):
        msg = "pyproject.toml [project].version is not a string"
        raise TypeError(msg)
    return version


def main(argv: list[str], root: Path = ROOT) -> int:
    """Print release notes for the tag in *argv*; return a process exit code."""
    if len(argv) != 1:
        sys.stderr.write("usage: release_notes.py vX.Y.Z\n")
        return 2
    tag = argv[0]
    version = tag.removeprefix("v")

    expected = project_version((root / "pyproject.toml").read_text(encoding="utf-8"))
    if version != expected:
        sys.stderr.write(
            f"Tag {tag} does not match pyproject.toml version {expected}; "
            "bump the version before tagging.\n"
        )
        return 1

    try:
        notes = release_notes((root / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write(notes + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
