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

**Dimension split.** The 5x5 synastry grid is scored into TWO disjoint
subsets, matching the brief's dimension rollup rather than one aggregate
reused for both dimensions: `connection` sums only pairs among
Sun/Moon/Venus/Mars (the "how do the two people relate" points), and
`communication` sums only pairs involving the Ascendant (the "how do they
present/read each other" point). Every pair still lands in `reasons`
regardless of which dimension it feeds -- the reasons block stays complete,
only the two numeric rollups are computed from disjoint inputs.

**Rescale ranges are derived, never assumed (fix round 2).** Each subset is
rescaled onto 0..100 against its own range, and that range is computed from
the pairs actually CHECKABLE for *this* pair of people -- `len(pairs) *
MIN_ASPECT_SCORE` to `len(pairs) * MAX_ASPECT_SCORE` -- not from a constant
that assumes both charts are complete. The full-grid pair counts below
(16 for `connection`, 9 for `communication`) survive only as the totals a
"grid reduced" note compares against.

That distinction is the whole product. `_points` drops a person's Moon when
their birth time is missing, and their Ascendant is already gone on that same
path (and on a polar-latitude chart, where the time IS known but Placidus
houses are undefined). The candidate grid shrinks. If the range does not
shrink with it, every unavailable pair is scored as a measured zero: two
people whose every checkable point sat in exact trine landed on 60/100 --
lower than a fully-timed pair with a handful of ordinary aspects -- because
seven pairs that were never looked at were quietly counted as "no aspect
found". Absent evidence must never be presented as negative evidence, so:

  * a reduced grid is rescaled against the reduced grid, and
  * whenever the grid IS reduced, a note says so, naming which points were
    unavailable -- including the asymmetric case (one person timed, one
    not), which used to be scored against the full 9-pair `communication`
    range and emitted with no note at all, and
  * a subset with ZERO checkable pairs is not rescaled at all. It falls back
    to the dimension's other input (Human Design for `connection`, the
    numerology matrix for `communication`) with a note, because summing zero
    and rescaling it would land on a specific, low-but-not-bottom number
    that reads as "measured near-incompatibility" when what actually
    happened is "nothing to compare". If a dimension's inputs are ALL
    absent, it reports `NEUTRAL_DIMENSION` and says, in a note, that the
    number is a placeholder for "nothing was measured" rather than a
    measured midpoint.

The same rule governs the numerology matrix (`numerology_harmony`): a
missing Life Path on either side, or a Life Path pair the knowledge base has
no curated entry for, falls back to `NEUTRAL_HARMONY` -- a reasonable
fallback that was, until fix round 2, completely silent. A 50 out of 100
reads as measured mid-compatibility. It now carries both a note and a
`reasons` row whose `effect` is `"unmeasured"` -- a third effect alongside
`"positive"` and `"challenging"`, because filing absent evidence under
either of those two is precisely the error this module exists not to make.

**Fix round 3: the same rule, closed at the top level.** The first two fix
rounds above chased this defect wherever it happened to have a name --
`connection`'s zero-pairs case, the numerology matrix's silent fallback. Two
more places still absorbed absent evidence as a measurement, both of them
consequences of the same missing-grid state rather than new sources of data:

  * `growth` has exactly one input -- `hard_count` from the synastry grid --
    and never had a fallback of its own. When the candidate grid is entirely
    empty (`connection_pairs` and `communication_pairs` both zero),
    `hard_count` is necessarily zero too, and rescaling that zero produced a
    reported 0 that reads as "no friction found" -- a confident claim of
    harmony asserted from zero measurements. `growth`'s `0..8` range is not
    the bug and is unchanged; the floor is. `growth` now takes the same
    fallback `connection` already had: zero checkable pairs reports
    `NEUTRAL_DIMENSION` with a note, not a measured 0.
  * `score = round(sum(dimensions.values()) / 3)` averaged all three
    dimensions unconditionally, including whichever ones had just reported a
    placeholder rather than a measurement. `score` now averages only the
    dimensions that were actually measured this call, and the response
    carries `score_partial: true` whenever one or more were excluded --
    additive to the v1 response shape, so a consumer can tell a
    fully-measured score from a partly-placeholder one by reading a field,
    not by parsing `notes`. A dimension counts as a placeholder here exactly
    when it reported `NEUTRAL_DIMENSION` for having no input at all (this
    applies to `connection` and, now, `growth`), or -- for `communication`,
    which has no `NEUTRAL_DIMENSION` branch of its own -- when BOTH of its
    inputs fell back: no checkable astrology pair AND the numerology matrix
    itself returned `NEUTRAL_HARMONY` rather than a curated value. When
    `communication` blends a real numerology measurement with an absent
    astrology grid, that numerology number is real evidence, not a
    placeholder, and stays in the mean.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.ephemeris.base import arc_between
