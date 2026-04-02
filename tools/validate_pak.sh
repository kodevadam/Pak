#!/usr/bin/env bash
# validate_pak.sh — Run the Pak compiler checker on one or more .pak files.
#
# Usage:
#   tools/validate_pak.sh file.pak
#   tools/validate_pak.sh src/*.pak
#   tools/validate_pak.sh          # checks all .pak files in the project
#
# Exit codes:
#   0 — all files passed
#   1 — one or more errors found
#
# This is the mechanical enforcement layer. If pak check fails,
# the code is wrong. Fix the errors reported before proceeding.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

# Ensure pak is installed
if ! command -v pak &>/dev/null; then
    echo "ERROR: 'pak' not found. Install with: pip install -e ." >&2
    exit 1
fi

# Run check
if [ $# -eq 0 ]; then
    pak check
else
    pak check "$@"
fi
