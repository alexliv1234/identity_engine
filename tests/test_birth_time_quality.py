"""Ambiguous and nonexistent local birth times (review FIX 1).

A local clock reading is not always a single instant. Twice a year, in every
zone that observes DST, one wall-clock hour is either repeated (the clock goes
back — the reading is *ambiguous*, it names two instants) or skipped (the clock
goes forward — the reading is *nonexistent*, it names none).

Before this fix `BirthInput.utc_datetime` resolved both silently with
`fold=0`, the profile reported `input_quality.birth_time: "exact"`, and every
chart system claimed `confidence 1.0` with no note anywhere. That contradicts
the spec §8 rule that "the engine never fakes precision" — and it is not a
theoretical concern: `test_ambiguous_hour_moves_the_ascendant_a_whole_sign`
below pins the measured consequence.
"""

import datetime as dt

import pytest

from engine.orchestrator import build_profile
from engine.systems.astrology import CONFIDENCE_NO_TIME
from engine.systems.astrology import CONFIDENCE_UNCERTAIN_TIME as ASTROLOGY_UNCERTAIN
from engine.systems.gene_keys import CONFIDENCE_UNCERTAIN_TIME as GENE_KEYS_UNCERTAIN
from engine.systems.human_design import CONFIDENCE_UNCERTAIN_TIME as HD_UNCERTAIN
from engine.types import BirthInput, BirthTimeQuality

# 1990-10-28 01:30 Europe/London: British Summer Time ended at 02:00 BST, so
# the clock went back to 01:00 GMT and read 01:30 twice.
AMBIGUOUS = dict(
    full_name="Robin Hale",
    birth_date=dt.date(1990, 10, 28),
    birth_time=dt.time(1, 30),
    lat=51.5074,
    lon=-0.1278,
    tz="Europe/London",
    hebrew_name=None,
)

# 1990-04-01 02:30 America/New_York: EST became EDT at 02:00, so the clock
# jumped straight from 01:59:59 to 03:00 and never showed 02:30.
NONEXISTENT = dict(
    full_name="Casey Rivera",
    birth_date=dt.date(1990, 4, 1),
    birth_time=dt.time(2, 30),
    lat=40.7128,
    lon=-74.0060,
    tz="America/New_York",
    hebrew_name=None,
)

ORDINARY = dict(
    full_name="Ada Lovelace",
    birth_date=dt.date(1815, 12, 10),
    birth_time=dt.time(13, 0),
    lat=51.5074,
    lon=-0.1278,
    tz="Europe/London",
    hebrew_name=None,
)

CHART_SYSTEMS = ("astrology", "human_design", "gene_keys")
DATE_ONLY_SYSTEMS = ("numerology", "chinese_zodiac", "kabbalah")


# --- detection -----------------------------------------------------------


def test_ambiguous_local_time_is_classified_ambiguous():
    assert BirthInput(**AMBIGUOUS).birth_time_quality is BirthTimeQuality.AMBIGUOUS


def test_nonexistent_local_time_is_classified_nonexistent():
    assert BirthInput(**NONEXISTENT).birth_time_quality is BirthTimeQuality.NONEXISTENT


def test_ordinary_local_time_is_classified_exact():
    assert BirthInput(**ORDINARY).birth_time_quality is BirthTimeQuality.EXACT


def test_absent_local_time_is_classified_missing():
    assert BirthInput(**{**ORDINARY, "birth_time": None}).birth_time_quality is (
        BirthTimeQuality.MISSING
    )


def test_the_two_directions_are_not_confused():
    """Both cases share `fold=0 offset != fold=1 offset`; only the *sign* of
    the change separates them. A check that tested the difference alone
    without its direction would pass on this pair with the labels swapped."""
    ambiguous = BirthInput(**AMBIGUOUS)
    nonexistent = BirthInput(**NONEXISTENT)
    assert ambiguous.birth_time_quality is not nonexistent.birth_time_quality


