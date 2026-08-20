import datetime as dt

from engine.systems.numerology import (
    NumerologyCalculator,
    is_vowel,
    letter_value,
    life_path,
    personal_month,
    personal_year,
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


def test_letter_values_cover_the_whole_alphabet():
    # Explicit expected table, independent of the (i % 9) + 1 formula the
    # implementation uses internally, so this doesn't just re-check itself.
    expected = {
        "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8, "I": 9,
        "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "O": 6, "P": 7, "Q": 8, "R": 9,
        "S": 1, "T": 2, "U": 3, "V": 4, "W": 5, "X": 6, "Y": 7, "Z": 8,
    }  # fmt: skip
    for letter, value in expected.items():
        assert letter_value(letter) == value, letter


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


def test_y_is_a_vowel_when_every_neighbour_is_also_y():
    # "YYY": no letter in the word is in the fixed AEIOU set, so every Y's
    # neighbour test comes back False and every position is a vowel.
    assert is_vowel("YYY", 0) is True
    assert is_vowel("YYY", 1) is True
    assert is_vowel("YYY", 2) is True


def test_y_is_a_vowel_at_word_start_before_a_consonant():
    # Word-initial Y has no predecessor (index > 0 is False), so it only
    # depends on the successor; "YZ" has a consonant successor -> vowel.
    assert is_vowel("YZ", 0) is True


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


def test_life_path_master_component_survives_to_the_final_sum():
    # 1991-11-09 is the discriminating case: month reduce(11)=11 (master
    # preserved), day reduce(9)=9, year 1+9+9+1=20->2. Sum = 11+9+2 = 22,
    # itself a master, so it stands as the Life Path.
    #
    # This is the case the two tests above cannot catch: substituting a
    # preserved master for its digital root only ever shifts a component by
    # a multiple of 9, which never changes the final digital root *unless*
    # the top-level sum itself lands on 11/22/33. Neither 1815-12-10 nor
    # 1979-11-29 does that, so a naive whole-date digit-sum with no
    # per-component master preservation would pass both of those tests. A
    # naive flatten of 1991-11-09 (1+1+0+9+1+9+9+1 = 31 -> 4) gives 4, not
    # 22 -- this test fails on that implementation and passes on the correct
    # one, so it's the one that actually pins "reduce separately, preserving
    # masters".
    assert life_path(dt.date(1991, 11, 9)) == 22
    out = NumerologyCalculator().compute(make_input(date=dt.date(1991, 11, 9)))
    assert out.raw["life_path"] == 22
    assert 22 in out.raw["master_numbers"]


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


def test_personal_year_for_a_normal_case():
    # Ada Lovelace's birthday 12-10 in calendar year 2024:
    # month reduce(12)=3, day reduce(10)=1, year digits 2+0+2+4=8 -> reduce(8)=8
    # sum = 3+1+8 = 12 -> reduce(12) = 3
    assert personal_year(dt.date(1815, 12, 10), 2024) == 3


def test_personal_year_preserves_a_master_result():
    # personal_year() only reads month/day off the date argument and ignores
    # the date's own calendar year, so the birth year here (2000) is
    # irrelevant -- only month=11, day=9, and the target year=1991 matter:
    # month reduce(11)=11 (master, kept), day reduce(9)=9,
    # target year digits 1+9+9+1=20 -> reduce(20)=2.
    # sum = 11+9+2 = 22, itself a master, so it stands.
    assert personal_year(dt.date(2000, 11, 9), 1991) == 22


def test_personal_month_reduces_personal_year_plus_month():
    # personal_year=3 (from the normal case above), month=2 (February):
    # 3+2=5, already a single digit.
    assert personal_month(3, 2) == 5
    # personal_year=9, month=11 (November): 9+11=20 -> reduce(20)=2+0=2.
    assert personal_month(9, 11) == 2
