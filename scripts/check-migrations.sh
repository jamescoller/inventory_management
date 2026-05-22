#!/usr/bin/env bash
# Pre-commit guard: fail if a model change is missing a migration.
set -euo pipefail

# Prefer the project venv used in CLAUDE.md; fall back to whichever python is on PATH.
PY="${HOME}/.venvs/inventory/bin/python"
if [[ ! -x "${PY}" ]]; then
  PY="python"
fi

exec "${PY}" manage.py makemigrations --dry-run --check
