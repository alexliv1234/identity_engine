"""Jewish numerology and Kabbalah (spec §3.5).

The least standardized of the six systems, so every interpretive choice is
recorded: mispar hechrechi (standard values) with final forms taking their base
values; sefirah assigned from the standard (unreduced) gematria of the Hebrew
name — digit-summing first would land on 1-9 and make Malkhut (10)
structurally unreachable, so the sefirah lookup deliberately uses the same
unreduced value the equivalences table already compares against, while
`raw.gematria.reduced` stays a plain digit sum exactly as specified for
display; Hebrew date via pyluach with no sunset adjustment (the birth *date*
is taken as given — see kb/kabbalah/hebrew_months.yaml's source header for the
same note recorded at the KB layer).
"""

from __future__ import annotations

from pyluach import dates as luach
from pyluach import hebrewcal

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
    """Keter at 1 through Malkhut at 10, cycling by ``(value - 1) % 10``.

    Deliberately takes the standard (unreduced) gematria value, not a
    digit-summed one: digit-summing to a single digit can only ever land on
    1-9, which would make Malkhut (10) structurally unreachable. See
    kb/kabbalah/sefirot.yaml's source header for the full reasoning.
    """
    return SEFIROT[(value - 1) % 10]


def _hebrew_date(date) -> dict:
    hd = luach.HebrewDate.from_pydate(date)
    month_name = HEBREW_MONTH_NAMES.get(hd.month, str(hd.month))
    # Adar is split into Adar I / Adar II only in a leap year; HEBREW_MONTH_NAMES
    # labels month 12 "Adar" (correct for a regular year, where it is the only
    # Adar), so a leap year needs the label corrected to "Adar I". The tag
    # lookup below is keyed by month *number*, so this relabeling never affects
    # which KB entry is used -- it only affects the user-visible name.
    if hd.month == 12 and hebrewcal.Year(hd.year).leap:
        month_name = "Adar I"
    return {
        "year": hd.year,
        "month": hd.month,
        "month_name": month_name,
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
        sefirah = sefirah_for(standard) if standard else ""
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
        for eq_key in equivalences:
            tags.extend(kb.tags_for(self.key, "equivalences", eq_key))

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
    Every match's tags are also emitted into `SystemOutput.tags` by the caller
    (`compute`) — an entry with tags that never reach synthesis is dead weight,
    so a matched equivalence contributes to the profile the same way any other
    KB element does.
    """
    kb_file = kb.files.get(("kabbalah", "equivalences"))
    if kb_file is None:
        return []
    return sorted(
        key
        for key, entry in kb_file.entries.items()
        if entry.label.isdigit() and int(entry.label) == standard
    )
