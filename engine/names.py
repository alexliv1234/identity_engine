"""Name normalization.

Numerology needs Latin letters; gematria needs Hebrew letters. When the caller
supplies only one, we derive the other through a fixed table and mark it DERIVED
so the profile can report reduced confidence rather than fake precision (§8).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

from unidecode import unidecode

from engine.errors import EngineError, ErrorCode

_NON_LETTER = re.compile(r"[^A-Z ]+")
_SPACES = re.compile(r"\s+")

# Longest-match-first: digraphs must precede their leading single letters.
LATIN_TO_HEBREW: tuple[tuple[str, str], ...] = (
    ("SH", "ש"),
    ("CH", "ח"),
    ("KH", "כ"),
    ("TZ", "צ"),
    ("TS", "צ"),
    ("PH", "פ"),
    ("TH", "ת"),
    ("A", "א"),
    ("B", "ב"),
    ("C", "ק"),
    ("D", "ד"),
    ("E", "ע"),
    ("F", "פ"),
    ("G", "ג"),
    ("H", "ה"),
    ("I", "י"),
    ("J", "י"),
    ("K", "כ"),
    ("L", "ל"),
    ("M", "מ"),
    ("N", "נ"),
    ("O", "ו"),
    ("P", "פ"),
    ("Q", "ק"),
    ("R", "ר"),
    ("S", "ס"),
    ("T", "ט"),
    ("U", "ו"),
    ("V", "ב"),
    ("W", "ו"),
    ("X", "כס"),
    ("Y", "י"),
    ("Z", "ז"),
)

HEBREW_RANGE = re.compile(r"[֐-׿]")


class NameQuality(StrEnum):
    PROVIDED = "provided"
    DERIVED = "derived"


@dataclass(frozen=True)
class NormalizedName:
    latin: str
    latin_quality: NameQuality
    hebrew: str
    hebrew_quality: NameQuality
    notes: list[str] = field(default_factory=list)


def latin_letters(text: str) -> str:
    """Uppercase A-Z with single spaces between words; everything else dropped.

    Hyphens are treated as word separators (e.g. "Jean-Luc" -> "JEAN LUC"),
    while other punctuation such as apostrophes is dropped with no separator
    (e.g. "O'Brien" -> "OBRIEN").
    """
    folded = unidecode(text).upper().replace("-", " ")
    stripped = _NON_LETTER.sub("", folded)
    return _SPACES.sub(" ", stripped).strip()


def _is_latin_script(text: str) -> bool:
    """True when every *letter* character in text belongs to the Latin script.

    Non-letters (spaces, digits, punctuation, hyphens, apostrophes) are
    ignored and never affect the result. Diacritics are Latin script (e.g.
    "LATIN SMALL LETTER E WITH ACUTE" for the e in "Renee") — only a letter
    from a genuinely different script (Cyrillic, CJK, Hebrew, Arabic, ...)
    makes this false. This is a fixed rule over Unicode character names, with
    no locale or heuristic component, and it never raises on a codepoint with
    no assigned name (such a codepoint is simply treated as non-Latin).
    """
    saw_letter = False
    for ch in text:
        if not ch.isalpha():
            continue
        saw_letter = True
        try:
            char_name = unicodedata.name(ch)
        except ValueError:
            return False
        if not char_name.startswith("LATIN"):
            return False
    return saw_letter


def to_hebrew(latin: str) -> str:
    """Fixed-table Latin -> Hebrew transliteration (deterministic, lossy).

    Assumes `latin` has already had its internal whitespace collapsed (as
    `latin_letters` does); irregular runs of whitespace in the input are
    preserved verbatim in the output rather than being normalized.
    """
    out: list[str] = []
    for word in latin.split(" "):
        i = 0
        while i < len(word):
            for src, dst in LATIN_TO_HEBREW:
                if word.startswith(src, i):
                    out.append(dst)
                    i += len(src)
                    break
            else:
                i += 1
        out.append(" ")
    return "".join(out).strip()


def normalize(full_name: str, hebrew_name: str | None) -> NormalizedName:
    notes: list[str] = []

    latin = latin_letters(full_name)
    if not latin:
        raise EngineError(
            ErrorCode.NAME_UNMAPPABLE,
            "full_name contains no letters that map to the Latin alphabet",
            field="full_name",
        )

    latin_quality = NameQuality.PROVIDED if _is_latin_script(full_name) else NameQuality.DERIVED
    if latin_quality is NameQuality.DERIVED:
        notes.append(
            "full_name is not Latin script: numerology uses a fixed-table "
            "transliteration, reducing confidence"
        )

    if hebrew_name and HEBREW_RANGE.search(hebrew_name):
        hebrew, hebrew_quality = hebrew_name.strip(), NameQuality.PROVIDED
    else:
        hebrew, hebrew_quality = to_hebrew(latin), NameQuality.DERIVED
        notes.append(
            "no hebrew_name supplied: gematria uses a fixed-table Latin->Hebrew "
            "transliteration, reducing confidence"
        )

    return NormalizedName(
        latin=latin,
        latin_quality=latin_quality,
        hebrew=hebrew,
        hebrew_quality=hebrew_quality,
        notes=notes,
    )
