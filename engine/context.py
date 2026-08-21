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

import logging
import math
import re

logger = logging.getLogger(__name__)

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
        # Chinese zodiac (ruling R56). "rat", "ox", "dog", "pig" and "yin" were
        # briefly deleted here because *substring containment* made "rat"
        # fire on "deliberation" and "generator". That fix was backwards --
        # it removed the guard's coverage of exactly the terms it exists to
        # catch, on the accident that today's KB never emits them, not on any
        # guarantee that a future `kb/facets.yaml` edit or a `raw`-reading
        # code path never will. The real bug was the matching strategy, not
        # these five terms; word-boundary matching (`ESOTERIC_PATTERN` below)
        # fixes the collision without giving up coverage.
        "chinese zodiac",
        "rat",
        "ox",
        "tiger",
        "rabbit",
        "dragon",
        "snake",
        "horse",
        "goat",
        "monkey",
        "rooster",
        "dog",
        "pig",
        "yin",
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

# Word-boundary alternation over ESOTERIC_TERMS, with an optional trailing
# "s" so a plural still trips it (e.g. "the Rats", "dragons"). Compiled once
# at module import rather than once per term per call, since the guard runs
# on every request. Case-insensitive: the plain block's casing is not a
# defense.
#
# `\b` treats hyphens, punctuation and string boundaries as word breaks, so
# "dragon-like" and "Year of the Rat" both trip on the bare term while
# "deliberation" and "generator" -- which merely *contain* "rat" as
# characters, not as a word -- do not (that collision, under naive substring
# containment, is exactly what caused the five terms above to be deleted;
# see the Chinese zodiac comment).
#
# Known gap, accepted: irregular plurals ("oxen") are not covered by the
# trailing `s?`. Not fixed here because the failure mode is asymmetric --
# leaked chart jargon in the singular or regularly-plural form still reads
# as a proper noun/term of art to a plain-vocabulary reader and gets caught;
# "oxen" specifically slipping through reads as an ordinary plural noun, not
# as chart jargon, which is a much smaller leak than what the guard exists
# to catch.
ESOTERIC_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in sorted(ESOTERIC_TERMS)) + r")s?\b",
    re.IGNORECASE,
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
# agreement" intuition) is what keeps the hedge honest. Three bands
# (ruling R58 -- the original two-band version overclaimed "consistently
# indicated" at a bare 3-of-6 tie):
#   - >= 0.6667: at least 4 of 6 applicable systems agree -- a genuine
#     majority, not a tie. Reachable: the observed maximum across the
#     fixture suite is 0.833 (5/6); nothing in the suite reaches 6/6.
#   - >= 0.5 and < 0.6667: at least half agree but not more -- e.g. exactly
#     3 of 6, a tie. "(repeatedly indicated)" claims only that more than one
#     system pointed there, which is exactly what is true at a tie; it does
#     not claim consensus.
#   - <  0.25: one applicable system (or two, out of five-plus) -- flagged as
#     a single indicator, so the assistant does not over-index on it.
#   - in between: the common case, left unmarked.
CONVERGENCE_CONSISTENT = 0.6667
CONVERGENCE_CORROBORATED = 0.5
CONVERGENCE_SINGLE_SOURCE = 0.25


def estimate_tokens(text: str) -> int:
    """Four characters per token -- documented, deliberate, and errs high for
    English prose (spec §5.2's "~350 tokens" is a budget, not a tokenizer
    contract)."""
    return math.ceil(len(text) / 4)


def _confidence_note(convergence: float) -> str:
    if convergence >= CONVERGENCE_CONSISTENT:
        return " (consistently indicated)"
    if convergence >= CONVERGENCE_CORROBORATED:
        return " (repeatedly indicated)"
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


def build_context(
    profile: dict, vocabulary: str = "plain", *, person_id: str | None = None
) -> dict:
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
    #
    # Floored at one section carrying one facet (ruling R57): trimming below
    # that point is what used to fall through to `sections.pop()` until
    # `sections == []`, returning `{"text": "", "json": {}, "tokens": 0}`.
    # The token budget is a promise about size; "never truncate
    # mid-sentence" is a promise about usability. An empty string keeps the
    # first promise by breaking the second completely -- a caller can detect
    # and handle a marginally oversized bundle, but it cannot do anything
    # with an empty one. So if the floor block still exceeds the budget, we
    # return it anyway and log a warning instead of erasing it.
    text = render(sections)
    while estimate_tokens(text) > TOKEN_BUDGET and sections:
        if len(sections) == 1 and len(sections[0][2]) == 1:
            break
        for index in range(len(sections) - 1, -1, -1):
            heading, key, lines = sections[index]
            if len(lines) > 1:
                sections[index] = (heading, key, lines[:-1])
                break
        else:
            sections.pop()
        text = render(sections)

    tokens = estimate_tokens(text)
    if sections and tokens > TOKEN_BUDGET:
        logger.warning(
            "context bundle for %s exceeds token budget even at the minimum "
            "size of one section with one facet: %d tokens > %d budget",
            person_id if person_id is not None else "<unknown>",
            tokens,
            TOKEN_BUDGET,
        )

    return {
        "text": text,
        "json": {key: lines for _heading, key, lines in sections},
        "tokens": tokens,
    }
