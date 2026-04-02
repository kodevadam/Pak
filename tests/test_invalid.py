"""
tests/test_invalid.py — Verify that invalid Pak programs fail with the expected error codes.

Each .pak file in tests/invalid/ must contain a comment of the form:
    -- EXPECT: EXXX
where EXXX is the error code the compiler should emit.

The test runner:
1. Runs `pak check <file>` on each test file individually.
2. Verifies the process exits non-zero (compilation failed).
3. Verifies the expected error code appears in stderr output.
"""

import subprocess
import sys
import re
from pathlib import Path

INVALID_DIR = Path(__file__).parent / "invalid"
EXPECT_RE = re.compile(r"--\s*EXPECT:\s*(E\d+)")


def run_test(pak_file: Path) -> tuple[bool, str]:
    """
    Run pak check on a single file.
    Returns (passed, message).
    """
    source = pak_file.read_text(encoding="utf-8")
    m = EXPECT_RE.search(source)
    if not m:
        return False, f"SKIP — no '-- EXPECT: EXXX' annotation found"

    expected_code = m.group(1)

    result = subprocess.run(
        ["pak", "check", str(pak_file)],
        capture_output=True,
        text=True,
    )

    # Must fail
    if result.returncode == 0:
        return False, f"FAIL — expected {expected_code} but compiler exited 0 (no error)"

    # Expected error code must appear in output
    combined = result.stdout + result.stderr
    if expected_code not in combined:
        # Show what was actually emitted
        actual_codes = re.findall(r"error\[([A-Z]\d+)\]", combined)
        actual_str = ", ".join(actual_codes) if actual_codes else "(none)"
        return False, f"FAIL — expected {expected_code}, got: {actual_str}\n  stderr: {result.stderr.strip()[:200]}"

    return True, f"PASS — {expected_code} emitted as expected"


def main() -> int:
    pak_files = sorted(INVALID_DIR.glob("*.pak"))
    if not pak_files:
        print(f"No .pak files found in {INVALID_DIR}", file=sys.stderr)
        return 1

    passed = 0
    failed = 0
    skipped = 0

    for pak_file in pak_files:
        ok, msg = run_test(pak_file)
        status = "✓" if ok else ("~" if msg.startswith("SKIP") else "✗")
        print(f"  [{status}] {pak_file.name}: {msg}")
        if ok:
            passed += 1
        elif msg.startswith("SKIP"):
            skipped += 1
        else:
            failed += 1

    print()
    print(f"{len(pak_files)} file(s): {passed} passed, {failed} failed, {skipped} skipped.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