from engine.kb.loader import load_kb
from engine.orchestrator import DISCLAIMER
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

# The per-pair extremes a subset's rescale range is built from: a subset of
# N checkable pairs spans N * MIN_ASPECT_SCORE .. N * MAX_ASPECT_SCORE.
MIN_ASPECT_SCORE = min(ASPECT_SCORES.values())
MAX_ASPECT_SCORE = max(ASPECT_SCORES.values())

# Full-grid pair counts, used ONLY by the "N of M pairs were checkable" note
# -- never to rescale a subset (see the module docstring).
#
# `connection`: Sun/Moon/Venus/Mars on both sides -> 4x4 = 16 ordered pairs.
FULL_CONNECTION_PAIRS = 16
# `communication`: any pair involving the Ascendant on either side -> the 25
# total minus the 16 above = 9 ordered pairs (asc-asc, asc-X x4, X-asc x4).
FULL_COMMUNICATION_PAIRS = 9

CHANNEL_POINTS = 4
CHANNEL_CAP = 40
NEUTRAL_HARMONY = 5

#: What a dimension reports when *every* one of its inputs was unavailable.
#: Always accompanied by a note saying it is a placeholder, never a measured
#: midpoint.
NEUTRAL_DIMENSION = 50

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


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " or " + items[-1]


def _absent_points_phrase(points_a: dict[str, float], points_b: dict[str, float]) -> str:
    """Which synastry points each person is missing, named rather than
    inferred from a birth-time flag: a point can be absent for reasons other
    than a missing time (a polar-latitude chart has an exact birth time and
    still has no ascendant), so the note reports the observed gap."""
    parts = []
    for who, points in (("A", points_a), ("B", points_b)):
        missing = [name for name in SYNASTRY_POINTS if name not in points]
        if missing:
            parts.append(f"{who} has no {_join(missing)}")
    return "; ".join(parts) if parts else "no points were unavailable"


@dataclass(frozen=True)
class Synastry:
    """What the inter-chart grid actually yielded for one pair of people.

    `connection_pairs`/`communication_pairs` count the CHECKABLE ordered
    pairs -- the candidate grid, not the pairs that happened to match an
    aspect -- which is what each dimension's rescale range is derived from.
    """

    connection_raw: float = 0.0
    communication_raw: float = 0.0
    connection_pairs: int = 0
    communication_pairs: int = 0
    hard_count: int = 0
    reasons: list[dict] = field(default_factory=list)
    absent_points: str = ""


def astrology_synastry(a: dict, b: dict) -> Synastry:
    """Score the inter-chart grid, per dimension, over checkable pairs only.

    Point sets are built per person (`_points`), so a pair is a candidate
    only when the point survives for both A and B -- which is exactly how a
    person's missing-time Moon/Ascendant exclusion propagates into the grid
    without any extra bookkeeping here. Every checked pair, from either
    subset, is appended to `reasons` -- the split only affects which raw
    total a pair's score feeds, never whether it is reported.
    """
    points_a, points_b = _points(a), _points(b)
    connection_raw, communication_raw = 0.0, 0.0
    connection_pairs, communication_pairs = 0, 0
    hard = 0
    reasons: list[dict] = []

    for name_a in SYNASTRY_POINTS:
        for name_b in SYNASTRY_POINTS:
            if name_a not in points_a or name_b not in points_b:
                continue
            is_communication = name_a == "ascendant" or name_b == "ascendant"
            if is_communication:
                communication_pairs += 1
            else:
                connection_pairs += 1

            found = _aspect_for(arc_between(points_a[name_a], points_b[name_b]))
            if found is None:
                continue
            aspect, _orb = found
            score = ASPECT_SCORES[aspect]
            if is_communication:
                communication_raw += score
            else:
                connection_raw += score
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
    return Synastry(
        connection_raw=connection_raw,
        communication_raw=communication_raw,
        connection_pairs=connection_pairs,
        communication_pairs=communication_pairs,
        hard_count=hard,
        reasons=reasons,
        absent_points=_absent_points_phrase(points_a, points_b),
    )


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