def test_only_ambiguous_and_nonexistent_are_uncertain():
    assert BirthInput(**AMBIGUOUS).birth_time_is_uncertain
    assert BirthInput(**NONEXISTENT).birth_time_is_uncertain
    assert not BirthInput(**ORDINARY).birth_time_is_uncertain
    assert not BirthInput(**{**ORDINARY, "birth_time": None}).birth_time_is_uncertain


def test_ordinary_and_missing_times_carry_no_birth_time_note():
    assert BirthInput(**ORDINARY).birth_time_note is None
    assert BirthInput(**{**ORDINARY, "birth_time": None}).birth_time_note is None


def test_uncertain_notes_name_the_case_the_zone_and_the_assumption():
    ambiguous_note = BirthInput(**AMBIGUOUS).birth_time_note
    assert "ambiguous" in ambiguous_note
    assert "Europe/London" in ambiguous_note
    assert "01:30" in ambiguous_note
    assert "first" in ambiguous_note  # names what was assumed

    nonexistent_note = BirthInput(**NONEXISTENT).birth_time_note
    assert "never occurred" in nonexistent_note
    assert "America/New_York" in nonexistent_note
    assert "02:30" in nonexistent_note


# --- the magnitude the fix exists for ------------------------------------


def test_ambiguous_hour_moves_the_ascendant_a_whole_sign():
    """The measured consequence, pinned so it cannot quietly shrink.

    The two readings of 1990-10-28 01:30 Europe/London are 60 minutes apart.
    Over 60 minutes the Ascendant advances ~15 degrees — half a sign — and
    here it crosses a sign boundary, so a *different* `astrology/ascendants`
    knowledge-base entry fires and different tags reach synthesis.
    """
    from zoneinfo import ZoneInfo

    from engine.ephemeris import get_ephemeris
    from engine.systems.astrology import sign_of

    eph = get_ephemeris()
    local = dt.datetime.combine(
        AMBIGUOUS["birth_date"], AMBIGUOUS["birth_time"], tzinfo=ZoneInfo(AMBIGUOUS["tz"])
    )
    signs = []
    for fold in (0, 1):
        jd = eph.julian_day(local.replace(fold=fold).astimezone(dt.UTC))
        houses = eph.houses(jd, AMBIGUOUS["lat"], AMBIGUOUS["lon"])
        signs.append(sign_of(houses.ascendant))

    (sign_a, deg_a), (sign_b, deg_b) = signs
    assert (sign_a, round(deg_a, 2)) == ("Leo", 27.33)
    assert (sign_b, round(deg_b, 2)) == ("Virgo", 7.84)
    assert sign_a != sign_b


def test_ambiguous_hour_moves_a_human_design_line():
    """The same one-hour window also shifts the fastest Human Design point.

    The Moon covers ~0.55 degrees an hour against a 0.9375-degree line, so a
    line change is likely — here the personality Moon moves from line 5 to
    line 6. Gate assignments (5.625 degrees wide) are far more robust, which
    is exactly why Human Design's uncertain-time confidence sits above
    astrology's.
    """
    from zoneinfo import ZoneInfo

    from engine.ephemeris import get_ephemeris
    from engine.systems.hd_wheel import activations

    eph = get_ephemeris()
    local = dt.datetime.combine(
        AMBIGUOUS["birth_date"], AMBIGUOUS["birth_time"], tzinfo=ZoneInfo(AMBIGUOUS["tz"])
    )
    sides = [
        activations(eph, eph.julian_day(local.replace(fold=fold).astimezone(dt.UTC)))
        for fold in (0, 1)
    ]
    assert (sides[0]["moon"].gate, sides[0]["moon"].line) == (13, 5)
    assert (sides[1]["moon"].gate, sides[1]["moon"].line) == (13, 6)
    assert sides[0]["sun"].gate == sides[1]["sun"].gate  # the Sun barely moves


