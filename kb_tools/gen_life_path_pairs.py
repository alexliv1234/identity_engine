"""Generates `kb/compatibility/life_path_pairs.yaml` (R67/R70).

**Reads:** nothing at runtime. The `TRAITS` table below is a *hand
transcription* of the one-line essence descriptions already published in
`kb/numerology/life_path.yaml` (e.g. Life Path 1 -> "initiators", "fast-moving
and self-directed"), reduced to two numbers per Life Path -- `tempo` and
`warmth`, both 0..10 -- chosen by this script's author, not derived by any
formula from that file. Anyone re-deriving this table should start from
`kb/numerology/life_path.yaml`'s prose and expect to disagree with some of
these numbers; that disagreement is the point of human review, not a bug.

**Writes:** `kb/compatibility/life_path_pairs.yaml`, all 78 unordered pairs
over `1..9, 11, 22, 33` (`i<=j` over the 12 Life Path numbers). Four pairs
are pinned verbatim to the values the 2026-08-20 API-platform task brief
specified by hand (`PINNED` / `PINNED_TEXT` below); the remaining 74 are
computed from `harmony()` and `text_for()`.

`harmony(a, b)` is a simple, fully deterministic rule: start at 5 (neutral),
add a bonus when both numbers' `warmth` sums high, subtract a penalty for a
large `tempo` gap, and nudge same-number pairs up (slow/warm types resonate)
or down (fast/assertive types compete for the same lane). `text_for` derives
a one-line description from the same two numbers' descriptive phrases plus a
banded closing sentence keyed off the resulting score. Nothing here reads an
LLM or the network (this is not `draft_kb.py`'s "B assist" path) -- it is
arithmetic over a small hand-picked table, which is exactly why it is
auditable but also exactly why it should not be trusted as calibrated.

**Output requires human review before it counts as curated content.** This
script sets `curation: derived_pending_review` on the file it writes (see
`engine/kb/loader.py`), which is a load-time-visible marker, not just this
comment, that the 74 non-pinned entries have not individually been read and
signed off by a person. `reviewed: true` stays as-is (a product-owner
decision tracked separately, see `docs/superpowers/plans/
2026-08-22-plan-03-followups.md`) so the file continues to ship while that
review is pending.

**Known mismatch a reviewer should know about (surfaced in code review,
2026-08-22):** the four PINNED anchors do NOT sit inside the range this
heuristic actually produces. `1-5` and `2-6` are pinned at 9 -- the two
highest scores in the whole 78-entry table -- while `harmony()` itself never
returns higher than 8 for any pair it computes, and most `5-x` pairs
specifically score 2..4 (low warmth, high tempo-gap penalty). So the four
"curated examples" the brief supplied do not represent the model that
generated the other 74; a reviewer should not assume the derived entries
were calibrated to match the pinned ones, because they were not -- the
pinned four were used verbatim, untouched by `harmony()`, and the heuristic
was written independently of them.

Usage: `python kb_tools/gen_life_path_pairs.py` (deterministic; overwrites
`kb/compatibility/life_path_pairs.yaml`). Run it, diff the result, and only
commit if the diff is expected -- the same discipline as any other generator
under `kb_tools/`.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "kb" / "compatibility" / "life_path_pairs.yaml"

NUMBERS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 22, 33]

# (tempo, warmth) on a 0..10 scale -- hand-transcribed from
# kb/numerology/life_path.yaml's essence descriptions (see module docstring).
TRAITS: dict[int, dict[str, object]] = {
    1: dict(tempo=8, warmth=4, noun="initiators", phrase="fast-moving and self-directed"),
    2: dict(tempo=3, warmth=9, noun="partners", phrase="attuned and quick to read the room"),
    3: dict(tempo=7, warmth=6, noun="expressers", phrase="playful and idea-rich"),
    4: dict(tempo=3, warmth=5, noun="builders", phrase="steady and structure-seeking"),
    5: dict(tempo=9, warmth=4, noun="wanderers", phrase="restless and change-hungry"),
    6: dict(tempo=5, warmth=9, noun="caretakers", phrase="responsible and service-minded"),
    7: dict(tempo=2, warmth=3, noun="processors", phrase="inward and solitary"),
    8: dict(tempo=7, warmth=4, noun="stewards", phrase="scale-oriented and driven"),
    9: dict(tempo=5, warmth=6, noun="closers", phrase="broad-minded and idealistic"),
    11: dict(tempo=6, warmth=7, noun="seers", phrase="highly perceptive and sensitive"),
    22: dict(tempo=6, warmth=5, noun="architects", phrase="visionary and practical"),
    33: dict(tempo=5, warmth=9, noun="teachers", phrase="devoted and other-focused"),
}

# Pinned verbatim by the 2026-08-20 API-platform task brief (task-6-brief.md,
# Step 1). Never overridden by harmony()/text_for() -- see the "known
# mismatch" note in the module docstring for why these sit outside the
# heuristic's own range.
PINNED: dict[tuple[int, int], int] = {
    (1, 1): 6,
    (1, 5): 9,
    (2, 6): 9,
    (7, 7): 7,
}
PINNED_TEXT: dict[tuple[int, int], str] = {
    (1, 1): "Two initiators: fast-moving together, prone to competing for the wheel.",
    (1, 5): "Initiative meets appetite for change; high momentum, low routine.",
    (2, 6): "Both oriented to care and attunement; easy warmth, watch for over-accommodation.",
    (7, 7): "Two inward processors: deep understanding, sparse day-to-day signal.",
}


def harmony(a: int, b: int) -> int:
    """0..10 harmony score for the pair, clamped. See the module docstring
    for the rule in words; deliberately simple arithmetic, not a model."""
    ta, tb = TRAITS[a], TRAITS[b]
    warmth_bonus = (ta["warmth"] + tb["warmth"] - 10) // 4
    tempo_penalty = abs(ta["tempo"] - tb["tempo"]) // 3
    score = 5 + warmth_bonus - tempo_penalty
    if a == b:
        # Two of the same number either resonate deeply (slow/warm types) or
        # compete for the same lane (fast/assertive types).
        score += -1 if ta["tempo"] >= 7 else 1
    return max(0, min(10, score))


def text_for(a: int, b: int, score: int) -> str:
    ta, tb = TRAITS[a], TRAITS[b]
    if a == b:
        lead = f"Two {ta['noun']}: both {ta['phrase']}."
    else:
        lead = (
            f"{str(ta['noun']).capitalize()} meet {tb['noun']}: "
            f"{ta['phrase']} alongside {tb['phrase']}."
        )
    if score >= 8:
        tail = "A high-harmony pair; the differences reinforce rather than grate."
    elif score >= 6:
        tail = "A workable, generally easy pair with a minor friction point to watch."
    elif score >= 4:
        tail = "A neutral pair; harmony depends more on the people than the numbers."
    else:
        tail = "A friction-prone pair; the gap takes deliberate effort to bridge."
    return f"{lead} {tail}"


def build_entries() -> dict[str, tuple[int, str]]:
    entries: dict[str, tuple[int, str]] = {}
    for i, a in enumerate(NUMBERS):
        for b in NUMBERS[i:]:
            key = f"{a}-{b}"
            pair = (a, b)
            score = PINNED.get(pair, harmony(a, b))
            text = PINNED_TEXT.get(pair, text_for(a, b, score))
            entries[key] = (score, text)
    return entries


SOURCE_NOTE = """\
schema: kb.mapping.v1
system: compatibility
element: life_path_pairs
reviewed: true
curation: derived_pending_review
source: >-
  Life Path pair-harmony matrix, 0..10 in the label field. Keys are the two
  Life Path numbers sorted ascending and joined with a hyphen, e.g. "1-5".
  Master numbers 11/22/33 are keyed as themselves, not reduced.


  Provenance (R67/R70): 4 of these 78 entries -- "1-1", "1-5", "2-6", "7-7"
  -- were pinned verbatim by the 2026-08-20 API-platform task brief and are
  hand-authored text. The other 74 were generated by
  kb_tools/gen_life_path_pairs.py from a small tempo/warmth heuristic keyed
  off the one-line essence description each Life Path number already has in
  kb/numerology/life_path.yaml (see that script's module docstring for the
  exact rule and for how to re-derive or regenerate every value). Every
  derived entry has a distinct, number-specific sentence, but none of the 74
  has been individually read and signed off by a person -- see this file's
  `curation: derived_pending_review` field and
  docs/superpowers/plans/2026-08-22-plan-03-followups.md for the tracked
  review gate. Notably, the 4 pinned anchors sit OUTSIDE the range the
  heuristic itself produces: "1-5" and "2-6" score 9, the two highest values
  in the table, while harmony() never scores a derived pair above 8 and most
  "5-x" pairs score 2..4 -- so the pinned examples should not be read as
  representative of, or calibrated against, the model that generated the
  rest.
entries:
"""


def render() -> str:
    lines = [SOURCE_NOTE.rstrip("\n")]
    for i, a in enumerate(NUMBERS):
        for b in NUMBERS[i:]:
            key = f"{a}-{b}"
            score, text = build_entries()[key]
            lines.append(f'  "{key}":')
            lines.append(f'    label: "{score}"')
            lines.append(f'    text: "{text}"')
            lines.append("    tags: []")
    return "\n".join(lines) + "\n"


def main() -> None:
    text = render()
    OUT_PATH.write_text(text, encoding="utf-8", newline="\n")
    entries = build_entries()
    print(f"wrote {len(entries)} entries to {OUT_PATH}")
    for k in ("1-1", "1-5", "2-6", "7-7"):
        print(" pinned", k, entries[k])


if __name__ == "__main__":
    main()
