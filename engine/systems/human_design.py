"""Human Design bodygraph (spec §3.2).

Requires a birth time. Without one the module returns confidence 0.0 and is
excluded from synthesis rather than guessing -- an HD chart computed for noon
is wrong often enough to be worse than absent.

An *uncertain* birth time is a different case and is handled differently. A
reading that is ambiguous (the clock read it twice when DST ended) or
nonexistent (the clock skipped it when DST began) still pins the chart to
within one hour, which is reduced precision rather than absent data: the
bodygraph is computed as normal from `BirthInput.utc_datetime`'s declared
`fold=0` resolution, and the degradation is an explicit note plus a reduced
confidence. See `CONFIDENCE_UNCERTAIN_TIME`.

This module builds on `engine.systems.hd_wheel` (gate/line resolution and the
design-moment solve) without either module knowing about the other's layer:
hd_wheel has no notion of centers, channels, type, or authority, and this
module has no opinion on how a longitude becomes a gate. That separation
(spec correction 5c, see hd_wheel.py) is what lets a later Gene Keys
calculator reuse hd_wheel directly, sharing the design-moment solve, without
depending on anything bodygraph-specific here.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

from engine.ephemeris import get_ephemeris
from engine.kb.loader import load_kb
from engine.systems.hd_wheel import Activation, activations, cached_design_julian_day
from engine.types import BirthInput, InputField, SystemOutput, TraitTag

DATA_DIR = Path(__file__).parent / "data"

CENTERS = (
    "head",
    "ajna",
    "throat",
    "g",
    "heart",
    "sacral",
    "solar_plexus",
    "spleen",
    "root",
)
MOTORS = frozenset({"sacral", "heart", "solar_plexus", "root"})

STRATEGY = {
    "Generator": "Wait to respond",
    "Manifesting Generator": "Wait to respond, then inform",
    "Projector": "Wait for the invitation",
    "Manifestor": "Inform before acting",
    "Reflector": "Wait a lunar cycle",
}

#: An ambiguous or nonexistent birth time: a one-hour window, not the
#: twenty-four hours of a missing time, so this system degrades instead of
#: being excluded. Derived from what one hour actually risks on the wheel,
#: whose gates are 5.625 deg wide and whose lines are 0.9375 deg wide:
#:
#:   * Sun/Earth points move ~0.04 deg/hour -> ~0.7% chance of a gate change,
#:     ~4.4% chance of a line change. The 1/2 profile digits come from the
#:     personality and design Sun lines, so the profile is ~91% safe.
#:   * The Moon moves ~0.55 deg/hour -> ~10% chance of a gate change and a
#:     coin-flip on the line. Mercury and Venus sit between the two.
#:   * Type, authority, definition and defined centers depend on the whole
#:     26-activation gate set, so any single gate flip can (but usually does
#:     not) cross a channel boundary and change them.
#:
#: 0.85 prices "one of the tagged elements is likely off" without pretending
#: the bodygraph as a whole is unreliable. It sits above astrology's 0.8
#: because no HD element is anywhere near as exposed as the Ascendant, whose
#: sign changes about half the time over the same hour; and below Gene Keys'
#: 0.9 because HD reads fast-moving points that Gene Keys does not.
#: tests/test_birth_time_quality.py pins the measured case: over the
#: 1990-10-28 Europe/London ambiguity the personality Moon moves 13/5 -> 13/6
#: while the Sun's gate does not move at all.
CONFIDENCE_UNCERTAIN_TIME = 0.85

DEFINITION_NAMES = {
    0: "none",
    1: "single",
    2: "split",
    3: "triple split",
    4: "quadruple split",
}


@functools.lru_cache(maxsize=1)
def load_gate_centers() -> dict[int, str]:
    """Gate -> center, loaded from hd_gates.yaml. See that file's header for
    the two independent sources this mapping was verified against."""
    doc = yaml.safe_load((DATA_DIR / "hd_gates.yaml").read_text(encoding="utf-8"))
    return {gate: center for center, gates in doc["centers"].items() for gate in gates}


@functools.lru_cache(maxsize=1)
def load_channels() -> tuple[tuple[int, int], ...]:
    """The 36 channels as sorted (low, high) gate-number pairs."""
    doc = yaml.safe_load((DATA_DIR / "hd_channels.yaml").read_text(encoding="utf-8"))
    return tuple(tuple(sorted(pair)) for pair in doc["channels"])  # type: ignore[misc]


def gate_center(gate: int) -> str:
    return load_gate_centers()[gate]


def defined_channels(gates: set[int]) -> list[str]:
    """Channel keys like "10-20" for every channel whose both gates are in
    `gates`, sorted numerically (low gate first, then by high gate)."""
    return sorted(
        (f"{a}-{b}" for a, b in load_channels() if a in gates and b in gates),
        key=lambda key: tuple(int(x) for x in key.split("-")),
    )


def _channel_center_pairs(channels: list[str]) -> list[tuple[str, str]]:
    """Each defined channel as the pair of centers its two gates belong to."""
    pairs = []
    for key in channels:
        a, b = (gate_center(int(g)) for g in key.split("-"))
        pairs.append((a, b))
    return pairs


def _adjacency(defined: set[str], channels: list[str]) -> dict[str, set[str]]:
    """Center adjacency graph restricted to defined centers, edges being
    defined channels between them."""
    graph: dict[str, set[str]] = {c: set() for c in defined}
    for a, b in _channel_center_pairs(channels):
        graph[a].add(b)
        graph[b].add(a)
    return graph


def _reachable(graph: dict[str, set[str]], start: str) -> set[str]:
    seen, stack = {start}, [start]
    while stack:
        node = stack.pop()
        for neighbour in sorted(graph.get(node, ())):
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return seen


def _connected(defined: set[str], channels: list[str], a: str, b: str) -> bool:
    """Whether `a` and `b` are both defined and joined by a path of defined
    channels through other defined centers -- a graph reachability question,
    not "are both of them merely defined"."""
    if a not in defined or b not in defined:
        return False
    return b in _reachable(_adjacency(defined, channels), a)


def _motor_reaches_throat(defined: set[str], channels: list[str]) -> bool:
    """True when any motor center is connected to the throat through defined
    channels (a graph traversal, not "throat and a motor are both defined")."""
    if "throat" not in defined:
        return False
    reachable = _reachable(_adjacency(defined, channels), "throat")
    return bool(reachable & MOTORS)


def _components(defined: set[str], channels: list[str]) -> int:
    """Count connected components among defined centers linked by defined
    channels, via union-find over the center adjacency graph."""
    parent = {c: c for c in defined}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in _channel_center_pairs(channels):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    return len({find(c) for c in defined})


def _determine_type(defined: set[str], channels: list[str]) -> str:
    if not defined:
        return "Reflector"
    motor_to_throat = _motor_reaches_throat(defined, channels)
    if "sacral" in defined:
        return "Manifesting Generator" if motor_to_throat else "Generator"
    return "Manifestor" if motor_to_throat else "Projector"


def _determine_authority(defined: set[str], channels: list[str], hd_type: str) -> str:
    if "solar_plexus" in defined:
        return "Emotional"
    if "sacral" in defined:
        return "Sacral"
    if "spleen" in defined:
        return "Splenic"
    if "heart" in defined:
        return (
            "Ego Manifested"
            if _connected(defined, channels, "heart", "throat")
            else "Ego Projected"
        )
    if "g" in defined and _connected(defined, channels, "g", "throat"):
        return "Self-Projected"
    if hd_type == "Reflector":
        return "Lunar"
    return "Mental Projected"


def _side(acts: dict[str, Activation]) -> dict[str, dict]:
    return {name: {"gate": a.gate, "line": a.line} for name, a in sorted(acts.items())}


class HumanDesignCalculator:
    key = "human_design"
    required_inputs = {InputField.BIRTH_DATE, InputField.BIRTH_TIME, InputField.BIRTH_PLACE}

    def compute(self, inp: BirthInput) -> SystemOutput:
        if inp.birth_time is None:
            return SystemOutput(
                raw={"available": False},
                tags=[],
                confidence=0.0,
                notes=[
                    "birth time missing: Human Design requires an exact birth time "
                    "and is excluded from synthesis"
                ],
            )

        notes: list[str] = []
        confidence = 1.0
        if inp.birth_time_is_uncertain:
            confidence = CONFIDENCE_UNCERTAIN_TIME
            notes.append(
                f"{inp.birth_time_note} Gate and line assignments taken from the "
                "faster-moving points -- the Moon above all, which covers about "
                "0.55 degrees an hour against a 0.9375-degree line -- may differ "
                "for the alternative reading, and a single gate flip can cross a "
                "channel boundary and change type, authority or definition. The "
                "Sun-derived profile lines are far more stable"
            )

        eph = get_ephemeris()
        natal_jd = eph.julian_day(inp.utc_datetime)
        design_jd = cached_design_julian_day(eph, natal_jd)

        personality = activations(eph, natal_jd)
        design = activations(eph, design_jd)

        gates = {a.gate for a in personality.values()} | {a.gate for a in design.values()}
        channels = defined_channels(gates)

        defined: set[str] = set()
        for key in channels:
            for gate in key.split("-"):
                defined.add(gate_center(int(gate)))

        hd_type = _determine_type(defined, channels)
        authority = _determine_authority(defined, channels, hd_type)
        profile = f"{personality['sun'].line}/{design['sun'].line}"

        raw = {
            "type": hd_type,
            "strategy": STRATEGY[hd_type],
            "authority": authority,
            "profile": profile,
            "definition": DEFINITION_NAMES[_components(defined, channels)],
            "defined_centers": sorted(defined),
            "open_centers": sorted(set(CENTERS) - defined),
            "channels": channels,
            "gates": sorted(gates),
            "personality": _side(personality),
            "design": _side(design),
            "available": True,
        }

        kb = load_kb()
        tags: list[TraitTag] = [
            *kb.tags_for(self.key, "types", hd_type.lower().replace(" ", "_")),
            *kb.tags_for(self.key, "authorities", authority.lower().replace(" ", "_")),
            *kb.tags_for(self.key, "profiles", profile.replace("/", "_")),
        ]
        for center in sorted(defined):
            tags.extend(kb.tags_for(self.key, "centers", f"{center}_defined"))

        return SystemOutput(raw=raw, tags=tags, confidence=confidence, notes=notes)
