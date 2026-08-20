"""Profile assembly.

A profile is a pure function of (birth input, engine version, KB version) — no
clock, no randomness, no network (spec §1, §8).

Every collection that reaches the output is built in a deterministic order:
`SYSTEM_REGISTRY` is walked via `sorted()`, never dict iteration order, so a
future registration order (or a dict re-insertion) can never change output
bytes.
"""

from __future__ import annotations

from engine import __version__
from engine.canonical import canonical_json
from engine.kb.version import kb_version
from engine.names import NameQuality, normalize
from engine.synthesis import synthesize
from engine.systems.chinese_zodiac import ChineseZodiacCalculator
from engine.systems.numerology import NumerologyCalculator
from engine.types import BirthInput, SystemCalculator, SystemOutput, TraitTag

DISCLAIMER = (
    "Reflective and entertainment insight; not medical, psychological, or financial advice."
)

# The single wiring point: a later plan extends this dict with four more
# systems and changes nothing else in this module.
SYSTEM_REGISTRY: dict[str, SystemCalculator] = {
    calc.key: calc
    for calc in (
        NumerologyCalculator(),
        ChineseZodiacCalculator(),
    )
}


def _unavailable(calc: SystemCalculator, missing: set) -> SystemOutput:
    names = ", ".join(sorted(str(m) for m in missing))
    return SystemOutput(
        raw={"available": False},
        tags=[],
        confidence=0.0,
        notes=[f"{calc.key} excluded: required input missing ({names})"],
    )


def _build_raw_and_confidences(
    inp: BirthInput, selected: list[str]
) -> tuple[dict[str, dict], dict[str, float], list[TraitTag]]:
    """Run every selected calculator (gating unavailable ones) and assemble
    the raw slots, the per-system confidence map, and the flat tag list.

    `confidences` is built from exactly the same key set as `raw` — every
    selected system gets an entry, whether it ran, was gated, or produced no
    tags — which is what keeps `synthesize`'s completeness invariant
    (engine/synthesis.py: every tag's system must have a confidence entry)
    satisfied by construction rather than by convention.
    """
    raw: dict[str, dict] = {}
    confidences: dict[str, float] = {}
    all_tags: list[TraitTag] = []

    for key in sorted(selected):
        calc = SYSTEM_REGISTRY[key]
        missing = set(calc.required_inputs) - inp.available_fields
        output = _unavailable(calc, missing) if missing else calc.compute(inp)

        raw[key] = {
            **output.raw,
            "confidence": output.confidence,
            "notes": output.notes,
        }
        confidences[key] = output.confidence
        all_tags.extend(output.tags)

    # Own invariant, not an assumption: every tag emitted above must belong
    # to a system we just recorded a confidence for. A gated system always
    # contributes zero tags (see `_unavailable`), so this should never fire —
    # but if a future calculator ever returns tags tagged with a system name
    # other than its own registry key, this fails loudly here instead of
    # deep inside `synthesize`.
    for tag in all_tags:
        assert tag.system in confidences, (
            f"tag from facet {tag.facet!r} references system {tag.system!r}, "
            "which has no confidence entry"
        )

    return raw, confidences, all_tags


def build_profile(inp: BirthInput, systems: list[str] | None = None) -> dict:
    selected = (
        list(SYSTEM_REGISTRY)
        if systems is None
        else [k for k in SYSTEM_REGISTRY if k in set(systems)]
    )

    raw, confidences, all_tags = _build_raw_and_confidences(inp, selected)

    name = normalize(inp.full_name, inp.hebrew_name)
    return {
        "versions": {"engine": __version__, "kb": kb_version()},
        "input_quality": {
            "birth_time": "exact" if inp.birth_time is not None else "missing",
            "hebrew_name": "provided" if name.hebrew_quality is NameQuality.PROVIDED else "derived",
            "full_name_script": "latin"
            if name.latin_quality is NameQuality.PROVIDED
            else "transliterated",
        },
        "raw": raw,
        "synthesis": synthesize(all_tags, confidences),
        "disclaimer": DISCLAIMER,
    }


def profile_bytes(profile: dict) -> str:
    """Canonical serialization — the determinism-check surface."""
    return canonical_json(profile)
