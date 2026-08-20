"""Gene Keys Activation Sequence (spec §3.3).

Reuses the shared I-Ching wheel from hd_wheel, deliberately not the Human
Design calculator: the two systems share gate math, not bodygraph logic
(spec correction 5c, see hd_wheel.py). engine/systems/gene_keys.py must never
import engine/systems/human_design.py -- tests/test_gene_keys.py enforces
this with an AST-based guard, the same pattern tests/test_hd_wheel.py uses to
guard hd_wheel itself. At the same time the two systems must agree exactly on
gate numbers for the same birth input, since both derive them from the same
hd_wheel substrate; tests/test_gene_keys.py cross-checks that agreement by
importing HumanDesignCalculator in the test (not in this module).
"""

from __future__ import annotations

from engine.ephemeris import get_ephemeris
from engine.kb.loader import KBEntry, load_kb
from engine.systems.hd_wheel import activations, cached_design_julian_day
from engine.types import BirthInput, InputField, SystemOutput, TraitTag

# (label, side, point) -- the four points of spec §3.3's Activation Sequence.
SEQUENCE: tuple[tuple[str, str, str], ...] = (
    ("lifes_work", "personality", "sun"),
    ("evolution", "personality", "earth"),
    ("radiance", "design", "sun"),
    ("purpose", "design", "earth"),
)


class GeneKeysCalculator:
    key = "gene_keys"
    required_inputs = {InputField.BIRTH_DATE, InputField.BIRTH_TIME, InputField.BIRTH_PLACE}

    def compute(self, inp: BirthInput) -> SystemOutput:
        if inp.birth_time is None:
            return SystemOutput(
                raw={"available": False},
                tags=[],
                confidence=0.0,
                notes=[
                    "birth time missing: Gene Keys derives from the same "
                    "Sun/Earth gate math as Human Design and is excluded "
                    "from synthesis for the same reason -- there is no "
                    "design moment to solve for without an exact birth time"
                ],
            )

        eph = get_ephemeris()
        natal_jd = eph.julian_day(inp.utc_datetime)
        sides = {
            "personality": activations(eph, natal_jd),
            "design": activations(eph, cached_design_julian_day(eph, natal_jd)),
        }

        kb = load_kb()
        sequence: dict[str, dict] = {}
        tags: list[TraitTag] = []

        for label, side, point in SEQUENCE:
            act = sides[side][point]
            entry = kb.entry(self.key, "keys", str(act.gate))
            spectrum = _spectrum(entry)
            sequence[label] = {
                "gene_key": act.gate,
                "line": act.line,
                "shadow": spectrum["shadow"],
                "gift": spectrum["gift"],
                "siddhi": spectrum["siddhi"],
            }
            tags.extend(kb.tags_for(self.key, "keys", str(act.gate)))

        return SystemOutput(
            raw={"activation_sequence": sequence, "available": True},
            tags=tags,
            confidence=1.0,
            notes=[],
        )


def _spectrum(entry: KBEntry | None) -> dict[str, str]:
    """Shadow/gift/siddhi keywords, encoded in the KB entry label as
    'Shadow|Gift|Siddhi' -- a structural contract, not a cosmetic format:
    kb/gene_keys/keys.yaml's header documents it, and
    tests/test_kb_validation.py's label-shape test pins every one of the 64
    entries to exactly three non-empty parts, so a missing or reordered part
    fails the build rather than silently producing a blank or shifted
    spectrum here."""
    if entry is None:
        return {"shadow": "", "gift": "", "siddhi": ""}
    parts = [p.strip() for p in entry.label.split("|")]
    while len(parts) < 3:
        parts.append("")
    return {"shadow": parts[0], "gift": parts[1], "siddhi": parts[2]}
