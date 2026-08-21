"""Western astrology (spec §3.1).

Degrades rather than fails when the birth time is unknown: no houses, no
angles, the Moon is reported as a sign range if it crosses a boundary that
day, and the Moon's *aspects* are segregated out of the fact list (see
"Moon aspects" below). It also degrades — separately — when Placidus houses
have no solution for the given latitude (or the cusp solver fails to
converge): `engine.ephemeris.HousesUnavailable` is caught here and turned
into the same kind of honest "no houses" degradation, with a note naming the
real reason (latitude) rather than reusing the missing-birth-time note. The
two degradations never stack into two notes: houses are only ever attempted
when a birth time is known, so when the birth time is missing the missing-
time note alone already fully explains the absence of houses, and a latitude
that would *also* be unsolvable does not add a second, redundant note on top
of it (see `AstrologyCalculator.compute`).

**Uncertain birth times.** A supplied time that is ambiguous (the clock read
it twice when DST ended) or nonexistent (the clock skipped it when DST began)
is *reduced precision, not absent data*: the full chart is still computed
from `BirthInput.utc_datetime`'s declared `fold=0` resolution, and the
degradation is a note plus a reduced confidence rather than dropped output.
See `CONFIDENCE_UNCERTAIN_TIME` for how that number was chosen.

**Moon aspects.** The Moon covers ~13 degrees a day. Between local midnight
and 23:59 it therefore gains and loses aspects outright — measured on the
1815-12-10 fixture, the Moon's aspect set at 00:00, noon and 23:59 are three
different sets. Publishing the noon set in `raw.aspects` alongside the Sun's,
with the same four-decimal orbs and no qualification, states as fact
something the engine does not know; spec §5.3's `/compatibility` scores
inter-chart aspects across Sun, Moon, Venus, Mars and Ascendant and would
consume it as such. So on the missing-time path `raw.aspects` carries only
the slower pairs and the Moon's aspects move to
`raw.moon_aspects_uncertain` — segregated rather than deleted, so nothing is
lost, but a consumer reading `aspects` gets facts by default.
"""

from __future__ import annotations

import datetime as dt
from itertools import combinations
from zoneinfo import ZoneInfo

from engine.ephemeris import Body, HousesUnavailable, Position, arc_between, get_ephemeris, norm360
from engine.kb.loader import load_kb
from engine.types import BirthInput, InputField, SystemOutput, TraitTag

