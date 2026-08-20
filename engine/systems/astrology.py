"""Western astrology (spec §3.1).

Degrades rather than fails when the birth time is unknown: no houses, no
angles, and the Moon is reported as a sign range if it crosses a boundary
that day. It also degrades — separately — when Placidus houses have no
solution for the given latitude (or the cusp solver fails to converge):
`engine.ephemeris.HousesUnavailable` is caught here and turned into the same
kind of honest "no houses" degradation, with a note naming the real reason
(latitude) rather than reusing the missing-birth-time note. The two
degradations never stack into two notes: houses are only ever attempted when
a birth time is known, so when the birth time is missing the missing-time
note alone already fully explains the absence of houses, and a latitude that
would *also* be unsolvable does not add a second, redundant note on top of
it (see `AstrologyCalculator.compute`).
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
CONFIDENCE_NO_TIME = 0.6


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

        raw = {
            "placements": placements,
            "aspects": aspects_between(positions),
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

        return SystemOutput(
            raw=raw,
            tags=tags,
            confidence=1.0 if has_time else CONFIDENCE_NO_TIME,
            notes=notes,
        )
