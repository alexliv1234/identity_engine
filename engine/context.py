"""The /context bundle (spec §5.2).

A compact, prompt-injectable block an AI assistant can be given so it knows
who it is talking to. Built **entirely from the synthesis layer** -- the
dimensions, facets, direction labels and convergence scores that
`engine.synthesis.synthesize` already produced -- plus the fixed facet
taxonomy's labels. It never reaches into the raw layer for the default
`plain` vocabulary.

The reason that matters: a consuming app pastes this block into a system
prompt for an assistant that may know nothing about astrology, Human Design,
Gene Keys, numerology, the Chinese zodiac or Kabbalah. In the `plain`
vocabulary the block tells the assistant what the person tends to be like --
not which six-thousand-year-old tradition said so. `ESOTERIC_TERMS` is the
guard that keeps system names and esoteric jargon out of that default path;
`?vocabulary=esoteric` is the opt-in that adds the raw layer's headline
values (Sun sign, Human Design type, Life Path) back in, for a consumer that
wants the chart specifics.
"""

from __future__ import annotations

import math

TOKEN_BUDGET = 350

# Guards the plain vocabulary against leaking system names or esoteric jargon
# (spec §5.2). Covers all six systems now live, not only the two that existed
# when this module was first drafted -- astrology, Human Design, Gene Keys,
# numerology, the Chinese zodiac and Kabbalah. `test_esoteric_guard_would_catch_a_leak`
# in tests/test_context.py proves this list is not merely disjoint from
# everything the generator could ever emit.
ESOTERIC_TERMS: frozenset[str] = frozenset(
    {
        # Astrology
        "astrolog",
        "zodiac",
        "horoscope",
        "natal",
        "ascendant",
        "midheaven",
        "sun sign",
        "moon sign",
        "rising sign",
        "retrograde",
        "conjunction",
        "aries",
        "taurus",
        "gemini",
        "cancer",
        "leo",
        "virgo",
        "libra",
        "scorpio",
        "sagittarius",
        "capricorn",
        "aquarius",
        "pisces",
        # Human Design
        "human design",
        "bodygraph",
        "gate",
        "channel",
        "sacral",
        "splenic",
        "generator",
        "manifestor",
        "projector",
        "reflector",
        "defined center",
        "open center",
        # Gene Keys
        "gene key",
        "hexagram",
        "shadow",
        "siddhi",
        "iching",
        "i ching",
        "activation sequence",
        # Numerology
        "numerolog",
        "life path",
        "destiny number",
        "expression number",
        "soul urge",
        "master number",
        # Chinese zodiac. "rat", "ox", "dog", "pig" and "yin" are deliberately
        # excluded even though they're valid animal/polarity terms: as bare
        # substrings they collide with ordinary English ("deliberation" and
        # "generator" both contain "rat"; "-ying" words like "saying" contain
        # "yin"). A substring-based guard can only be as safe as its terms are
        # distinctive -- the per-fixture sweep in tests/test_context.py is
        # what caught this collision.
        "chinese zodiac",
        "tiger",
        "rabbit",
        "dragon",
        "snake",
        "horse",
        "goat",
        "monkey",
        "rooster",
        "yang",
        # Kabbalah
        "kabbalah",
        "gematria",
        "sefirah",
        "sefirot",
        "tree of life",
        "tikkun",
        "keter",
        "chokmah",
        "binah",
        "chesed",
        "gevurah",
        "tiferet",
        "netzach",
        "malkuth",
    }
)

# (dimension id, heading, json key), in spec §5.2 order. Deliberately five of
# the taxonomy's nine dimensions -- the block is a summary an assistant can
# hold in its head, not a dump of all 32 facets.
SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("core_essence", "Identity snapshot", "identity_snapshot"),
    ("communication", "Communication", "communication"),
    ("decision_making", "Decision style", "decision_style"),
    ("drive", "Motivation levers", "motivation_levers"),
    ("growth_edges", "Cautions", "cautions"),
)

MAX_FACETS_PER_SECTION = 3

# Convergence is the share of *applicable* systems agreeing on a facet's
# direction (engine/synthesis.py). With six systems live, an unremarkable
# single-source facet already reads around 0.17 (1/6), and even a facet every
# applicable system agrees on rarely clears ~0.83 (5/6) in practice, since no
# facet in the fixture suite is ever addressed by all six systems at once.
# Reading these thresholds against that scale (not against a 0-1 "percent
# agreement" intuition) is what keeps the hedge honest:
#   - >= 0.5: at least half of the applicable systems agree -- flagged as
#     corroborated.
#   - <  0.25: one applicable system (or two, out of five-plus) -- flagged as
#     a single indicator, so the assistant does not over-index on it.
#   - in between: the common case, left unmarked.
CONVERGENCE_CORROBORATED = 0.5
CONVERGENCE_SINGLE_SOURCE = 0.25


def estimate_tokens(text: str) -> int:
    """Four characters per token -- documented, deliberate, and errs high for
    English prose (spec §5.2's "~350 tokens" is a budget, not a tokenizer
    contract)."""
    return math.ceil(len(text) / 4)


def _confidence_note(convergence: float) -> str:
    if convergence >= CONVERGENCE_CORROBORATED:
        return " (consistently indicated)"
    if convergence < CONVERGENCE_SINGLE_SOURCE:
        return " (a single indicator)"
    return ""


def _phrase(facet: dict) -> str:
    return f"{facet['label']}: {facet['direction']}{_confidence_note(facet['convergence'])}"


def _esoteric_headline(profile: dict) -> str:
    raw = profile.get("raw", {})
    bits: list[str] = []

    astrology = raw.get("astrology", {})
    for placement in astrology.get("placements", []):
        if placement.get("body") == "sun":
            bits.append(f"Sun in {placement['sign']}")
            break

    hd_type = raw.get("human_design", {}).get("type")
    if hd_type:
        bits.append(hd_type)

    life_path = raw.get("numerology", {}).get("life_path")
    if life_path:
        bits.append(f"Life Path {life_path}")

    return "; ".join(bits)


def build_context(profile: dict, vocabulary: str = "plain") -> dict:
    dimensions = profile.get("synthesis", {}).get("dimensions", {})

    sections: list[tuple[str, str, list[str]]] = []
    for dim_id, heading, json_key in SECTIONS:
        dim = dimensions.get(dim_id)
        if not dim or not dim["facets"]:
            continue
        lines = [_phrase(f) for f in dim["facets"][:MAX_FACETS_PER_SECTION]]
        sections.append((heading, json_key, lines))

    headline = _esoteric_headline(profile) if vocabulary == "esoteric" else ""

    def render(current: list[tuple[str, str, list[str]]]) -> str:
        parts: list[str] = []
        if headline:
            parts.append(f"Chart headline: {headline}.")
        for heading, _key, lines in current:
            parts.append(f"{heading} — " + "; ".join(lines) + ".")
        return "\n".join(parts)

    # Trim by dropping whole facets, then whole sections -- reverse of the
    # section order above (lowest-priority section first) -- until the
    # rendered text fits the budget. Never truncate mid-sentence: each drop
    # removes a whole facet line, so every render() call above is still a
    # set of complete sentences.
    text = render(sections)
    while estimate_tokens(text) > TOKEN_BUDGET and sections:
        for index in range(len(sections) - 1, -1, -1):
            heading, key, lines = sections[index]
            if len(lines) > 1:
                sections[index] = (heading, key, lines[:-1])
                break
        else:
            sections.pop()
        text = render(sections)

    return {
        "text": text,
        "json": {key: lines for _heading, key, lines in sections},
        "tokens": estimate_tokens(text),
    }
