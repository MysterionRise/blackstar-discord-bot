# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

### Added

- Project scaffold: source layout, CI, pre-commit hooks, agent prompts
- `pyproject.toml` with full tool configuration (ruff, mypy, pytest, bandit)
- GitHub Actions CI pipeline (lint, typecheck, test, security)
- GitHub issue and PR templates
- Claude Code agentic team configuration (orchestrator + 4 specialist agents)
- Runtime backend selection, device listing, status, and volume slash commands
- Safer stream startup cleanup, voice connect retry, and playback diagnostics
