import datetime as dt

from engine.systems.chinese_zodiac import ChineseZodiacCalculator, zodiac_year
from engine.types import BirthInput, InputField


def make_input(date, **over):
    base = dict(
        full_name="Test Person",
        birth_date=date,
        birth_time=None,
        lat=39.9042,
        lon=116.4074,
        tz="Asia/Shanghai",
        hebrew_name=None,
    )
    base.update(over)
    return BirthInput(**base)


def compute(date):
    return ChineseZodiacCalculator().compute(make_input(date)).raw


def test_anchor_year_1984_is_yang_wood_rat():
    raw = compute(dt.date(1984, 6, 1))
    assert raw == {
        "animal": "Rat",
        "element": "Wood",
        "polarity": "yang",
        "zodiac_year": 1984,
        "new_year_date": "1984-02-02",
    }


def test_january_birthday_belongs_to_the_previous_zodiac_year():
    # CNY 1984 fell on 1984-02-02, so 1984-01-15 is still the 1983 Water Pig year.
    assert zodiac_year(dt.date(1984, 1, 15)) == 1983
    raw = compute(dt.date(1984, 1, 15))
    assert raw["animal"] == "Pig"
    assert raw["element"] == "Water"
    assert raw["polarity"] == "yin"


def test_day_before_and_day_of_new_year_differ():
    before = compute(dt.date(1984, 2, 1))
    on = compute(dt.date(1984, 2, 2))
    assert before["animal"] != on["animal"]
    assert on["animal"] == "Rat"


def test_element_advances_every_two_years():
    assert compute(dt.date(1984, 6, 1))["element"] == "Wood"
    assert compute(dt.date(1985, 6, 1))["element"] == "Wood"
    assert compute(dt.date(1986, 6, 1))["element"] == "Fire"


def test_sixty_year_cycle_repeats():
    a = compute(dt.date(1984, 6, 1))
    b = compute(dt.date(2044, 6, 1)) if dt.date(2044, 6, 1) <= dt.date.today() else None
    older = compute(dt.date(1924, 6, 1))
    assert (older["animal"], older["element"], older["polarity"]) == (
        a["animal"],
        a["element"],
        a["polarity"],
    )
    assert b is None or (b["animal"], b["element"]) == (a["animal"], a["element"])


def test_requires_only_birth_date():
    assert ChineseZodiacCalculator().required_inputs == {InputField.BIRTH_DATE}
    out = ChineseZodiacCalculator().compute(make_input(dt.date(1984, 6, 1)))
    assert out.confidence == 1.0
    assert out.notes == []


def test_emits_animal_and_element_tags():
    out = ChineseZodiacCalculator().compute(make_input(dt.date(1984, 6, 1)))
    elements = {t.element for t in out.tags}
    assert elements == {"animals", "elements"}


# --- lunardate range [1900, 2100) and the Jan 21 - Feb 20 window rule ------
#
# `lunardate` only covers Gregorian years 1900-2099. Outside the Jan 21 -
# Feb 20 window that Chinese New Year always falls in (verified empirically
# across that whole range: earliest 21 Jan in 1966, latest 20 Feb in 1920),
# the zodiac-year boundary is decidable by calendar arithmetic alone and
# never needs the table — so it works even for years the table doesn't
# cover. Only a date inside the window, in a year outside [1900, 2099],
# genuinely can't be resolved.


def test_pre_1900_date_outside_window_is_decided_without_the_table():
    # Ada Lovelace, born 1815-12-10 -- real-world Wood Pig, yin.
    raw = compute(dt.date(1815, 12, 10))
    assert raw["zodiac_year"] == 1815
    assert raw["animal"] == "Pig"
    assert raw["element"] == "Wood"
    assert raw["polarity"] == "yin"
    assert raw["new_year_date"] is None
    out = ChineseZodiacCalculator().compute(make_input(dt.date(1815, 12, 10)))
    assert out.confidence == 1.0
    assert out.notes == []


def test_pre_1900_date_inside_window_cannot_be_determined():
    raw = compute(dt.date(1815, 2, 1))
    assert raw == {
        "animal": None,
        "element": None,
        "polarity": None,
        "zodiac_year": None,
        "new_year_date": None,
    }
    out = ChineseZodiacCalculator().compute(make_input(dt.date(1815, 2, 1)))
    assert out.confidence < 1.0
    assert len(out.notes) == 1
    assert "1815" in out.notes[0]
    assert out.tags == []


def test_window_boundaries_decide_without_the_table_even_pre_1900():
    # Jan 20: still on/before the earliest-ever CNY minus one day -> previous year.
    assert zodiac_year(dt.date(1815, 1, 20)) == 1814
    # Feb 21: already past the latest-ever CNY -> this year.
    assert zodiac_year(dt.date(1815, 2, 21)) == 1815
