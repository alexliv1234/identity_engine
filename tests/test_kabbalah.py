# tests/test_kabbalah.py
import datetime as dt

from engine.systems.kabbalah import (
    MISPAR_HECHRECHI,
    KabbalahCalculator,
    gematria,
    gematria_reduced,
    sefirah_for,
)
from engine.types import BirthInput


def make_input(**over):
    base = dict(
        full_name="Avraham Cohen",
        birth_date=dt.date(1947, 5, 14),
        birth_time=dt.time(18, 30),
        lat=31.7683,
        lon=35.2137,
        tz="Asia/Jerusalem",
        hebrew_name="אברהם כהן",
    )
    base.update(over)
    return BirthInput(**base)


def test_letter_values_follow_mispar_hechrechi():
    assert MISPAR_HECHRECHI["א"] == 1
    assert MISPAR_HECHRECHI["י"] == 10
    assert MISPAR_HECHRECHI["ק"] == 100
    assert MISPAR_HECHRECHI["ת"] == 400


def test_final_forms_take_their_base_values():
    assert MISPAR_HECHRECHI["ך"] == MISPAR_HECHRECHI["כ"] == 20
    assert MISPAR_HECHRECHI["ם"] == MISPAR_HECHRECHI["מ"] == 40
    assert MISPAR_HECHRECHI["ן"] == MISPAR_HECHRECHI["נ"] == 50
    assert MISPAR_HECHRECHI["ף"] == MISPAR_HECHRECHI["פ"] == 80
    assert MISPAR_HECHRECHI["ץ"] == MISPAR_HECHRECHI["צ"] == 90


def test_known_gematria_values():
    assert gematria("חי") == 18  # chai
    assert gematria("אמת") == 441  # emet
    assert gematria("שלום") == 376  # shalom
    assert gematria("אברהם") == 248  # Avraham


def test_gematria_ignores_spaces_and_latin_characters():
    assert gematria("אברהם כהן") == gematria("אברהםכהן")
    assert gematria("Avraham") == 0


def test_reduction_is_a_plain_digit_sum():
    assert gematria_reduced(248) == 5  # 2+4+8=14 -> 5
    assert gematria_reduced(18) == 9
    assert gematria_reduced(11) == 2  # no master-number preservation here


def test_sefirah_cycles_through_ten():
    assert sefirah_for(1) == "Keter"
    assert sefirah_for(10) == "Malkhut"
    assert len({sefirah_for(n) for n in range(1, 11)}) == 10


def test_hebrew_date_conversion_for_a_known_date():
    """1947-05-14 (after sunset conventions ignored) is 24 Iyar 5707."""
    raw = KabbalahCalculator().compute(make_input()).raw
    assert raw["hebrew_date"]["year"] == 5707
    assert raw["hebrew_date"]["month_name"] == "Iyar"
    assert raw["hebrew_date"]["day"] == 24


def test_pre_1948_hebrew_date_is_supported():
    raw = KabbalahCalculator().compute(make_input(birth_date=dt.date(1901, 3, 3))).raw
    assert raw["hebrew_date"]["year"] > 5000


def test_supplied_hebrew_name_is_full_confidence():
    out = KabbalahCalculator().compute(make_input())
    assert out.raw["hebrew_name_quality"] == "provided"
    assert out.confidence == 1.0
    assert out.notes == []


def test_derived_hebrew_name_degrades_confidence_and_notes():
    out = KabbalahCalculator().compute(make_input(hebrew_name=None))
    assert out.raw["hebrew_name_quality"] == "derived"
    assert out.confidence < 1.0
    assert out.notes


def test_emits_sefirah_and_month_tags():
    out = KabbalahCalculator().compute(make_input())
    elements = {t.element for t in out.tags}
    assert "sefirot" in elements
    assert "hebrew_months" in elements


def test_output_is_deterministic():
    a = KabbalahCalculator().compute(make_input())
    b = KabbalahCalculator().compute(make_input())
    assert a.raw == b.raw
