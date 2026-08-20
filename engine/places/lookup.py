"""Offline city lookup. No network calls, ever (spec §2)."""

from __future__ import annotations

import csv
import functools
from dataclasses import dataclass
from pathlib import Path

from unidecode import unidecode

from engine.errors import EngineError, ErrorCode

DATA_FILE = Path(__file__).parent / "data" / "cities.csv"


@dataclass(frozen=True)
class Place:
    name: str
    country: str
    admin1: str
    lat: float
    lon: float
    tz: str
    population: int


@dataclass(frozen=True)
class _Row:
    place: Place
    key_name: str
    key_country_code: str
    key_country_name: str


def _fold(text: str) -> str:
    return unidecode(text).casefold().strip()


@functools.lru_cache(maxsize=1)
def _rows() -> tuple[_Row, ...]:
    out: list[_Row] = []
    with DATA_FILE.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            place = Place(
                name=r["name"],
                country=r["country_code"],
                admin1=r["admin1"],
                lat=float(r["lat"]),
                lon=float(r["lon"]),
                tz=r["tz"],
                population=int(r["population"] or 0),
            )
            out.append(
                _Row(
                    place=place,
                    key_name=_fold(r["ascii"]),
                    key_country_code=r["country_code"].casefold(),
                    key_country_name=_fold(r["country_name"]),
                )
            )
    # The CSV is already population-desc sorted; keep that order as the ranking.
    return tuple(out)


def _split_query(query: str) -> tuple[str, str | None]:
    parts = [p.strip() for p in query.split(",")]
    if len(parts) == 1:
        return _fold(parts[0]), None
    return _fold(parts[0]), _fold(parts[-1])


def search(query: str, limit: int = 5) -> list[Place]:
    city, country = _split_query(query)
    hits = [
        row.place
        for row in _rows()
        if row.key_name == city
        and (country is None or country in (row.key_country_code, row.key_country_name))
    ]
    return hits[:limit]


def resolve(query: str) -> Place:
    hits = search(query, limit=1)
    if not hits:
        raise EngineError(
            ErrorCode.UNKNOWN_PLACE,
            f"no city matched {query!r}; try 'City, CountryCode'",
            field="birth_place",
        )
    return hits[0]
