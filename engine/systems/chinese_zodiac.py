"""Chinese zodiac (spec §3.6).

The year boundary is Chinese New Year, not January 1 — a naive Jan-1 boundary
mislabels roughly one birthday in nine.

The brief for this task specified `convertdate.chinese.newyear()` as the
source of Chinese New Year dates. That API does not exist: `convertdate`
(latest published version, 2.4.1, the version this project pins) has never
shipped a Chinese-calendar module — confirmed by inspecting its installed
source tree and its upstream changelog. This module uses `lunardate`
instead, which was verified against the anchor fact this task is built on:
`LunarDate(1984, 1, 1).to_solar_date() == date(1984, 2, 2)`, i.e. 1984's
Chinese New Year.

`lunardate` bundles conversion tables for Gregorian years [1900, 2100) only
and raises outside that range. Rather than guess, or hand-roll a lunisolar
calculation for the pre-1900 remainder (birth dates as early as 1800-01-01
are otherwise valid, per `engine.types.MIN_BIRTH_DATE`), this module exploits
an empirical fact verified across the table's *entire* covered range:
Chinese New Year always falls between 21 January (earliest: 1966) and
20 February (latest: 1920), inclusive. A birth date outside that window is
decidable by calendar arithmetic alone, in any year, without ever consulting
the table:

  - on/before 20 Jan  -> definitely before this year's Chinese New Year
                          -> zodiac year is `date.year - 1`
  - on/after 21 Feb    -> definitely after this year's Chinese New Year
                          -> zodiac year is `date.year`

Only a date inside the 21 Jan - 20 Feb window truly depends on where that
year's Chinese New Year fell, and only there can the table's range limit
matter. For a window date in a year the table doesn't cover, the engine
reports an unknown result (reduced confidence, an explanatory note, and null
zodiac fields) instead of inventing one.
"""

from __future__ import annotations

import datetime as dt
import functools

from lunardate import LunarDate

from engine.kb.loader import load_kb
from engine.types import BirthInput, InputField, SystemOutput, TraitTag

ANIMALS = (
    "Rat",
    "Ox",
    "Tiger",
    "Rabbit",
    "Dragon",
    "Snake",
    "Horse",
    "Goat",
    "Monkey",
    "Rooster",
    "Dog",
    "Pig",
)
ELEMENTS = ("Wood", "Fire", "Earth", "Metal", "Water")
ANCHOR = 4  # 1984 == Wood Rat, yang; (1984 - 4) % 12 == 0 and % 10 == 0

# `lunardate`'s bundled tables cover Gregorian years [MIN, MAX] inclusive;
# it raises ValueError outside that range.
LUNARDATE_MIN_YEAR = 1900
LUNARDATE_MAX_YEAR = 2099

# Chinese New Year always falls in this window (verified across the full
# range `lunardate` covers, 1900-2099 inclusive: earliest 21 Jan in 1966,
# latest 20 Feb in 1920). See module docstring.
WINDOW_START = (1, 21)  # 21 January
WINDOW_END = (2, 20)  # 20 February


@functools.lru_cache(maxsize=512)
def _new_year_from_table(gregorian_year: int) -> dt.date:
    return LunarDate(gregorian_year, 1, 1).to_solar_date()


def new_year(gregorian_year: int) -> dt.date | None:
    """Gregorian date of Chinese New Year for a given Gregorian year.

    None if `gregorian_year` falls outside the range `lunardate` covers
    (1900-2099 inclusive).
    """
    if not LUNARDATE_MIN_YEAR <= gregorian_year <= LUNARDATE_MAX_YEAR:
        return None
    return _new_year_from_table(gregorian_year)


def zodiac_year(date: dt.date) -> int | None:
    """The Chinese zodiac year a Gregorian date belongs to.

    None only when `date` falls inside the 21 Jan - 20 Feb window in a year
    `lunardate`'s table doesn't cover, so the boundary can't be determined.
    """
    month_day = (date.month, date.day)
    if month_day < WINDOW_START:
        return date.year - 1
    if month_day > WINDOW_END:
        return date.year
    cny = new_year(date.year)
    if cny is None:
        return None
    return date.year - 1 if date < cny else date.year


def animal_for(year: int) -> str:
    return ANIMALS[(year - ANCHOR) % 12]


def element_for(year: int) -> str:
    return ELEMENTS[((year - ANCHOR) % 10) // 2]


def polarity_for(year: int) -> str:
    return "yang" if year % 2 == 0 else "yin"


class ChineseZodiacCalculator:
    key = "chinese_zodiac"
    required_inputs = {InputField.BIRTH_DATE}

    def compute(self, inp: BirthInput) -> SystemOutput:
        date = inp.birth_date
        year = zodiac_year(date)
        cny = new_year(date.year)
        new_year_date = cny.isoformat() if cny is not None else None

        if year is None:
            raw = {
                "animal": None,
                "element": None,
                "polarity": None,
                "zodiac_year": None,
                "new_year_date": new_year_date,
            }
            note = (
                f"Chinese New Year for {date.year} falls outside the bundled "
                "lunar calendar table (covers 1900-2099), and this birth date "
                "falls in the window where the zodiac year depends on that "
                "date; the zodiac year, animal, and element could not be "
                "determined."
            )
            return SystemOutput(raw=raw, tags=[], confidence=0.0, notes=[note])

        animal, element = animal_for(year), element_for(year)
        raw = {
            "animal": animal,
            "element": element,
            "polarity": polarity_for(year),
            "zodiac_year": year,
            "new_year_date": new_year_date,
        }

        kb = load_kb()
        tags: list[TraitTag] = [
            *kb.tags_for(self.key, "animals", animal.lower()),
            *kb.tags_for(self.key, "elements", element.lower()),
        ]
        return SystemOutput(raw=raw, tags=tags, confidence=1.0, notes=[])
