"""Pairwise compatibility (spec §5.3).

Deliberately modest for v1: inter-chart aspects on five points, Human Design
connection channels, and a curated Life Path matrix. Deeper synastry is
post-v1. Friction is surfaced as growth potential rather than as a penalty.

**Moon exclusion (R49/R59 controller amendment).** `engine/systems/astrology.py`
already answered this exact question for INTRA-chart aspects: with no birth
time the chart is computed for local noon and the Moon's aspects are
segregated out of `aspects`, because a noon assumption carries roughly
+/- 6.5 degrees of Moon error -- wider than every orb in `ASPECTS`
(conjunction/opposition 8.0, trine/square 7.0, sextile 5.0). The same
reasoning applies here: the synastry point set is built PER PERSON (never
from the module-level `SYNASTRY_POINTS` tuple directly), and `"moon"` is
dropped for whichever person's `input_quality.birth_time` is exactly
`"missing"` -- mirroring astrology.py's `has_time` predicate. `"ambiguous"`
and `"nonexistent"` readings are a one-hour DST window (~0.5 degrees of Moon
motion, comfortably inside every orb) and keep the Moon; using the looser
`birth_time_is_uncertain` predicate here would be wrong and is deliberately
not used. A pair contributes a given point only when it survives for BOTH
people. `"ascendant"` already disappears on a missing time because `angles`
is `None` on that same path, so no second guard is added for it.
"""

from __future__ import annotations

from engine.ephemeris.base import arc_between
from engine.kb.loader import load_kb
from engine.systems.astrology import ASPECTS
from engine.systems.human_design import load_channels

SYNASTRY_POINTS: tuple[str, ...] = ("sun", "moon", "venus", "mars", "ascendant")

ASPECT_SCORES: dict[str, int] = {
    "conjunction": 6,
    "trine": 5,
    "sextile": 3,
    "opposition": 1,
    "square": -2,
}
HARD_ASPECTS = frozenset({"square", "opposition"})

ASTRO_MIN, ASTRO_MAX = -50.0, 150.0
CHANNEL_POINTS = 4
CHANNEL_CAP = 40
NEUTRAL_HARMONY = 5

_SIGNS = (
    "Aries",
    "Taurus",
    "Gemini",
    "Cancer",
    "Leo",
    "Virgo",
    "Libra",
    "Scorpio",
    "Sagittarius",
    "Capricorn",
    "Aquarius",
    "Pisces",
)


def _absolute(sign: str, degree: float) -> float:
    return _SIGNS.index(sign) * 30.0 + degree


def _birth_time_quality(profile: dict) -> str:
    return profile.get("input_quality", {}).get("birth_time", "exact")


def _points(profile: dict) -> dict[str, float]:
    """Longitudes for this person's available synastry points, in degrees.

    `"moon"` is dropped when this person's own birth time is missing (see
    the module docstring); `"ascendant"` is already absent on that same path
    because `angles` is `None` -- no separate guard is needed for it here.
    """
    astrology = profile.get("raw", {}).get("astrology", {})
    exclude_moon = _birth_time_quality(profile) == "missing"

    out: dict[str, float] = {}
    for placement in astrology.get("placements", []):
        body = placement["body"]
        if body not in SYNASTRY_POINTS:
            continue
        if body == "moon" and exclude_moon:
            continue
        out[body] = _absolute(placement["sign"], placement["degree"])
    angles = astrology.get("angles")
    if angles:
        out["ascendant"] = _absolute(angles["ascendant"]["sign"], angles["ascendant"]["degree"])
    return out


def _aspect_for(separation: float) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for name, (exact, orb) in ASPECTS.items():
        delta = abs(separation - exact)
        if delta <= orb and (best is None or delta < best[1]):
            best = (name, delta)
    return best


def astrology_synastry(a: dict, b: dict) -> tuple[float, int, list[dict]]:
    """Returns (raw score, hard-aspect count, reasons).

    Point sets are built per person (`_points`), so a pair contributes a
    point only when it survives for both A and B -- which is exactly how a
    person's missing-time Moon exclusion propagates into the grid without
    any extra bookkeeping here.
    """
    points_a, points_b = _points(a), _points(b)
    total, hard = 0.0, 0
    reasons: list[dict] = []

    for name_a in SYNASTRY_POINTS:
        for name_b in SYNASTRY_POINTS:
            if name_a not in points_a or name_b not in points_b:
                continue
            found = _aspect_for(arc_between(points_a[name_a], points_b[name_b]))
            if found is None:
                continue
            aspect, _orb = found
            total += ASPECT_SCORES[aspect]
            if aspect in HARD_ASPECTS:
                hard += 1
            reasons.append(
                {
                    "system": "astrology",
                    "detail": f"A's {name_a} {aspect} B's {name_b}",
                    "effect": "challenging" if aspect in HARD_ASPECTS else "positive",
                }
            )

    reasons.sort(key=lambda r: r["detail"])
    return total, hard, reasons


