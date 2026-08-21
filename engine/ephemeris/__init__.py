"""Ephemeris entry point. Swapping implementations is a one-line change here."""

from __future__ import annotations

import functools

from engine.ephemeris.base import (
    Body,
    Ephemeris,
    EphemerisDataMissing,
    Houses,
    HousesUnavailable,
    Position,
    arc_between,
    norm360,
)

__all__ = [
    "Body",
    "Ephemeris",
    "EphemerisDataMissing",
    "Houses",
    "HousesUnavailable",
    "Position",
    "arc_between",
    "norm360",
    "get_ephemeris",
]


@functools.lru_cache(maxsize=1)
def get_ephemeris() -> Ephemeris:
    from engine.ephemeris.skyfield_adapter import SkyfieldEphemeris  # noqa: PLC0415

    return SkyfieldEphemeris()
