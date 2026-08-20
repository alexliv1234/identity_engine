import datetime as dt

from engine.systems.numerology import (
    NumerologyCalculator,
    is_vowel,
    letter_value,
    reduce_number,
)
from engine.types import BirthInput, InputField


def make_input(name="Ada Lovelace", date=dt.date(1815, 12, 10), **over):
    base = dict(
        full_name=name,
        birth_date=date,
        birth_time=dt.time(13, 0),
        lat=51.5074,
        lon=-0.1278,
        tz="Europe/London",
        hebrew_name=None,
    )
    base.update(over)
    return BirthInput(**base)


def test_letter_values_follow_the_pythagorean_grid():
    assert letter_value("A") == 1
    assert letter_value("I") == 9
    assert letter_value("J") == 1
    assert letter_value("R") == 9
    assert letter_value("S") == 1
    assert letter_value("Z") == 8


def test_reduce_preserves_master_numbers():
    assert reduce_number(11) == 11
    assert reduce_number(22) == 22
    assert reduce_number(33) == 33
    assert reduce_number(29) == 11  # 2+9=11, stop
    assert reduce_number(48) == 3  # 4+8=12 -> 3
    assert reduce_number(9) == 9


def test_y_is_a_vowel_only_between_consonants():
    assert is_vowel("LYNN", 1) is True  # L-Y-N: both neighbours consonants
    assert is_vowel("MAYA", 2) is False  # A-Y-A: neighbour is a vowel
    assert is_vowel("YARA", 0) is False  # next letter A is a vowel
    assert is_vowel("SKY", 2) is True  # end of word, previous is a consonant


def test_life_path_reduces_components_separately():
    # 1815-12-10 -> month 12->3, day 10->1, year 1815->1+8+1+5=15->6 ; 3+1+6=10->1
    out = NumerologyCalculator().compute(make_input())
    assert out.raw["life_path"] == 1


def test_life_path_preserves_a_master_result():
    # 1979-11-29: month 11 (master, kept), day 29->11 (master, kept),
    # year 1979 -> 26 -> 8 ; 11+11+8 = 30 -> 3
    out = NumerologyCalculator().compute(make_input(date=dt.date(1979, 11, 29)))
    assert out.raw["life_path"] == 3
    assert out.raw["birthday"] == 11
    assert 11 in out.raw["master_numbers"]


def test_expression_soul_urge_and_personality_partition_the_name():
    out = NumerologyCalculator().compute(make_input(name="Ada"))
    # A=1 D=4 A=1 -> expression 6 ; vowels A,A -> 2 ; consonant D -> 4
    assert out.raw["expression"] == 6
    assert out.raw["soul_urge"] == 2
    assert out.raw["personality"] == 4


def test_required_inputs_do_not_include_birth_time():
    calc = NumerologyCalculator()
    assert calc.required_inputs == {InputField.FULL_NAME, InputField.BIRTH_DATE}
    out = calc.compute(make_input(birth_time=None))
    assert out.confidence == 1.0  # numerology is unaffected by missing time


def test_non_latin_name_degrades_confidence_and_notes():
    out = NumerologyCalculator().compute(make_input(name="Владимир Иванов"))
    assert out.confidence < 1.0
    assert out.notes


def test_emits_tags_for_the_life_path_entry():
    out = NumerologyCalculator().compute(make_input())
    facets = {t.facet for t in out.tags}
    assert facets  # at least one mapped facet
    assert all(t.system == "numerology" for t in out.tags)


def test_output_is_deterministic():
    a = NumerologyCalculator().compute(make_input())
    b = NumerologyCalculator().compute(make_input())
    assert a.raw == b.raw
    assert a.tags == b.tags
