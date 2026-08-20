# engine/kb/loader.py
"""KB loading and validation.

Every KB file is data, reviewed by a human and frozen (spec §4.3). Loading is
strict on purpose: an unreviewed or malformed file must fail the build, not
silently degrade a profile. Lookup at runtime is the opposite: an unmapped
system element must never crash a profile — see `KnowledgeBase.tags_for`.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml

from engine.kb.facets import load_taxonomy
from engine.kb.version import KB_ROOT
from engine.types import TraitTag

SCHEMA = "kb.mapping.v1"


class KBValidationError(Exception):
    """Raised when a KB file violates the schema or references an unknown facet."""


@dataclass(frozen=True)
class TagSpec:
    facet: str
    weight: float
    direction: str


@dataclass(frozen=True)
class KBEntry:
    key: str
    label: str
    text: str
    tags: tuple[TagSpec, ...]


@dataclass(frozen=True)
class KBFile:
    system: str
    element: str
    source: str | None
    entries: dict[str, KBEntry]


@dataclass(frozen=True)
class KnowledgeBase:
    files: dict[tuple[str, str], KBFile]

    def entry(self, system: str, element: str, key: str) -> KBEntry | None:
        kb_file = self.files.get((system, element))
        return kb_file.entries.get(key) if kb_file else None

    def tags_for(self, system: str, element: str, key: str) -> list[TraitTag]:
        found = self.entry(system, element, key)
        if found is None:
            return []
        return [
            TraitTag(
                facet=t.facet,
                weight=t.weight,
                direction=t.direction,  # type: ignore[arg-type]
                system=system,
                element=element,
                text=found.text,
            )
            for t in found.tags
        ]

    def text_for(self, system: str, element: str, key: str) -> str:
        found = self.entry(system, element, key)
        return found.text if found else ""


def _validate_and_build(path: Path, doc: dict, taxonomy) -> KBFile:
    def fail(msg: str) -> None:
        raise KBValidationError(f"{path}: {msg}")

    if doc.get("schema") != SCHEMA:
        fail(f"expected schema {SCHEMA}, got {doc.get('schema')!r}")
    if doc.get("reviewed") is not True:
        fail("reviewed must be true — unreviewed KB drafts must not ship")
    system, element = doc.get("system"), doc.get("element")
    if not system or not element:
        fail("system and element are required")

    entries: dict[str, KBEntry] = {}
    for key, raw in (doc.get("entries") or {}).items():
        if not isinstance(raw, dict):
            fail(f"entry {key!r}: must be a mapping, got {raw!r}")
        label, text = (raw.get("label") or "").strip(), (raw.get("text") or "").strip()
        if not label:
            fail(f"entry {key!r}: label must not be empty")
        if not text:
            fail(f"entry {key!r}: text must not be empty")
        specs: list[TagSpec] = []
        for tag in raw.get("tags") or []:
            if not isinstance(tag, dict):
                fail(f"entry {key!r}: each tag must be a mapping, got {tag!r}")
            facet = tag.get("facet")
            if not facet:
                fail(f"entry {key!r}: tag is missing 'facet'")
            if not taxonomy.has(facet):
                fail(f"entry {key!r}, facet {facet!r}: unknown facet")
            if "weight" not in tag:
                fail(f"entry {key!r}, facet {facet!r}: tag is missing 'weight'")
            raw_weight = tag.get("weight")
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError):
                fail(f"entry {key!r}, facet {facet!r}: weight {raw_weight!r} is not a number")
            if not 0.0 <= weight <= 1.0:
                fail(f"entry {key!r}, facet {facet!r}: weight {weight} outside 0..1")
            direction = tag.get("direction")
            if direction not in ("high", "low"):
                fail(
                    f"entry {key!r}, facet {facet!r}: direction must be "
                    f"'high' or 'low', got {direction!r}"
                )
            specs.append(TagSpec(facet=facet, weight=weight, direction=direction))
        entries[key] = KBEntry(key=key, label=label, text=text, tags=tuple(specs))

    return KBFile(system=system, element=element, source=doc.get("source"), entries=entries)


@functools.cache
def load_kb(root: Path | None = None) -> KnowledgeBase:
    kb_root = Path(root or KB_ROOT)
    taxonomy = load_taxonomy(kb_root)
    files: dict[tuple[str, str], KBFile] = {}
    # sorted() so load order — and therefore any error reported — is deterministic.
    for path in sorted(kb_root.rglob("*.yaml")):
        if path.name == "facets.yaml":
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        kb_file = _validate_and_build(path, doc, taxonomy)
        key = (kb_file.system, kb_file.element)
        if key in files:
            raise KBValidationError(f"{path}: duplicate (system, element) pair {key}")
        files[key] = kb_file
    return KnowledgeBase(files=files)
