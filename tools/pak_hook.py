#!/usr/bin/env python3
"""
pak_hook.py — Claude Code PostToolUse hook for automatic Pak validation.

Claude Code calls this after every Write or Edit tool use, passing the
tool input as JSON on stdin. This script:

  1. Reads the tool input JSON from stdin.
  2. Extracts the file path.
  3. Skips non-.pak files silently.
  4. Runs `pak check` on the file.
  5. If errors are found, prints them and exits with code 2.
     Claude Code surfaces the output to Claude, which must fix the
     errors before continuing.
  6. If clean, runs `pak explain` and prints the generated C so Claude
     can verify the semantics match intent, then exits 0.

Exit codes:
  0 — file is valid (or not a .pak file, no action needed)
  2 — pak check failed; errors printed to stdout for Claude to read

Environment variables:
  PAK_HOOK_NO_EXPLAIN=1  — skip the pak explain step (faster, less output)
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    # Read tool input from stdin
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Can't parse input — skip silently
        sys.exit(0)

    # Extract file path from Write or Edit tool input
    file_path = (
        data.get("file_path")      # Write tool
        or data.get("path")        # alternative key
    )

    if not file_path:
        sys.exit(0)

    path = Path(file_path)

    # Only act on .pak files
    if path.suffix != ".pak":
        sys.exit(0)

    # Run pak check on the file
    try:
        result = subprocess.run(
            ["pak", "check", str(path)],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("WARNING: 'pak' not found — cannot validate. Install with: pip install -e .")
        sys.exit(0)

    if result.returncode != 0:
        print("=" * 60)
        print(f"PAK VALIDATION FAILED: {path}")
        print("=" * 60)
        if result.stderr.strip():
            print(result.stderr.strip())
        if result.stdout.strip():
            print(result.stdout.strip())
        print()
        print("Fix the errors above before proceeding.")
        print("Reference LANGUAGE.md and NOT_SUPPORTED.md.")
        print("=" * 60)
        sys.exit(2)

    # Clean — optionally run pak explain for semantic verification
    if os.environ.get("PAK_HOOK_NO_EXPLAIN") == "1":
        sys.exit(0)

    try:
        explain = subprocess.run(
            ["pak", "explain", str(path)],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        sys.exit(0)

    if explain.returncode == 0 and explain.stdout.strip():
        print("=" * 60)
        print(f"PAK EXPLAIN: {path}")
        print("=" * 60)
        print(explain.stdout.strip())
        print("=" * 60)
        print("Review the generated C above. If it does not match your intent,")
        print("fix the Pak source — the file passed pak check but may be semantically wrong.")
        print("=" * 60)

    sys.exit(0)


if __name__ == "__main__":
    main()
