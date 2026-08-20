"""KB completeness manifest.

The loader (engine/kb/loader.py) validates what a file contains. This declares
what it must contain, so a half-authored file fails the build instead of quietly
producing a thinner profile.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

from engine.kb.version import KB_ROOT


@functools.lru_cache(maxsize=4)
def load_manifest(root: Path | None = None) -> dict[tuple[str, str], list[str]]:
    path = Path(root or KB_ROOT) / "manifest.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "kb.manifest.v1":
        raise ValueError(f"{path}: expected schema kb.manifest.v1, got {doc.get('schema')!r}")

    manifest: dict[tuple[str, str], list[str]] = {}
    for declared, spec in doc["files"].items():
        system, element = declared.split("/", 1)
        manifest[(system, element)] = [str(k) for k in spec["keys"]]
    return manifest