def _grid_reduced_note(dimension: str, checkable: int, full: int, absent: str) -> str:
    """Said whenever a dimension's candidate grid is smaller than the full
    one. Same voice as `_moon_excluded_note`: name what was dropped, then say
    why reporting it as a low score would have been a lie."""
    return (
        f"{dimension} astrology grid reduced: {checkable} of the {full} pairs this "
        f"dimension scores were checkable for this pair ({absent}). The score is "
        "rescaled against the pairs actually available rather than against a full "
        "grid, because an unchecked pair is absent evidence, not evidence of a "
        "mismatch -- scoring it as a zero would report silence as disagreement."
    )


_COMMUNICATION_ASTRO_EXCLUDED_NOTE = (
    "communication astrology signal excluded: neither chart has an ascendant to "
    "compare, so this dimension's astrology grid has no checkable pairs at all -- "
    "not zero matched aspects, zero candidates. That is an absence of evidence, "
    "not evidence of a mismatch, so communication reflects the numerology matrix "
    "alone rather than a zero-pair astrology score standing in for measured "
    "incompatibility."
)

_CONNECTION_ASTRO_EXCLUDED_NOTE = (
    "connection astrology signal excluded: no sun/moon/venus/mars point is present "
    "in both charts, so this dimension's astrology grid has no checkable pairs at "
    "all -- not zero matched aspects, zero candidates. That is an absence of "
    "evidence, not evidence of a mismatch, so connection reflects the human design "
    "connection channels alone rather than a zero-pair astrology score standing in "
    "for measured incompatibility."
)

_CONNECTION_UNMEASURABLE_NOTE = (
    "connection could not be measured: its astrology grid has no checkable pairs "
    "and human design is unavailable, so neither of this dimension's two inputs "
    f"produced any evidence. The {NEUTRAL_DIMENSION} reported here is a placeholder "
    "for 'nothing was measured', not a measured midpoint."
)

_GROWTH_UNMEASURABLE_NOTE = (
    "growth could not be measured: the synastry grid has no checkable pairs at "
    "all, so there is no hard-aspect count to rescale -- not zero friction found, "
    f"zero pairs looked at. The {NEUTRAL_DIMENSION} reported here is a placeholder "
    "for 'nothing was measured', not a measured absence of friction."
)


