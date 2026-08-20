"""Jewish numerology and Kabbalah (spec §3.5).

The least standardized of the six systems, so every interpretive choice is
recorded: mispar hechrechi (standard values) with final forms taking their base
values; sefirah assigned from the reduced gematria of the Hebrew name; Hebrew
date via pyluach with no sunset adjustment (the birth *date* is taken as given).
"""

from __future__ import annotations

from pyluach import dates as luach

from engine.kb.loader import load_kb
from engine.names import NameQuality, normalize
from engine.types import BirthInput, InputField, SystemOutput, TraitTag

_BASE_VALUES = {
    "א": 1,
    "ב": 2,
    "ג": 3,
    "ד": 4,
    "ה": 5,
    "ו": 6,
    "ז": 7,
    "ח": 8,
    "ט": 9,
    "י": 10,
    "כ": 20,
    "ל": 30,
    "מ": 40,
    "נ": 50,
    "ס": 60,
    "ע": 70,
    "פ": 80,
    "צ": 90,
    "ק": 100,
    "ר": 200,
    "ש": 300,
    "ת": 400,
}
# Final forms take their base values in mispar hechrechi.
_FINALS = {"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}

MISPAR_HECHRECHI: dict[str, int] = {
    **_BASE_VALUES,
    **{final: _BASE_VALUES[base] for final, base in _FINALS.items()},
}

SEFIROT = (
    "Keter",
    "Chokhmah",
    "Binah",
    "Chesed",
    "Gevurah",
    "Tiferet",
    "Netzach",
    "Hod",
    "Yesod",
    "Malkhut",
)

HEBREW_MONTH_NAMES = {
    1: "Nisan",
    2: "Iyar",
    3: "Sivan",
    4: "Tammuz",
    5: "Av",
    6: "Elul",
    7: "Tishrei",
    8: "Cheshvan",
    9: "Kislev",
    10: "Tevet",
    11: "Shevat",
    12: "Adar",
    13: "Adar II",
}

CONFIDENCE_DERIVED_NAME = 0.6


def gematria(text: str) -> int:
    return sum(MISPAR_HECHRECHI.get(ch, 0) for ch in text)


def gematria_reduced(value: int) -> int:
    while value > 9:
        value = sum(int(d) for d in str(value))
    return value


def sefirah_for(value: int) -> str:
    """Keter at 1 through Malkhut at 10; values above 10 reduce first."""
    normalized = value if 1 <= value <= 10 else gematria_reduced(value)
    return SEFIROT[(normalized - 1) % 10]


def _hebrew_date(date) -> dict:
    hd = luach.HebrewDate.from_pydate(date)
    return {
        "year": hd.year,
        "month": hd.month,
        "month_name": HEBREW_MONTH_NAMES.get(hd.month, str(hd.month)),
        "day": hd.day,
        "day_of_week": hd.weekday(),
    }


class KabbalahCalculator:
    key = "kabbalah"
    required_inputs = {InputField.FULL_NAME, InputField.BIRTH_DATE}

    def compute(self, inp: BirthInput) -> SystemOutput:
        name = normalize(inp.full_name, inp.hebrew_name)
        derived = name.hebrew_quality is NameQuality.DERIVED

        standard = gematria(name.hebrew)
        reduced = gematria_reduced(standard) if standard else 0
        sefirah = sefirah_for(reduced) if reduced else ""
        hebrew_date = _hebrew_date(inp.birth_date)

        kb = load_kb()
        equivalences = _matching_equivalences(kb, standard)

        raw = {
            "hebrew_name": name.hebrew,
            "hebrew_name_quality": "derived" if derived else "provided",
            "gematria": {"standard": standard, "reduced": reduced},
            "sefirah": sefirah,
            "hebrew_date": hebrew_date,
            "equivalences": equivalences,
        }

        tags: list[TraitTag] = []
        if sefirah:
            tags.extend(kb.tags_for(self.key, "sefirot", sefirah.lower()))
        tags.extend(kb.tags_for(self.key, "hebrew_months", str(hebrew_date["month"])))

        notes: list[str] = []
        confidence = 1.0
        if derived:
            confidence = CONFIDENCE_DERIVED_NAME
            notes.append(
                "no hebrew_name supplied: gematria uses a transliterated name and "
                "is lower confidence"
            )

        return SystemOutput(raw=raw, tags=tags, confidence=confidence, notes=notes)


def _matching_equivalences(kb, standard: int) -> list[str]:
    """Curated equivalences whose value equals this name's gematria (spec §3.5).

    The equivalences file stores its numeric value in each entry's `label`. A
    missing file is not an error — the table is curated and deliberately small.
    """
    kb_file = kb.files.get(("kabbalah", "equivalences"))
    if kb_file is None:
        return []
    return sorted(
        key
        for key, entry in kb_file.entries.items()
        if entry.label.isdigit() and int(entry.label) == standard
    )
