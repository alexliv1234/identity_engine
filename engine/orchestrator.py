"""Profile assembly.

A profile is a pure function of (birth input, engine version, KB version) — no
clock, no randomness, no network (spec §1, §8).

Every collection that reaches the output is built in a deterministic order:
`SYSTEM_REGISTRY` is walked via `sorted()`, never dict iteration order, so a
future registration order (or a dict re-insertion) can never change output
bytes.

`build_profile` deliberately takes no system filter. It used to accept
`systems=[...]`, which *recomputed* the profile over a subset — and that is
not the same operation as filtering a finished profile: convergence is the
share of *applicable* systems agreeing (engine/synthesis.py), so dropping
systems from the computation changes the denominator and rewrites every
facet's convergence score (a facet measured at 0.333 on the full six rose to
1.0 on a two-system subset). Plan 3's `?systems=` is a post-hoc projection
over a stored full profile, which is a different thing entirely, so nothing
consumed the parameter and it existed only as a trap. Removed rather than
documented: a projection belongs at the API layer, over the stored profile.
"""

from __future__ import annotations

from engine import __version__
from engine.canonical import canonical_json
from engine.kb.version import kb_version
from engine.names import NameQuality, normalize
from engine.synthesis import synthesize
from engine.systems.astrology import AstrologyCalculator
from engine.systems.chinese_zodiac import ChineseZodiacCalculator
from engine.systems.gene_keys import GeneKeysCalculator
from engine.systems.human_design import HumanDesignCalculator
from engine.systems.kabbalah import KabbalahCalculator
from engine.systems.numerology import NumerologyCalculator
from engine.types import BirthInput, SystemCalculator, SystemOutput, TraitTag

DISCLAIMER = (
    "Reflective and entertainment insight; not medical, psychological, or financial advice."
)

# The single wiring point: a later plan extends this dict with more systems
# and changes nothing else in this module.
SYSTEM_REGISTRY: dict[str, SystemCalculator] = {
    calc.key: calc
    for calc in (
        AstrologyCalculator(),
        NumerologyCalculator(),
        ChineseZodiacCalculator(),
        HumanDesignCalculator(),
        GeneKeysCalculator(),
        KabbalahCalculator(),
    )
}

ENGINE_OWNED_RAW_KEYS = frozenset({"confidence", "notes"})


def _unavailable(calc: SystemCalculator, missing: set) -> SystemOutput:
    names = ", ".join(sorted(str(m) for m in missing))
    return SystemOutput(
        raw={"available": False},
        tags=[],
        confidence=0.0,
        notes=[f"{calc.key} excluded: required input missing ({names})"],
    )


def _build_raw_and_confidences(
    inp: BirthInput,
) -> tuple[dict[str, dict], dict[str, float], list[TraitTag]]:
    """Run every registered calculator (gating unavailable ones) and assemble
    the raw slots, the per-system confidence map, and the flat tag list.

    `confidences` is built from exactly the same key set as `raw` — every
    system gets an entry, whether it ran, was gated, or produced no tags —
    which is what keeps `synthesize`'s completeness invariant
    (engine/synthesis.py: every tag's system must have a confidence entry)
    satisfied by construction rather than by convention.

    Both guards below `raise ValueError` rather than `assert`. `python -O`
    strips assertions, and a hosted service is far likelier to run under `-O`
    than a test suite is — which would have turned the first guard into silent
    data loss and the second into a crash deep inside `synthesize`, in exactly
    the deployment where the failure is hardest to diagnose.
    """
    raw: dict[str, dict] = {}
    confidences: dict[str, float] = {}
    all_tags: list[TraitTag] = []

    for key in sorted(SYSTEM_REGISTRY):
        calc = SYSTEM_REGISTRY[key]
        missing = set(calc.required_inputs) - inp.available_fields
        output = _unavailable(calc, missing) if missing else calc.compute(inp)

        # The raw slot is the calculator's own dict plus two engine-owned keys.
        # If a future calculator ever emits its own "confidence" or "notes" raw
        # key, the spread below would silently discard it -- data loss with no
        # symptom. Fail loudly at the collision instead; the calculator should
        # name its key something else.
        collisions = ENGINE_OWNED_RAW_KEYS & set(output.raw)
        if collisions:
            raise ValueError(
                f"{key}: raw output collides with an engine-owned key "
                f"({sorted(collisions)}); "
                "the engine sets confidence and notes from SystemOutput"
            )
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
        if tag.system not in confidences:
            raise ValueError(
                f"tag from facet {tag.facet!r} references system {tag.system!r}, "
                "which has no confidence entry"
            )

    return raw, confidences, all_tags


def build_profile(inp: BirthInput) -> dict:
    raw, confidences, all_tags = _build_raw_and_confidences(inp)

    name = normalize(inp.full_name, inp.hebrew_name)
    return {
        "versions": {"engine": __version__, "kb": kb_version()},
        "input_quality": {
            # "exact" | "missing" | "ambiguous" | "nonexistent" — see
            # engine/types.py's BirthTimeQuality. The last two are DST clock
            # readings that name two instants or none; reporting them as
            # "exact" was the precision the engine was faking.
            "birth_time": str(inp.birth_time_quality),
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