def test_utc_datetime_resolves_an_ambiguous_time_to_the_first_occurrence():
    """`fold=0` is retained deliberately (the earlier instant); the point of
    the fix is that the choice is now *declared*, not that it changed."""
    assert BirthInput(**AMBIGUOUS).utc_datetime == dt.datetime(1990, 10, 28, 0, 30, tzinfo=dt.UTC)


def test_utc_datetime_resolves_a_nonexistent_time_with_the_pre_transition_offset():
    assert BirthInput(**NONEXISTENT).utc_datetime == dt.datetime(1990, 4, 1, 7, 30, tzinfo=dt.UTC)


# --- profile-level behaviour ---------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [(AMBIGUOUS, "ambiguous"), (NONEXISTENT, "nonexistent"), (ORDINARY, "exact")],
)
def test_input_quality_reports_the_birth_time_quality(payload, expected):
    assert build_profile(BirthInput(**payload))["input_quality"]["birth_time"] == expected


@pytest.mark.parametrize("payload", [AMBIGUOUS, NONEXISTENT])
@pytest.mark.parametrize("system", CHART_SYSTEMS)
def test_chart_systems_still_compute_on_an_uncertain_time(payload, system):
    """Reduced precision is not absent data: the chart systems must still run
    (unlike the missing-time path, where Human Design and Gene Keys are
    excluded outright)."""
    slot = build_profile(BirthInput(**payload))["raw"][system]
    assert slot.get("available") is not False
    assert slot["confidence"] > 0.0


@pytest.mark.parametrize("payload", [AMBIGUOUS, NONEXISTENT])
@pytest.mark.parametrize("system", CHART_SYSTEMS)
def test_chart_systems_note_the_uncertainty(payload, system):
    notes = build_profile(BirthInput(**payload))["raw"][system]["notes"]
    assert any("ambiguous" in n or "never occurred" in n for n in notes), notes


@pytest.mark.parametrize("payload", [AMBIGUOUS, NONEXISTENT])
def test_chart_system_confidence_is_reduced_but_above_the_missing_time_tier(payload):
    raw = build_profile(BirthInput(**payload))["raw"]
    assert raw["astrology"]["confidence"] == ASTROLOGY_UNCERTAIN
    assert raw["human_design"]["confidence"] == HD_UNCERTAIN
    assert raw["gene_keys"]["confidence"] == GENE_KEYS_UNCERTAIN
    # A one-hour uncertainty is materially less damaging than a 24-hour one.
    assert ASTROLOGY_UNCERTAIN > CONFIDENCE_NO_TIME
    for value in (ASTROLOGY_UNCERTAIN, HD_UNCERTAIN, GENE_KEYS_UNCERTAIN):
        assert 0.0 < value < 1.0


@pytest.mark.parametrize("payload", [AMBIGUOUS, NONEXISTENT])
@pytest.mark.parametrize("system", DATE_ONLY_SYSTEMS)
def test_date_only_systems_are_untouched_by_time_ambiguity(payload, system):
    """Numerology, Chinese zodiac and Kabbalah never read the clock."""
    uncertain = build_profile(BirthInput(**payload))["raw"][system]
    same_date_no_time = build_profile(BirthInput(**{**payload, "birth_time": None}))["raw"][system]
    assert uncertain == same_date_no_time
    assert uncertain["confidence"] > 0.0
    assert not any("ambiguous" in n or "never occurred" in n for n in uncertain["notes"])


def test_ordinary_time_is_unchanged_by_the_fix():
    """The contrast case, so none of the above can pass vacuously."""
    raw = build_profile(BirthInput(**ORDINARY))["raw"]
    assert raw["astrology"]["confidence"] == 1.0
    assert raw["human_design"]["confidence"] == 1.0
    assert raw["gene_keys"]["confidence"] == 1.0
    for system in CHART_SYSTEMS:
        assert raw[system]["notes"] == []
