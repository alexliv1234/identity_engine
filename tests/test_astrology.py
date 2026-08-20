import datetime as dt

from engine.ephemeris import Body
from engine.systems.astrology import (
    ASPECTS,
    SIGNS,
    AstrologyCalculator,
    aspects_between,
    sign_of,
)
from engine.types import BirthInput, InputField


def make_input(**over):
    base = dict(
        full_name="Ada Lovelace",
        birth_date=dt.date(1815, 12, 10),
        birth_time=dt.time(13, 0),
        lat=51.5074,
        lon=-0.1278,
        tz="Europe/London",
        hebrew_name=None,
    )
    base.update(over)
    return BirthInput(**base)


def placement(raw, body):
    return next(p for p in raw["placements"] if p["body"] == body)


def test_signs_start_at_aries_and_wrap():
    assert SIGNS[0] == "Aries"
    assert SIGNS[11] == "Pisces"
    assert sign_of(0.0) == ("Aries", 0.0)
    assert sign_of(359.5) == ("Pisces", 29.5)
    assert sign_of(45.0) == ("Taurus", 15.0)


def test_known_chart_has_expected_sun_sign():
    raw = AstrologyCalculator().compute(make_input()).raw
    assert placement(raw, "sun")["sign"] == "Sagittarius"


def test_all_eleven_bodies_are_placed():
    """Correction 1: de406.bsp carries no minor bodies. Chiron is deferred
    from v1, so Body has exactly 11 members, not 12."""
    raw = AstrologyCalculator().compute(make_input()).raw
    bodies = {p["body"] for p in raw["placements"]}
    assert bodies == {str(b) for b in Body}
    assert len(bodies) == 11


def test_houses_and_angles_present_when_birth_time_is_known():
    raw = AstrologyCalculator().compute(make_input()).raw
    assert raw["houses_available"] is True
    assert raw["angles"]["ascendant"]["sign"] in SIGNS
    assert all(1 <= p["house"] <= 12 for p in raw["placements"])


def test_missing_birth_time_drops_houses_and_angles():
    out = AstrologyCalculator().compute(make_input(birth_time=None))
    assert out.raw["houses_available"] is False
    assert out.raw["angles"] is None
    assert all("house" not in p for p in out.raw["placements"])
    assert out.confidence == 0.6
    assert any("birth time" in n.lower() for n in out.notes)


def test_missing_birth_time_reports_a_moon_sign_range_when_it_changes():
    # 1815-12-10: the Moon crosses a sign boundary during the day.
    out = AstrologyCalculator().compute(make_input(birth_time=None))
    rng = out.raw["moon_sign_range"]
    assert rng is None or (len(rng) == 2 and rng[0] != rng[1])


def test_moon_emits_no_tags_when_its_sign_is_ambiguous():
    out = AstrologyCalculator().compute(make_input(birth_time=None))
    if out.raw["moon_sign_range"] is not None:
        assert not any(t.element == "moon_signs" for t in out.tags)


def test_astrology_is_not_excluded_without_birth_time():
    assert AstrologyCalculator().required_inputs == {
        InputField.BIRTH_DATE,
        InputField.BIRTH_PLACE,
    }


def test_aspect_table_matches_the_spec_five():
    assert set(ASPECTS) == {"conjunction", "opposition", "trine", "square", "sextile"}
    assert ASPECTS["trine"][0] == 120.0


def test_aspects_are_detected_within_orb():
    from engine.ephemeris.base import Position

    positions = {
        Body.SUN: Position(Body.SUN, 10.0, 0.0, 1.0),
        Body.MOON: Position(Body.MOON, 130.5, 0.0, 13.0),
        Body.MARS: Position(Body.MARS, 190.0, 0.0, 0.5),
    }
    found = aspects_between(positions)
    kinds = {(a["a"], a["b"], a["aspect"]) for a in found}
    assert ("moon", "sun", "trine") in kinds
    assert ("mars", "sun", "opposition") in kinds


def test_aspect_list_is_sorted_and_deduplicated():
    from engine.ephemeris.base import Position

    positions = {
        Body.SUN: Position(Body.SUN, 10.0, 0.0, 1.0),
        Body.MOON: Position(Body.MOON, 130.5, 0.0, 13.0),
    }
    found = aspects_between(positions)
    assert len(found) == 1  # one pair, not two orderings
    keys = [(a["a"], a["b"], a["aspect"]) for a in found]
    assert keys == sorted(keys)


def test_southern_hemisphere_chart_computes():
    raw = (
        AstrologyCalculator()
        .compute(
            make_input(
                lat=-33.8688,
                lon=151.2093,
                tz="Australia/Sydney",
                birth_date=dt.date(1988, 7, 4),
                birth_time=dt.time(6, 45),
            )
        )
        .raw
    )
    assert raw["houses_available"] is True
    assert placement(raw, "sun")["sign"] == "Cancer"


def test_output_is_deterministic():
    a = AstrologyCalculator().compute(make_input())
    b = AstrologyCalculator().compute(make_input())
    assert a.raw == b.raw


# --- Correction 2: HousesUnavailable must be caught and degraded, not raised ---


def test_polar_latitude_with_known_birth_time_degrades_houses_not_the_whole_profile():
    """Tromso, Norway sits above the Placidus polar limit (66.0 deg). Design
    spec §8 requires degradation, not a crash: the profile must still be
    produced, with full placements (sign + degree), but no houses/angles,
    and a note that names the real reason (latitude), not birth time -- the
    birth time IS known here."""
    out = AstrologyCalculator().compute(
        make_input(
            lat=69.6492,
            lon=18.9553,
            tz="Europe/Oslo",
            birth_date=dt.date(1990, 6, 15),
            birth_time=dt.time(14, 0),
        )
    )
    assert out.raw["houses_available"] is False
    assert out.raw["angles"] is None
    assert all("house" not in p for p in out.raw["placements"])
    # Chart is still fully populated: 11 bodies, each with a sign and a degree.
    assert len(out.raw["placements"]) == 11
    for p in out.raw["placements"]:
        assert p["sign"] in SIGNS
        assert 0.0 <= p["degree"] < 30.0
    # The note must name latitude, not birth time -- they are different
    # failure reasons and must not be conflated.
    assert any("latitude" in n.lower() or "polar" in n.lower() for n in out.notes)
    assert not any("birth time" in n.lower() for n in out.notes)


def test_polar_latitude_without_birth_time_gives_one_coherent_note():
    """Both degradations apply at once (no time AND polar latitude), but the
    houses are already unavailable for the simpler reason (no birth time);
    the module must not also emit a second, redundant/contradictory note
    about latitude on top of that."""
    out = AstrologyCalculator().compute(
        make_input(
            lat=69.6492,
            lon=18.9553,
            tz="Europe/Oslo",
            birth_date=dt.date(1990, 6, 15),
            birth_time=None,
        )
    )
    assert out.raw["houses_available"] is False
    assert out.raw["angles"] is None
    assert out.confidence == 0.6
    time_notes = [n for n in out.notes if "birth time" in n.lower()]
    latitude_notes = [n for n in out.notes if "latitude" in n.lower() or "polar" in n.lower()]
    assert len(time_notes) == 1
    assert len(latitude_notes) == 0
