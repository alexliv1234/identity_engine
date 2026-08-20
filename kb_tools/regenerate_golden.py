"""Regenerate tests/golden/*.json from the current engine + KB.

Run deliberately, review the diff, commit. Never run this in CI — the whole
value of golden files is that they only change when a human decides they should.

Usage (from the repo root):

    .venv/Scripts/python kb_tools/regenerate_golden.py    # Windows
    .venv/bin/python kb_tools/regenerate_golden.py         # Linux/macOS
"""

from __future__ import annotations

import sys
from pathlib import Path

# This script lives in kb_tools/, so its own directory (not the repo root)
# is what Python puts on sys.path[0] when it's run by path. `tests` is not
# an installed package (only `engine` is, via the editable install), so
# without this the `tests.fixtures.people` import below fails with
# "No module named 'tests'". Insert the repo root explicitly instead of
# relying on invocation-relative sys.path behaviour.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.orchestrator import build_profile, profile_bytes  # noqa: E402
from tests.fixtures.people import FIXTURES  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "tests" / "golden"


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name in sorted(FIXTURES):
        blob = profile_bytes(build_profile(FIXTURES[name]))
        (GOLDEN_DIR / f"{name}.json").write_text(blob + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {name}.json ({len(blob)} bytes)")


if __name__ == "__main__":
    main()