SIGNS = (
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

# name -> (exact angle, default orb)
ASPECTS: dict[str, tuple[float, float]] = {
    "conjunction": (0.0, 8.0),
    "opposition": (180.0, 8.0),
    "trine": (120.0, 7.0),
    "square": (90.0, 7.0),
    "sextile": (60.0, 5.0),
}

NOON = dt.time(12, 0)
MOON = str(Body.MOON)

#: No birth time at all: a 24-hour window. The Ascendant and houses are gone
#: outright (the Ascendant traverses the entire zodiac in a day) and the Moon
#: is frequently ambiguous, so only the Sun sign survives as a certainty.
CONFIDENCE_NO_TIME = 0.6

#: An ambiguous or nonexistent reading: a *one-hour* window (the DST shift),
#: not twenty-four, so it must not reuse CONFIDENCE_NO_TIME. Derived from what
#: the three tag sources actually risk over one hour:
#:
#:   * Sun sign      — the Sun moves ~0.04 deg/hour against a 30 deg sign, so
#:                     the sign is invariant.                    reliability 1.00
#:   * Moon sign     — ~0.55 deg/hour against 30 deg: a boundary
#:                     crossing lands in ~1.8% of cases.         reliability 0.98
#:   * Ascendant     — ~15 deg/hour against 30 deg: the rising
#:                     sign changes about half the time.         reliability 0.50
#:
#: Their mean is 0.83. Floored to 0.8 because house placements move by roughly
#: half a sign too, which the three-way mean does not price in. Measured on
#: 1990-10-28 01:30 Europe/London the Ascendant really does move Leo 27.33 ->
#: Virgo 7.84 between the two readings, firing a different `ascendants` KB
#: entry (tests/test_birth_time_quality.py pins this).
CONFIDENCE_UNCERTAIN_TIME = 0.8


def sign_of(longitude: float) -> tuple[str, float]:
    lon = norm360(longitude)
    index = int(lon // 30.0)
    return SIGNS[index], lon - index * 30.0


def house_of(longitude: float, cusps: tuple[float, ...]) -> int:
    """Which house a longitude falls in, handling the 0/360 wrap."""
    lon = norm360(longitude)
    for i in range(12):
        start, end = cusps[i], cusps[(i + 1) % 12]
        span = norm360(end - start)
        if norm360(lon - start) < span:
            return i + 1
    return 12  # unreachable for well-formed cusps; keeps the return type total


def aspects_between(positions: dict[Body, Position]) -> list[dict]:
    found: list[dict] = []
    for a, b in combinations(sorted(positions, key=str), 2):
        separation = arc_between(positions[a].longitude, positions[b].longitude)
        for name, (exact, orb) in ASPECTS.items():
            delta = abs(separation - exact)
            if delta <= orb:
                first, second = sorted((str(a), str(b)))
                found.append(
                    {
                        "a": first,
                        "b": second,
                        "aspect": name,
                        "orb": round(delta, 4),
                        "exact": exact,
                    }
                )
                break  # aspect windows do not overlap; first match wins
    found.sort(key=lambda x: (x["a"], x["b"], x["aspect"]))
    return found


def _involves_moon(aspect: dict) -> bool:
    return MOON in (aspect["a"], aspect["b"])


def _moon_sign_range(eph, inp: BirthInput) -> list[str] | None:
    """Signs the Moon occupies between local midnight and 23:59 on the birth date."""
    tz = ZoneInfo(inp.tz)
    edges = []
    for clock in (dt.time(0, 0), dt.time(23, 59)):
        moment = dt.datetime.combine(inp.birth_date, clock, tzinfo=tz).astimezone(dt.UTC)
        edges.append(sign_of(eph.position(eph.julian_day(moment), Body.MOON).longitude)[0])
    return None if edges[0] == edges[1] else edges


class AstrologyCalculator:
    key = "astrology"
    # Deliberately excludes BIRTH_TIME: this system degrades, it is not skipped.
    required_inputs = {InputField.BIRTH_DATE, InputField.BIRTH_PLACE}

    def compute(self, inp: BirthInput) -> SystemOutput:
        eph = get_ephemeris()
        notes: list[str] = []
        has_time = inp.birth_time is not None

        if has_time:
            moment = inp.utc_datetime
        else:
            moment = dt.datetime.combine(inp.birth_date, NOON, tzinfo=ZoneInfo(inp.tz)).astimezone(
                dt.UTC
            )
            notes.append(
                "birth time missing: chart computed for local noon; no houses or "
                "angles are reported"
            )

        # An ambiguous or nonexistent reading still produces a full chart --
        # it is one of two candidate instants, or the resolution of a skipped
        # one, not an absence. Say which, and by how much it could be wrong.
        if inp.birth_time_is_uncertain:
            notes.append(
                f"{inp.birth_time_note} Over that window the Ascendant advances "
                "roughly 15 degrees an hour -- up to half a sign -- so the rising "
                "sign, the Midheaven and the house placements may all differ for "
                "the alternative reading; the Sun sign cannot, and the Moon sign "
                "almost certainly does not."
            )

        jd = eph.julian_day(moment)
        positions = eph.positions(jd, list(Body))

        # Houses are only ever attempted when a birth time is known. This is
        # what keeps the two degradation paths from ever colliding: when the
        # birth time is missing, the note above already fully explains the
        # absent houses, so a latitude that would *also* fail to solve adds
        # no new information and is never separately reported.
        houses = None
        if has_time:
            try:
                houses = eph.houses(jd, inp.lat, inp.lon)
            except HousesUnavailable:
                notes.append(
                    f"birth latitude {inp.lat} is beyond the range where Placidus "
                    "house cusps are defined (near or above the polar circle), or "
                    "the cusp solver did not converge: no houses or angles are "
                    "reported"
                )

        moon_range = None if has_time else _moon_sign_range(eph, inp)
        if moon_range:
            notes.append(
                f"moon changed sign on the birth date ({moon_range[0]} to "
                f"{moon_range[1]}): moon contributes no traits"
            )

        placements: list[dict] = []
        for body in sorted(positions, key=str):
            pos = positions[body]
            sign, degree = sign_of(pos.longitude)
            entry = {
                "body": str(body),
                "sign": sign,
                "degree": round(degree, 4),
                "retrograde": pos.retrograde,
            }
            if houses is not None:
                entry["house"] = house_of(pos.longitude, houses.cusps)
            placements.append(entry)

        angles = None
        if houses is not None:
            asc_sign, asc_deg = sign_of(houses.ascendant)
            mc_sign, mc_deg = sign_of(houses.midheaven)
            angles = {
                "ascendant": {"sign": asc_sign, "degree": round(asc_deg, 4)},
                "midheaven": {"sign": mc_sign, "degree": round(mc_deg, 4)},
            }

        # See the module docstring: with a known time every aspect is a fact
        # and the list stays whole (`moon_aspects_uncertain` is null, not an
        # empty list, mirroring `angles` and `moon_sign_range`). Without one,
        # the Moon's aspects are noon-chart estimates and move out of the way.
        every_aspect = aspects_between(positions)
        aspects = every_aspect
        moon_aspects_uncertain = None
        if not has_time:
            aspects = [a for a in every_aspect if not _involves_moon(a)]
            moon_aspects_uncertain = [a for a in every_aspect if _involves_moon(a)]
            if moon_aspects_uncertain:
                notes.append(
                    "birth time missing: the moon moves roughly 13 degrees a day, "
                    "enough to gain and lose aspects between midnight and midnight, "
                    "so its aspects in the noon chart are estimates rather than "
                    "facts. They are reported separately under "
                    "`moon_aspects_uncertain` and must not be consumed as exact; "
                    "`aspects` carries only the slower-moving pairs (at most about "
                    "1.5 degrees of motion across the date, against 5-8 degree orbs)"
                )

        raw = {
            "placements": placements,
            "aspects": aspects,
            "moon_aspects_uncertain": moon_aspects_uncertain,
            "angles": angles,
            "houses_available": houses is not None,
            "moon_sign_range": moon_range,
        }

        kb = load_kb()
        tags: list[TraitTag] = []
        sun_sign = sign_of(positions[Body.SUN].longitude)[0]
        tags.extend(kb.tags_for(self.key, "sun_signs", sun_sign.lower()))
        if moon_range is None:
            moon_sign = sign_of(positions[Body.MOON].longitude)[0]
            tags.extend(kb.tags_for(self.key, "moon_signs", moon_sign.lower()))
        if angles is not None:
            tags.extend(kb.tags_for(self.key, "ascendants", angles["ascendant"]["sign"].lower()))

        if not has_time:
            confidence = CONFIDENCE_NO_TIME
        elif inp.birth_time_is_uncertain:
            confidence = CONFIDENCE_UNCERTAIN_TIME
        else:
            confidence = 1.0

        return SystemOutput(raw=raw, tags=tags, confidence=confidence, notes=notes)