def _moon_excluded_note(quality_a: str, quality_b: str) -> str | None:
    """R49/R59: name whichever of A/B has no birth time, or both -- once, not
    twice -- or `None` when the Moon was not excluded from either side."""
    a_missing = quality_a == "missing"
    b_missing = quality_b == "missing"
    if not a_missing and not b_missing:
        return None
    if a_missing and b_missing:
        who = "A and B have no birth time"
    else:
        who = "A has no birth time" if a_missing else "B has no birth time"
    return (
        f"moon excluded from synastry: {who}. A noon-chart moon position carries "
        "roughly +/- 6.5 degrees of uncertainty (the moon moves about 13 degrees a "
        "day), wider than every orb in ASPECTS, so a moon synastry aspect built on "
        "it would be scoring noise and calling it a fact."
    )


def hd_connection_channels(a: dict, b: dict) -> tuple[int, list[dict], list[str]]:
    hd_a = a.get("raw", {}).get("human_design", {})
    hd_b = b.get("raw", {}).get("human_design", {})
    if not hd_a.get("available") or not hd_b.get("available"):
        missing = "A" if not hd_a.get("available") else "B"
        return 0, [], [f"human_design excluded: {missing} has no birth time"]

    gates_a, gates_b = set(hd_a.get("gates", [])), set(hd_b.get("gates", []))
    reasons: list[dict] = []
    for low, high in load_channels():
        a_has_both = low in gates_a and high in gates_a
        b_has_both = low in gates_b and high in gates_b
        if a_has_both or b_has_both:
            continue  # already defined in one chart; not a connection channel
        completes = (low in gates_a and high in gates_b) or (high in gates_a and low in gates_b)
        if completes:
            reasons.append(
                {
                    "system": "human_design",
                    "detail": (
                        f"gates {low} and {high} combine across the pair (channel {low}-{high})"
                    ),
                    "effect": "positive",
                }
            )

    reasons.sort(key=lambda r: r["detail"])
    return min(len(reasons) * CHANNEL_POINTS, CHANNEL_CAP), reasons, []


def life_path_harmony(a: int, b: int) -> int:
    key = "-".join(str(n) for n in sorted((a, b)))
    entry = load_kb().entry("compatibility", "life_path_pairs", key)
    if entry is None or not entry.label.isdigit():
        return NEUTRAL_HARMONY
    return int(entry.label)


def numerology_harmony(a: dict, b: dict) -> tuple[int, list[dict]]:
    lp_a = a.get("raw", {}).get("numerology", {}).get("life_path")
    lp_b = b.get("raw", {}).get("numerology", {}).get("life_path")
    if not lp_a or not lp_b:
        return NEUTRAL_HARMONY, []
    harmony = life_path_harmony(lp_a, lp_b)
    entry = load_kb().entry(
        "compatibility", "life_path_pairs", "-".join(str(n) for n in sorted((lp_a, lp_b)))
    )
    detail = entry.text if entry else f"Life Path {lp_a} and {lp_b}"
    return harmony, [
        {
            "system": "numerology",
            "detail": detail,
            "effect": "positive" if harmony >= NEUTRAL_HARMONY else "challenging",
        }
    ]


def _rescale(value: float, low: float, high: float) -> int:
    clamped = max(low, min(high, value))
    return round((clamped - low) / (high - low) * 100)


def compare(profile_a: dict, profile_b: dict) -> dict:
    astro_raw, hard_count, astro_reasons = astrology_synastry(profile_a, profile_b)
    hd_raw, hd_reasons, hd_notes = hd_connection_channels(profile_a, profile_b)
    numerology_raw, numerology_reasons = numerology_harmony(profile_a, profile_b)

    astro_score = _rescale(astro_raw, ASTRO_MIN, ASTRO_MAX)
    hd_score = min(100, 50 + hd_raw)
    numerology_score = numerology_raw * 10

    connection = round((astro_score + hd_score) / 2) if not hd_notes else astro_score
    communication = round((astro_score + numerology_score) / 2)
    # More hard aspects means more friction to work with -- reported as growth.
    growth = _rescale(hard_count, 0, 8)

    dimensions = {
        "connection": connection,
        "communication": communication,
        "growth": growth,
    }

    notes = list(hd_notes)
    quality_a, quality_b = _birth_time_quality(profile_a), _birth_time_quality(profile_b)
    moon_note = _moon_excluded_note(quality_a, quality_b)
    if moon_note:
        notes.append(moon_note)

    return {
        "score": round(sum(dimensions.values()) / 3),
        "dimensions": dimensions,
        "reasons": astro_reasons + hd_reasons + numerology_reasons,
        "notes": notes,
    }
