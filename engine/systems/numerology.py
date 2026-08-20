"""Pythagorean numerology (spec §3.4).

Pure arithmetic — no ephemeris, no birth time. The interpretive choices (how
Life Path components reduce, when Y is a vowel) are fixed here and documented in
the matching KB file headers so a profile is reproducible from the record alone.
"""

from __future__ import annotations

import datetime as dt

from engine.kb.loader import load_kb
from engine.names import NameQuality, normalize
from engine.types import BirthInput, InputField, SystemOutput, TraitTag

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PYTHAGOREAN = {ch: (i % 9) + 1 for i, ch in enumerate(ALPHABET)}
MASTERS = frozenset({11, 22, 33})
BASE_VOWELS = frozenset("AEIOU")


def letter_value(ch: str) -> int:
    return PYTHAGOREAN.get(ch.upper(), 0)


def reduce_number(n: int) -> int:
    """Digit-sum to a single digit, stopping at a master number."""
    while n > 9 and n not in MASTERS:
        n = sum(int(d) for d in str(n))
    return n


def is_vowel(word: str, index: int) -> bool:
    """Fixed Y rule: Y is a vowel iff both neighbours in the word are consonants."""
    ch = word[index]
    if ch in BASE_VOWELS:
        return True
    if ch != "Y":
        return False
    prev_is_vowel = index > 0 and word[index - 1] in BASE_VOWELS
    next_is_vowel = index + 1 < len(word) and word[index + 1] in BASE_VOWELS
    return not (prev_is_vowel or next_is_vowel)


def _name_sum(latin: str, selector) -> int:
    total = 0
    for word in latin.split(" "):
        for i, ch in enumerate(word):
            if selector(word, i):
                total += letter_value(ch)
    return reduce_number(total)


def life_path(date: dt.date) -> int:
    parts = (
        reduce_number(date.month),
        reduce_number(date.day),
        reduce_number(sum(int(d) for d in str(date.year))),
    )
    return reduce_number(sum(parts))


def personal_year(date: dt.date, year: int) -> int:
    parts = (
        reduce_number(date.month),
        reduce_number(date.day),
        reduce_number(sum(int(d) for d in str(year))),
    )
    return reduce_number(sum(parts))


def personal_month(py: int, month: int) -> int:
    return reduce_number(py + month)


class NumerologyCalculator:
    key = "numerology"
    required_inputs = {InputField.FULL_NAME, InputField.BIRTH_DATE}

    def compute(self, inp: BirthInput) -> SystemOutput:
        name = normalize(inp.full_name, inp.hebrew_name)
        latin = name.latin

        lp = life_path(inp.birth_date)
        expression = _name_sum(latin, lambda w, i: True)
        soul_urge = _name_sum(latin, is_vowel)
        personality = _name_sum(latin, lambda w, i: not is_vowel(w, i))
        birthday = reduce_number(inp.birth_date.day)

        raw = {
            "life_path": lp,
            "expression": expression,
            "soul_urge": soul_urge,
            "personality": personality,
            "birthday": birthday,
            "master_numbers": sorted(
                {n for n in (lp, expression, soul_urge, personality, birthday) if n in MASTERS}
            ),
            "latin_name": latin,
            "name_quality": str(name.latin_quality),
        }

        kb = load_kb()
        tags: list[TraitTag] = []
        for element, value in (
            ("life_path", lp),
            ("expression", expression),
            ("soul_urge", soul_urge),
        ):
            tags.extend(kb.tags_for(self.key, element, str(value)))

        notes = list(name.notes) if name.latin_quality is NameQuality.DERIVED else []
        confidence = 0.7 if name.latin_quality is NameQuality.DERIVED else 1.0

        return SystemOutput(raw=raw, tags=tags, confidence=confidence, notes=notes)
