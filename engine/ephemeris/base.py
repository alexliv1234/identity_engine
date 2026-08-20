"""Ephemeris-agnostic types and angle helpers.

Nothing here knows about Skyfield. The adapter that satisfies `Ephemeris` is a
swappable implementation detail (design spec §9): swapping libraries means
writing a second module that satisfies this Protocol and changing one line in
`__init__.py`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Body(StrEnum):
    SUN = "sun"
    MOON = "moon"
    MERCURY = "mercury"
    VENUS = "venus"
    MARS = "mars"
    JUPITER = "jupiter"
    SATURN = "saturn"
    URANUS = "uranus"
    NEPTUNE = "neptune"
    PLUTO = "pluto"
    NORTH_NODE = "north_node"

    # Chiron is deliberately absent from v1: de406.bsp (the vendored JPL
    # kernel) carries only the Sun, Moon, and the eight planet barycenters.
    # Chiron is a minor body that needs a separate SPK from JPL Horizons — a
    # second data dependency and a second failure mode. Deferred by ruling
    # until a later task actually needs it.


def norm360(deg: float) -> float:
    """Normalize to [0, 360)."""
    return deg % 360.0


def arc_between(a: float, b: float) -> float:
    """Shortest angular separation in [0, 180]. Never subtract angles directly."""
    diff = abs(norm360(a) - norm360(b)) % 360.0
    return 360.0 - diff if diff > 180.0 else diff


@dataclass(frozen=True)
class Position:
    body: Body
    longitude: float
    latitude: float
    speed: float

    @property
    def retrograde(self) -> bool:
        return self.speed < 0.0


@dataclass(frozen=True)
class Houses:
    cusps: tuple[float, ...]
    ascendant: float
    midheaven: float


class HousesUnavailable(Exception):
    """Raised by `Ephemeris.houses` when Placidus cusps do not exist.

    Placidus is undefined above the polar circle: the iteration divides a
    point's semi-diurnal arc, but circumpolar ecliptic degrees never rise or
    set, so there is no arc to divide. Rather than fake a result, the engine
    raises this so a caller can degrade explicitly (no houses, an honest
    note) instead of silently reporting numbers that do not mean anything —
    consistent with the project's rule that the engine never fakes precision.
    """


@runtime_checkable
class Ephemeris(Protocol):
    def julian_day(self, moment: dt.datetime) -> float: ...
    def position(self, jd: float, body: Body) -> Position: ...
    def positions(self, jd: float, bodies: Iterable[Body]) -> dict[Body, Position]: ...
    def houses(self, jd: float, lat: float, lon: float) -> Houses: ...
