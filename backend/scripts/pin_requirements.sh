#!/usr/bin/env bash
# Builds requirements.lock: every dependency (and its dependencies) at an exact version, resolved in a CLEAN
# virtual environment so nothing from your own machine leaks in.
#
#   scripts/pin_requirements.sh            # keep the versions already in requirements.lock where possible
#   scripts/pin_requirements.sh --upgrade  # move everything to the newest allowed versions
#
# Then: run the tests, commit requirements.lock, and point the Render / AWS build command at it:
#   pip install -r requirements.lock
# (requirements.txt keeps working until then.)
set -euo pipefail

BACKEND="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BACKEND"
VENV="$(mktemp -d)/venv"
UPGRADE=""
[ "${1:-}" = "--upgrade" ] && UPGRADE="--upgrade"

python3 -m venv "$VENV"
# shellcheck disable=SC1091
. "$VENV/bin/activate"
python -m pip install --quiet --upgrade pip pip-tools

if python -m piptools --version >/dev/null 2>&1; then
  python -m piptools compile $UPGRADE --quiet --strip-extras --resolver=backtracking \
    --output-file requirements.lock requirements.in
else
  # Fallback: install the direct dependencies, then freeze what pip chose.
  python -m pip install --quiet -r requirements.in
  python -m pip freeze --exclude-editable | sort > requirements.lock
fi

echo "Wrote $BACKEND/requirements.lock ($(grep -cE '^[A-Za-z0-9]' requirements.lock) packages)."
echo "Review it, run the tests, then commit it."