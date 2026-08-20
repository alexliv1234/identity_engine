# engine/kb/version.py
"""KB version, read from kb/VERSION. Date-based, e.g. kb-2026.08 (spec §4.3)."""

from __future__ import annotations

import functools
from pathlib import Path

KB_ROOT = Path(__file__).resolve().parents[2] / "kb"


@functools.cache
def kb_version(root: Path | None = None) -> str:
    return (root or KB_ROOT).joinpath("VERSION").read_text(encoding="utf-8").strip()