def _score_partial_note(placeholder_dimensions: set[str]) -> str:
    """Said whenever the headline `score` excluded one or more dimensions
    from its mean because they reported a placeholder rather than a
    measurement. Same voice as the fallback notes above: name what was
    dropped, then say why averaging it in would have been a lie."""
    named = _join(sorted(placeholder_dimensions))
    return (
        f"score is partial: {named} reported a placeholder rather than a "
        "measurement, so the headline score averages only the dimensions that "
        "were actually measured this time. Averaging a placeholder in would let "
        "silence pull the headline number toward NEUTRAL_DIMENSION as if it were "
        "evidence -- see score_partial."
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


def _life_path_key(a: int, b: int) -> str:
    return "-".join(str(n) for n in sorted((a, b)))


def _life_path_entry(a: int, b: int):
    return load_kb().entry("compatibility", "life_path_pairs", _life_path_key(a, b))


def life_path_harmony(a: int, b: int) -> int:
    """0..10 harmony for a Life Path pair, or `NEUTRAL_HARMONY` when the
    knowledge base carries no usable entry for it. Callers that need to know
    *which* of those two happened (so they can say so) should use
    `numerology_harmony`, which reports the fallback instead of absorbing it
    silently."""
    entry = _life_path_entry(a, b)
    if entry is None or not entry.label.isdigit():
        return NEUTRAL_HARMONY
    return int(entry.label)


def numerology_harmony(a: dict, b: dict) -> tuple[int, list[dict], list[str]]:
    """Returns (harmony 0..10, reasons, notes).

    The two fallback paths -- a missing Life Path on either side, and a Life
    Path pair with no usable knowledge-base entry -- both land on
    `NEUTRAL_HARMONY`, i.e. 50 out of 100 once scaled. That reads as a
    measured middling compatibility when nothing was measured at all, so
    each one now emits a note AND a `reasons` row (effect `"unmeasured"`)
    rather than disappearing into the score.
    """
    lp_a = a.get("raw", {}).get("numerology", {}).get("life_path")
    lp_b = b.get("raw", {}).get("numerology", {}).get("life_path")

    if not lp_a or not lp_b:
        if not lp_a and not lp_b:
            who = "neither A nor B has"
        else:
            who = "A has" if not lp_a else "B has"
        return (
            NEUTRAL_HARMONY,
            [
                {
                    "system": "numerology",
                    "detail": f"life path comparison not possible: {who} no life path number",
                    "effect": "unmeasured",
                }
            ],
            [
                f"numerology harmony not measured: {who} no life path number, so the "
                f"life path matrix had nothing to look up. The {NEUTRAL_HARMONY * 10} "
                f"numerology contributes to communication here is a placeholder for "
                f"'nothing was measured', not a measured mid-compatibility."
            ],
        )

    key = _life_path_key(lp_a, lp_b)
    entry = _life_path_entry(lp_a, lp_b)
    if entry is None or not entry.label.isdigit():
        return (
            NEUTRAL_HARMONY,
            [
                {
                    "system": "numerology",
                    "detail": f"no curated life path {key} pairing in the knowledge base",
                    "effect": "unmeasured",
                }
            ],
            [
                f"numerology harmony not measured: the knowledge base carries no "
                f"curated life path {key} pairing, so the matrix had nothing to look "
                f"up. The {NEUTRAL_HARMONY * 10} numerology contributes to "
                f"communication here is a placeholder for 'nothing was measured', not "
                f"a measured mid-compatibility."
            ],
        )

    harmony = int(entry.label)
    return (
        harmony,
        [
            {
                "system": "numerology",
                "detail": entry.text,
                "effect": "positive" if harmony >= NEUTRAL_HARMONY else "challenging",
            }
        ],
        [],
    )


def _rescale(value: float, low: float, high: float) -> int:
    clamped = max(low, min(high, value))
    return round((clamped - low) / (high - low) * 100)


def _subset_score(raw: float, checkable_pairs: int) -> int | None:
    """Rescale one astrology subset onto 0..100 against the range its own
    checkable pairs actually span -- or `None` when there were no candidate
    pairs at all, which is a question this function cannot answer and must
    not pretend to."""
    if checkable_pairs == 0:
        return None
    return _rescale(
        raw,
        checkable_pairs * MIN_ASPECT_SCORE,
        checkable_pairs * MAX_ASPECT_SCORE,
    )


def compare(profile_a: dict, profile_b: dict) -> dict:
    synastry = astrology_synastry(profile_a, profile_b)
    hd_raw, hd_reasons, hd_notes = hd_connection_channels(profile_a, profile_b)
    numerology_raw, numerology_reasons, numerology_notes = numerology_harmony(profile_a, profile_b)

    connection_astro_score = _subset_score(synastry.connection_raw, synastry.connection_pairs)
    communication_astro_score = _subset_score(
        synastry.communication_raw, synastry.communication_pairs
    )
    hd_score = min(100, 50 + hd_raw)
    numerology_score = numerology_raw * 10

    notes = list(hd_notes)
    quality_a, quality_b = _birth_time_quality(profile_a), _birth_time_quality(profile_b)
    moon_note = _moon_excluded_note(quality_a, quality_b)
    if moon_note:
        notes.append(moon_note)

    # Dimensions that ended up reporting NEUTRAL_DIMENSION (or, for
    # `communication`, a value built entirely from fallbacks) rather than an
    # actual measurement -- tracked so the headline `score` below can average
    # only what was measured (fix round 3).
    placeholder_dimensions: set[str] = set()

    # --- connection: the planetary grid + Human Design connection channels
    if connection_astro_score is None:
        if hd_notes:
            connection = NEUTRAL_DIMENSION
            notes.append(_CONNECTION_UNMEASURABLE_NOTE)
            placeholder_dimensions.add("connection")
        else:
            connection = hd_score
            notes.append(_CONNECTION_ASTRO_EXCLUDED_NOTE)
    else:
        if synastry.connection_pairs < FULL_CONNECTION_PAIRS:
            notes.append(
                _grid_reduced_note(
                    "connection",
                    synastry.connection_pairs,
                    FULL_CONNECTION_PAIRS,
                    synastry.absent_points,
                )
            )
        connection = (
            connection_astro_score if hd_notes else round((connection_astro_score + hd_score) / 2)
        )

    # --- communication: the ascendant grid + the numerology life path matrix
    if communication_astro_score is None:
        communication = numerology_score
        notes.append(_COMMUNICATION_ASTRO_EXCLUDED_NOTE)
        if numerology_notes:
            # Both of communication's inputs are absent here -- no checkable
            # ascendant pair AND the numerology matrix itself fell back to
            # NEUTRAL_HARMONY -- so the number this dimension reports is a
            # placeholder end to end, not a real measurement standing alone.
            placeholder_dimensions.add("communication")
    else:
        if synastry.communication_pairs < FULL_COMMUNICATION_PAIRS:
            notes.append(
                _grid_reduced_note(
                    "communication",
                    synastry.communication_pairs,
                    FULL_COMMUNICATION_PAIRS,
                    synastry.absent_points,
                )
            )
        communication = round((communication_astro_score + numerology_score) / 2)

    notes.extend(numerology_notes)

    # More hard aspects means more friction to work with -- reported as
    # growth. A zero-pairs grid is absent evidence, not zero friction (fix
    # round 3): `hard_count` can only be zero BY MEASUREMENT when at least
    # one pair was actually checked, mirroring `connection`'s own zero-pairs
    # fallback above.
    total_synastry_pairs = synastry.connection_pairs + synastry.communication_pairs
    if total_synastry_pairs == 0:
        growth = NEUTRAL_DIMENSION
        notes.append(_GROWTH_UNMEASURABLE_NOTE)
        placeholder_dimensions.add("growth")
    else:
        growth = _rescale(synastry.hard_count, 0, 8)

    dimensions = {
        "connection": connection,
        "communication": communication,
        "growth": growth,
    }

    # The headline score averages only the dimensions that were actually
    # measured -- a placeholder dimension does not get to pull the number it
    # sits next to toward NEUTRAL_DIMENSION as if it were evidence.
    measured = {
        name: value for name, value in dimensions.items() if name not in placeholder_dimensions
    }
    score_partial = bool(placeholder_dimensions)
    if measured:
        score = round(sum(measured.values()) / len(measured))
    else:
        # All three dimensions were placeholders -- an extreme edge case, but
        # the response still needs a number, and it must be the same
        # placeholder the dimensions themselves already are, not a fabricated
        # measurement dressed up as one.
        score = NEUTRAL_DIMENSION
    if score_partial:
        notes.append(_score_partial_note(placeholder_dimensions))

    return {
        "score": score,
        # v1-additive: true whenever `score` excluded a placeholder
        # dimension from its mean, so a consumer can tell a fully-measured
        # score from a partly-placeholder one without parsing `notes`.
        "score_partial": score_partial,
        "dimensions": dimensions,
        "reasons": synastry.reasons + hd_reasons + numerology_reasons,
        "notes": notes,
        # Spec §11: consuming apps inherit the disclaimer, and a pairwise
        # compatibility score is exactly the output a reader is most likely
        # to over-read.
        "disclaimer": DISCLAIMER,
    }
