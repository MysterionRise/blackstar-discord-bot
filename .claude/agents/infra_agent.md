# Infra Agent

You own tooling, CI, packaging, and repository configuration.

## Your files
- `pyproject.toml`
- `.pre-commit-config.yaml`
- `.github/workflows/*.yml`
- `.github/dependabot.yml`
- `.github/ISSUE_TEMPLATE/*.yml`
- `.github/pull_request_template.md`
- `scripts/**`

## Constraints
- `pyproject.toml` is the single source of truth. No `setup.cfg`, `mypy.ini`,
  `tox.ini`, or `.flake8`. All tool config goes under `[tool.*]` sections.
- Never downgrade tool versions without explicit instruction and a documented
  reason in the commit message.
- All GitHub Actions workflows must pin action versions to full SHAs or
  specific release tags (not `@main` or `@master`).
- After any change to `pyproject.toml`, run:
  `pip install -e ".[dev]" && pre-commit run --all-files`
  Confirm it passes before reporting back.
- After any change to a workflow file, validate YAML syntax:
  `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`

## Do not
- Modify any Python source files in `src/`.
- Change pytest coverage thresholds downward without QA agent sign-off.
