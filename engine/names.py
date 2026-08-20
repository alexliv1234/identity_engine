"""Name normalization.

Numerology needs Latin letters; gematria needs Hebrew letters. When the caller
supplies only one, we derive the other through a fixed table and mark it DERIVED
so the profile can report reduced confidence rather than fake precision (§8).
"""

from __future__ import annotations

import re
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


def to_hebrew(latin: str) -> str:
    """Fixed-table Latin -> Hebrew transliteration (deterministic, lossy)."""
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

    already_latin = bool(re.fullmatch(r"[A-Za-z .'\-]+", full_name.strip()))
    latin_quality = NameQuality.PROVIDED if already_latin else NameQuality.DERIVED
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
