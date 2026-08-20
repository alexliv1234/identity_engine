# Identity Engine — Plan 2: Chart Systems Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the four remaining v1 systems — Western astrology, Human Design,
Gene Keys, and Jewish numerology/Kabbalah — behind the `SystemCalculator` protocol
Plan 1 established, so a profile covers all six systems from spec §3.

**Architecture:** One swappable ephemeris adapter (`engine/ephemeris/`) serves
astrology, Human Design and Gene Keys, which all need planetary longitudes. That
adapter is the *only* place `pyswisseph` is imported, because the AGPL licensing
question in spec §9 is resolved by swapping the implementation, not by editing
four calculators. Human Design's I-Ching gate wheel is its own module so Gene Keys
can reuse it without depending on the Human Design calculator. Kabbalah needs no
ephemeris — it is gematria plus a Jewish-calendar conversion.

**Tech Stack:** `pyswisseph` (AGPL — see Global Constraints), `pyluach`, plus
everything from Plan 1.

**Spec:** `docs/superpowers/specs/2026-08-19-identity-engine-design.md`

**Prerequisite:** Plan 1 (`2026-08-20-identity-engine-01-core-engine.md`) complete
— `SystemCalculator`, `BirthInput`, the KB loader, `synthesize()`, and
`build_profile()` all exist and are tested.

## Global Constraints

Every task's requirements implicitly include this section, **plus** all of Plan 1's
Global Constraints (they still hold — determinism, no network in the request path,
`reviewed: true`, master numbers, the exact disclaimer string, the stable error
codes, the 1800-01-01 date floor).

- **`pyswisseph` is AGPL.** It is imported in **exactly one file**,
  `engine/ephemeris/swisseph_adapter.py`. Any other module importing it is a bug.
  `README.md` must state the licensing position from spec §9 verbatim: fine for
  development and the demo; before a commercial closed-source launch, either buy
  the Swiss Ephemeris professional license or swap the adapter to MIT-licensed
  Skyfield + JPL files.
- **The engine never fakes precision** (spec §8). Missing birth time means:
  astrology omits houses and angles and reports the Moon as a sign *range* if it
  changes sign that day; Human Design and Gene Keys return `confidence = 0.0` and
  are excluded from synthesis with an explicit note.
- **Ephemeris files are bundled**, not downloaded at runtime. `swe.set_ephe_path()`
  points at a vendored directory.
- **Angles are always normalized to `[0, 360)`** before use, and compared with a
  helper — never with raw subtraction, which breaks across the 0°/360° seam.
- **Human Design gate/line math is pure arithmetic over a fixed wheel constant.**
  The wheel starts at **Gate 41 at 302.0° (2° Aquarius)**; each gate spans
  **5.625°**, each line **0.9375°**.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/ephemeris/base.py` | `Body` enum, `Position`, `Houses`, `Ephemeris` protocol, angle helpers |
| `engine/ephemeris/swisseph_adapter.py` | The **only** `pyswisseph` import |
| `engine/ephemeris/__init__.py` | `get_ephemeris()` — the single swap point |
| `engine/ephemeris/data/` | Vendored Swiss Ephemeris files |
| `engine/systems/astrology.py` | Placements, houses, aspects, tag emission |
| `engine/systems/hd_wheel.py` | I-Ching gate wheel + design-time solver (shared) |
| `engine/systems/data/hd_gates.yaml` | Gate → center map (64 entries) |
| `engine/systems/data/hd_channels.yaml` | The 36 channels |
| `engine/systems/human_design.py` | Bodygraph, type, authority, profile, definition |
| `engine/systems/gene_keys.py` | Activation sequence over the shared wheel |
| `engine/systems/kabbalah.py` | Gematria, Hebrew date, sefirot |
| `kb/astrology/*.yaml`, `kb/human_design/*.yaml`, `kb/gene_keys/*.yaml`, `kb/kabbalah/*.yaml` | Trait mappings |

---

### Task 1: Ephemeris adapter

**Files:**
- Create: `engine/ephemeris/base.py`, `engine/ephemeris/swisseph_adapter.py`,
  `engine/ephemeris/__init__.py`
- Create (vendored): `engine/ephemeris/data/` (Swiss Ephemeris `.se1` files)
- Modify: `pyproject.toml` (add `pyswisseph>=2.10`, `pyluach>=2.2`)
- Modify: `README.md` (licensing note)
- Test: `tests/test_ephemeris.py`

**Interfaces:**
- Consumes: nothing from Plan 1 except `engine.errors`.
- Produces:
  - `engine.ephemeris.base.Body` — `StrEnum`: `SUN MOON MERCURY VENUS MARS JUPITER
    SATURN URANUS NEPTUNE PLUTO CHIRON NORTH_NODE`.
  - `engine.ephemeris.base.Position` — frozen dataclass:
    `body: Body, longitude: float, latitude: float, speed: float`;
    property `retrograde: bool` (`speed < 0`).
  - `engine.ephemeris.base.Houses` — frozen dataclass:
    `cusps: tuple[float, ...]` (12 entries, cusp 1 first), `ascendant: float`,
    `midheaven: float`.
  - `engine.ephemeris.base.norm360(deg: float) -> float`
  - `engine.ephemeris.base.arc_between(a: float, b: float) -> float` — shortest
    separation in `[0, 180]`.
  - `engine.ephemeris.base.Ephemeris` — Protocol:
    `julian_day(moment: datetime) -> float`,
    `position(jd: float, body: Body) -> Position`,
    `positions(jd: float, bodies: Iterable[Body]) -> dict[Body, Position]`,
    `houses(jd: float, lat: float, lon: float) -> Houses`.
  - `engine.ephemeris.get_ephemeris() -> Ephemeris` — cached singleton. **The one
    line to change when swapping to Skyfield.**

- [ ] **Step 1: Add dependencies and vendor the ephemeris files**

In `pyproject.toml`, extend `dependencies`:

```toml
dependencies = [
    "pydantic>=2.7",
    "PyYAML>=6.0",
    "Unidecode>=1.3",
    "convertdate>=2.4",
    "pyswisseph>=2.10",
    "pyluach>=2.2",
]
```

Then `.venv/bin/pip install -e ".[dev]"`.

`pyswisseph` ships the Moshier analytic fallback, which needs no data files and is
accurate to a few arcseconds — good enough for signs, gates and houses. Vendor the
`.se1` files only if you want full Swiss precision; the adapter below falls back to
Moshier automatically when `data/` is empty, so this step is optional for v1.

Add to `README.md`:

```markdown
## Ephemeris licensing

`pyswisseph` (Swiss Ephemeris) is **AGPL**. That is fine for development and the
demo playground. Before any commercial closed-source launch, either purchase the
Swiss Ephemeris professional license or swap `engine/ephemeris/` to MIT-licensed
Skyfield + JPL ephemeris files. The ephemeris sits behind an adapter interface
precisely so this is a swappable implementation detail; `swisseph` is imported in
exactly one file and `tests/test_ephemeris.py` enforces that.
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_ephemeris.py
import datetime as dt
import re
from pathlib import Path

import pytest

from engine.ephemeris import get_ephemeris
from engine.ephemeris.base import Body, arc_between, norm360


@pytest.fixture(scope="module")
def eph():
    return get_ephemeris()


def test_norm360_wraps_both_directions():
    assert norm360(370.0) == 10.0
    assert norm360(-10.0) == 350.0
    assert norm360(360.0) == 0.0


def test_arc_between_takes_the_short_way_round():
    assert arc_between(10.0, 350.0) == 20.0
    assert arc_between(350.0, 10.0) == 20.0
    assert arc_between(0.0, 180.0) == 180.0
    assert arc_between(5.0, 5.0) == 0.0


def test_sun_longitude_at_a_known_equinox(eph):
    """2000-03-20 07:35 UTC was the March equinox: Sun at 0 deg Aries."""
    jd = eph.julian_day(dt.datetime(2000, 3, 20, 7, 35, tzinfo=dt.UTC))
    lon = eph.position(jd, Body.SUN).longitude
    assert arc_between(lon, 0.0) < 0.05


def test_sun_advances_about_one_degree_per_day(eph):
    a = eph.julian_day(dt.datetime(2000, 6, 1, 12, 0, tzinfo=dt.UTC))
    b = eph.julian_day(dt.datetime(2000, 6, 2, 12, 0, tzinfo=dt.UTC))
    delta = arc_between(
        eph.position(a, Body.SUN).longitude, eph.position(b, Body.SUN).longitude
    )
    assert 0.9 < delta < 1.1


def test_positions_returns_every_requested_body(eph):
    jd = eph.julian_day(dt.datetime(2000, 1, 1, 12, 0, tzinfo=dt.UTC))
    bodies = [Body.SUN, Body.MOON, Body.PLUTO, Body.CHIRON, Body.NORTH_NODE]
    got = eph.positions(jd, bodies)
    assert set(got) == set(bodies)
    assert all(0.0 <= p.longitude < 360.0 for p in got.values())


def test_north_node_is_always_retrograde(eph):
    """The mean lunar node moves backwards; a positive speed means wrong body."""
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    assert eph.position(jd, Body.NORTH_NODE).retrograde


def test_houses_are_twelve_cusps_with_asc_and_mc(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    houses = eph.houses(jd, lat=40.7128, lon=-74.0060)
    assert len(houses.cusps) == 12
    assert all(0.0 <= c < 360.0 for c in houses.cusps)
    assert 0.0 <= houses.ascendant < 360.0
    assert 0.0 <= houses.midheaven < 360.0
    assert arc_between(houses.cusps[0], houses.ascendant) < 0.001


def test_julian_day_requires_an_aware_datetime(eph):
    with pytest.raises(ValueError):
        eph.julian_day(dt.datetime(2000, 1, 1, 12, 0))  # naive


def test_positions_are_deterministic(eph):
    jd = eph.julian_day(dt.datetime(1815, 12, 10, 13, 0, tzinfo=dt.UTC))
    assert eph.position(jd, Body.SUN) == eph.position(jd, Body.SUN)


def test_swisseph_is_imported_in_exactly_one_module():
    """Spec §9: the AGPL dependency stays swappable, so confine the import."""
    pattern = re.compile(r"^\s*(import|from)\s+swisseph\b", re.M)
    offenders = sorted(
        p.name
        for p in Path("engine").rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    )
    assert offenders == ["swisseph_adapter.py"], offenders
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_ephemeris.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.ephemeris'`

- [ ] **Step 4: Implement `engine/ephemeris/base.py`**

```python
"""Ephemeris-agnostic types and angle helpers.

Nothing here knows about Swiss Ephemeris. Swapping to Skyfield means writing a
second module that satisfies `Ephemeris` and changing one line in __init__.py.
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
    CHIRON = "chiron"
    NORTH_NODE = "north_node"


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


@runtime_checkable
class Ephemeris(Protocol):
    def julian_day(self, moment: dt.datetime) -> float: ...
    def position(self, jd: float, body: Body) -> Position: ...
    def positions(self, jd: float, bodies: Iterable[Body]) -> dict[Body, Position]: ...
    def houses(self, jd: float, lat: float, lon: float) -> Houses: ...
```

- [ ] **Step 5: Implement `engine/ephemeris/swisseph_adapter.py`**

```python
"""Swiss Ephemeris adapter — the ONLY module that imports swisseph.

`pyswisseph` is AGPL (spec §9). Keeping the import confined here is what makes
the licensing decision a one-file swap rather than a rewrite.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from pathlib import Path

import swisseph as swe

from engine.ephemeris.base import Body, Ephemeris, Houses, Position, norm360

DATA_DIR = Path(__file__).parent / "data"

_SWE_BODY: dict[Body, int] = {
    Body.SUN: swe.SUN,
    Body.MOON: swe.MOON,
    Body.MERCURY: swe.MERCURY,
    Body.VENUS: swe.VENUS,
    Body.MARS: swe.MARS,
    Body.JUPITER: swe.JUPITER,
    Body.SATURN: swe.SATURN,
    Body.URANUS: swe.URANUS,
    Body.NEPTUNE: swe.NEPTUNE,
    Body.PLUTO: swe.PLUTO,
    Body.CHIRON: swe.CHIRON,
    Body.NORTH_NODE: swe.MEAN_NODE,
}

PLACIDUS = b"P"


class SwissEphemeris(Ephemeris):
    def __init__(self) -> None:
        # Use bundled .se1 files when present; otherwise fall back to the built-in
        # Moshier model, which needs no data files and is accurate to arcseconds.
        if DATA_DIR.exists() and any(DATA_DIR.glob("*.se1")):
            swe.set_ephe_path(str(DATA_DIR))
            self._flags = swe.FLG_SWIEPH | swe.FLG_SPEED
        else:
            self._flags = swe.FLG_MOSEPH | swe.FLG_SPEED

    def julian_day(self, moment: dt.datetime) -> float:
        if moment.tzinfo is None:
            raise ValueError("julian_day requires a timezone-aware datetime")
        utc = moment.astimezone(dt.UTC)
        hour = utc.hour + utc.minute / 60.0 + utc.second / 3600.0
        return swe.julday(utc.year, utc.month, utc.day, hour, swe.GREG_CAL)

    def position(self, jd: float, body: Body) -> Position:
        values, _ = swe.calc_ut(jd, _SWE_BODY[body], self._flags)
        return Position(
            body=body,
            longitude=norm360(values[0]),
            latitude=values[1],
            speed=values[3],
        )

    def positions(self, jd: float, bodies: Iterable[Body]) -> dict[Body, Position]:
        return {body: self.position(jd, body) for body in bodies}

    def houses(self, jd: float, lat: float, lon: float) -> Houses:
        cusps, ascmc = swe.houses(jd, lat, lon, PLACIDUS)
        return Houses(
            cusps=tuple(norm360(c) for c in cusps[:12]),
            ascendant=norm360(ascmc[0]),
            midheaven=norm360(ascmc[1]),
        )
```

```python
# engine/ephemeris/__init__.py
"""Ephemeris entry point. Swapping implementations is a one-line change here."""

from __future__ import annotations

import functools

from engine.ephemeris.base import Body, Ephemeris, Houses, Position, arc_between, norm360

__all__ = ["Body", "Ephemeris", "Houses", "Position", "arc_between", "norm360",
           "get_ephemeris"]


@functools.lru_cache(maxsize=1)
def get_ephemeris() -> Ephemeris:
    from engine.ephemeris.swisseph_adapter import SwissEphemeris  # noqa: PLC0415

    return SwissEphemeris()
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_ephemeris.py -v`
Expected: PASS, 10 tests

- [ ] **Step 7: Commit**

```bash
git add engine/ephemeris/ tests/test_ephemeris.py pyproject.toml README.md
git commit -m "feat: swappable ephemeris adapter over pyswisseph"
```

---

### Task 2: Western astrology calculator

**Files:**
- Create: `engine/systems/astrology.py`
- Create: `kb/astrology/sun_signs.yaml`, `kb/astrology/moon_signs.yaml`,
  `kb/astrology/ascendants.yaml`
- Test: `tests/test_astrology.py`

**Interfaces:**
- Consumes: `engine.ephemeris.*`, `engine.types.*`, `engine.kb.loader.load_kb`.
- Produces:
  - `engine.systems.astrology.SIGNS: tuple[str, ...]` — 12 names from Aries.
  - `engine.systems.astrology.sign_of(longitude: float) -> tuple[str, float]` —
    `(sign_name, degree_within_sign)`.
  - `engine.systems.astrology.ASPECTS: dict[str, tuple[float, float]]` —
    `name -> (exact_angle, default_orb)`.
  - `engine.systems.astrology.aspects_between(positions: dict[Body, Position])
    -> list[dict]` — sorted, deterministic.
  - `engine.systems.astrology.AstrologyCalculator` — `key = "astrology"`,
    `required_inputs = {InputField.BIRTH_DATE, InputField.BIRTH_PLACE}`
    (**not** birth time — astrology degrades rather than being excluded).
  - `raw` shape:

```jsonc
{
  "placements": [{"body": "sun", "sign": "Sagittarius", "degree": 17.42,
                  "house": 9, "retrograde": false}],
  "aspects": [{"a": "sun", "b": "moon", "aspect": "trine", "orb": 2.14, "exact": 120.0}],
  "angles": {"ascendant": {"sign": "Aries", "degree": 3.1},
             "midheaven": {"sign": "Capricorn", "degree": 12.7}},
  "houses_available": true,
  "moon_sign_range": null
}
```

**Degradation without a birth time (spec §8):** the chart is computed for **12:00
local noon**, `houses_available` is `false`, `angles` is `null`, no `house` key
appears on any placement, and if the Moon changes sign between 00:00 and 23:59
local that day, `moon_sign_range` is `["Cancer", "Leo"]` and the Moon emits **no**
tags. `confidence` drops to `0.6`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_astrology.py
import datetime as dt

import pytest

from engine.ephemeris import Body
from engine.systems.astrology import (
    ASPECTS,
    SIGNS,
    AstrologyCalculator,
    aspects_between,
    sign_of,
)
from engine.types import BirthInput, InputField


def make_input(**over):
    base = dict(full_name="Ada Lovelace", birth_date=dt.date(1815, 12, 10),
                birth_time=dt.time(13, 0), lat=51.5074, lon=-0.1278,
                tz="Europe/London", hebrew_name=None)
    base.update(over)
    return BirthInput(**base)


def placement(raw, body):
    return next(p for p in raw["placements"] if p["body"] == body)


def test_signs_start_at_aries_and_wrap():
    assert SIGNS[0] == "Aries"
    assert SIGNS[11] == "Pisces"
    assert sign_of(0.0) == ("Aries", 0.0)
    assert sign_of(359.5) == ("Pisces", 29.5)
    assert sign_of(45.0) == ("Taurus", 15.0)


def test_known_chart_has_expected_sun_sign():
    raw = AstrologyCalculator().compute(make_input()).raw
    assert placement(raw, "sun")["sign"] == "Sagittarius"


def test_all_twelve_bodies_are_placed():
    raw = AstrologyCalculator().compute(make_input()).raw
    bodies = {p["body"] for p in raw["placements"]}
    assert bodies == {str(b) for b in Body}


def test_houses_and_angles_present_when_birth_time_is_known():
    raw = AstrologyCalculator().compute(make_input()).raw
    assert raw["houses_available"] is True
    assert raw["angles"]["ascendant"]["sign"] in SIGNS
    assert all(1 <= p["house"] <= 12 for p in raw["placements"])


def test_missing_birth_time_drops_houses_and_angles():
    out = AstrologyCalculator().compute(make_input(birth_time=None))
    assert out.raw["houses_available"] is False
    assert out.raw["angles"] is None
    assert all("house" not in p for p in out.raw["placements"])
    assert out.confidence == 0.6
    assert any("birth time" in n.lower() for n in out.notes)


def test_missing_birth_time_reports_a_moon_sign_range_when_it_changes():
    # 1815-12-10: the Moon crosses a sign boundary during the day.
    out = AstrologyCalculator().compute(make_input(birth_time=None))
    rng = out.raw["moon_sign_range"]
    assert rng is None or (len(rng) == 2 and rng[0] != rng[1])


def test_moon_emits_no_tags_when_its_sign_is_ambiguous():
    out = AstrologyCalculator().compute(make_input(birth_time=None))
    if out.raw["moon_sign_range"] is not None:
        assert not any(t.element == "moon_signs" for t in out.tags)


def test_astrology_is_not_excluded_without_birth_time():
    assert AstrologyCalculator().required_inputs == {
        InputField.BIRTH_DATE, InputField.BIRTH_PLACE
    }


def test_aspect_table_matches_the_spec_five():
    assert set(ASPECTS) == {"conjunction", "opposition", "trine", "square", "sextile"}
    assert ASPECTS["trine"][0] == 120.0


def test_aspects_are_detected_within_orb():
    from engine.ephemeris.base import Position

    positions = {
        Body.SUN: Position(Body.SUN, 10.0, 0.0, 1.0),
        Body.MOON: Position(Body.MOON, 130.5, 0.0, 13.0),
        Body.MARS: Position(Body.MARS, 190.0, 0.0, 0.5),
    }
    found = aspects_between(positions)
    kinds = {(a["a"], a["b"], a["aspect"]) for a in found}
    assert ("moon", "sun", "trine") in kinds
    assert ("mars", "sun", "opposition") in kinds


def test_aspect_list_is_sorted_and_deduplicated():
    from engine.ephemeris.base import Position

    positions = {
        Body.SUN: Position(Body.SUN, 10.0, 0.0, 1.0),
        Body.MOON: Position(Body.MOON, 130.5, 0.0, 13.0),
    }
    found = aspects_between(positions)
    assert len(found) == 1  # one pair, not two orderings
    keys = [(a["a"], a["b"], a["aspect"]) for a in found]
    assert keys == sorted(keys)


def test_southern_hemisphere_chart_computes():
    raw = AstrologyCalculator().compute(
        make_input(lat=-33.8688, lon=151.2093, tz="Australia/Sydney",
                   birth_date=dt.date(1988, 7, 4), birth_time=dt.time(6, 45))
    ).raw
    assert raw["houses_available"] is True
    assert placement(raw, "sun")["sign"] == "Cancer"


def test_output_is_deterministic():
    a = AstrologyCalculator().compute(make_input())
    b = AstrologyCalculator().compute(make_input())
    assert a.raw == b.raw
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_astrology.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.systems.astrology'`

- [ ] **Step 3: Implement `engine/systems/astrology.py`**

```python
"""Western astrology (spec §3.1).

Degrades rather than fails when the birth time is unknown: no houses, no angles,
and the Moon is reported as a sign range if it crosses a boundary that day.
"""

from __future__ import annotations

import datetime as dt
from itertools import combinations
from zoneinfo import ZoneInfo

from engine.ephemeris import Body, get_ephemeris
from engine.ephemeris.base import Position, arc_between, norm360
from engine.kb.loader import load_kb
from engine.types import BirthInput, InputField, SystemOutput, TraitTag

SIGNS = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)

# name -> (exact angle, default orb)
ASPECTS: dict[str, tuple[float, float]] = {
    "conjunction": (0.0, 8.0),
    "opposition": (180.0, 8.0),
    "trine": (120.0, 7.0),
    "square": (90.0, 7.0),
    "sextile": (60.0, 5.0),
}

NOON = dt.time(12, 0)
CONFIDENCE_NO_TIME = 0.6


def sign_of(longitude: float) -> tuple[str, float]:
    lon = norm360(longitude)
    index = int(lon // 30.0)
    return SIGNS[index], lon - index * 30.0


def house_of(longitude: float, cusps: tuple[float, ...]) -> int:
    """Which house a longitude falls in, handling the 0/360 wrap."""
    lon = norm360(longitude)
    for i in range(12):
        start, end = cusps[i], cusps[(i + 1) % 12]
        span = norm360(end - start)
        if norm360(lon - start) < span:
            return i + 1
    return 12  # unreachable for well-formed cusps; keeps the return type total


def aspects_between(positions: dict[Body, Position]) -> list[dict]:
    found: list[dict] = []
    for a, b in combinations(sorted(positions, key=str), 2):
        separation = arc_between(positions[a].longitude, positions[b].longitude)
        for name, (exact, orb) in ASPECTS.items():
            delta = abs(separation - exact)
            if delta <= orb:
                first, second = sorted((str(a), str(b)))
                found.append(
                    {"a": first, "b": second, "aspect": name,
                     "orb": round(delta, 4), "exact": exact}
                )
                break  # aspect windows do not overlap; first match wins
    found.sort(key=lambda x: (x["a"], x["b"], x["aspect"]))
    return found


def _moon_sign_range(eph, inp: BirthInput) -> list[str] | None:
    """Signs the Moon occupies between local midnight and 23:59 on the birth date."""
    tz = ZoneInfo(inp.tz)
    edges = []
    for clock in (dt.time(0, 0), dt.time(23, 59)):
        moment = dt.datetime.combine(inp.birth_date, clock, tzinfo=tz).astimezone(dt.UTC)
        edges.append(sign_of(eph.position(eph.julian_day(moment), Body.MOON).longitude)[0])
    return None if edges[0] == edges[1] else edges


class AstrologyCalculator:
    key = "astrology"
    # Deliberately excludes BIRTH_TIME: this system degrades, it is not skipped.
    required_inputs = {InputField.BIRTH_DATE, InputField.BIRTH_PLACE}

    def compute(self, inp: BirthInput) -> SystemOutput:
        eph = get_ephemeris()
        notes: list[str] = []
        has_time = inp.birth_time is not None

        if has_time:
            moment = inp.utc_datetime
        else:
            moment = dt.datetime.combine(
                inp.birth_date, NOON, tzinfo=ZoneInfo(inp.tz)
            ).astimezone(dt.UTC)
            notes.append(
                "birth time missing: chart computed for local noon; no houses or "
                "angles are reported"
            )

        jd = eph.julian_day(moment)
        positions = eph.positions(jd, list(Body))

        houses = eph.houses(jd, inp.lat, inp.lon) if has_time else None
        moon_range = None if has_time else _moon_sign_range(eph, inp)
        if moon_range:
            notes.append(
                f"moon changed sign on the birth date ({moon_range[0]} to "
                f"{moon_range[1]}): moon contributes no traits"
            )

        placements: list[dict] = []
        for body in sorted(positions, key=str):
            pos = positions[body]
            sign, degree = sign_of(pos.longitude)
            entry = {
                "body": str(body),
                "sign": sign,
                "degree": round(degree, 4),
                "retrograde": pos.retrograde,
            }
            if houses is not None:
                entry["house"] = house_of(pos.longitude, houses.cusps)
            placements.append(entry)

        angles = None
        if houses is not None:
            asc_sign, asc_deg = sign_of(houses.ascendant)
            mc_sign, mc_deg = sign_of(houses.midheaven)
            angles = {
                "ascendant": {"sign": asc_sign, "degree": round(asc_deg, 4)},
                "midheaven": {"sign": mc_sign, "degree": round(mc_deg, 4)},
            }

        raw = {
            "placements": placements,
            "aspects": aspects_between(positions),
            "angles": angles,
            "houses_available": houses is not None,
            "moon_sign_range": moon_range,
        }

        kb = load_kb()
        tags: list[TraitTag] = []
        sun_sign = sign_of(positions[Body.SUN].longitude)[0]
        tags.extend(kb.tags_for(self.key, "sun_signs", sun_sign.lower()))
        if moon_range is None:
            moon_sign = sign_of(positions[Body.MOON].longitude)[0]
            tags.extend(kb.tags_for(self.key, "moon_signs", moon_sign.lower()))
        if angles is not None:
            tags.extend(kb.tags_for(self.key, "ascendants", angles["ascendant"]["sign"].lower()))

        return SystemOutput(
            raw=raw,
            tags=tags,
            confidence=1.0 if has_time else CONFIDENCE_NO_TIME,
            notes=notes,
        )
```

- [ ] **Step 4: Write the astrology KB files**

`kb/astrology/sun_signs.yaml` — twelve lowercase sign keys. Three shown; write all
twelve, then `moon_signs.yaml` and `ascendants.yaml` with the same keys, their own
`source` headers, and tags weighted toward the dimensions each angle governs
(Moon → `emotional.*`, Ascendant → `core_essence.visibility`, `communication.*`).

```yaml
schema: kb.mapping.v1
system: astrology
element: sun_signs
reviewed: true
source: >-
  Tropical zodiac, common contemporary synthesis of the twelve solar archetypes.
  Interpretive choice: the Sun is read as core drive and self-direction rather
  than as personality in total.
entries:
  aries:
    label: "Sun in Aries"
    text: "Direct, pioneering energy; initiates rather than waits."
    tags:
      - {facet: drive.initiative, weight: 0.9, direction: high}
      - {facet: communication.directness, weight: 0.7, direction: high}
      - {facet: decision_making.timing, weight: 0.7, direction: high}
      - {facet: work_energy.rhythm, weight: 0.6, direction: high}
  taurus:
    label: "Sun in Taurus"
    text: "Steady and sensory; builds slowly and does not like being hurried."
    tags:
      - {facet: work_energy.rhythm, weight: 0.8, direction: low}
      - {facet: decision_making.timing, weight: 0.7, direction: low}
      - {facet: relational.loyalty, weight: 0.7, direction: high}
      - {facet: life_themes.transformation, weight: 0.6, direction: low}
  gemini:
    label: "Sun in Gemini"
    text: "Quick and plural; thinks by talking and keeps several threads live at once."
    tags:
      - {facet: communication.pace, weight: 0.9, direction: high}
      - {facet: drive.novelty_seeking, weight: 0.8, direction: high}
      - {facet: work_energy.structure, weight: 0.6, direction: low}
```

Append to `kb/manifest.yaml` so completeness is enforced (Plan 1 Task 12):

```yaml
  astrology/sun_signs:
    keys: ["aries", "taurus", "gemini", "cancer", "leo", "virgo",
           "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]
  astrology/moon_signs:
    keys: ["aries", "taurus", "gemini", "cancer", "leo", "virgo",
           "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]
  astrology/ascendants:
    keys: ["aries", "taurus", "gemini", "cancer", "leo", "virgo",
           "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_astrology.py tests/test_kb_validation.py \
      tests/test_kb_completeness.py -v`
Expected: PASS (the completeness test names any sign you have not written yet)

- [ ] **Step 6: Register the calculator and refresh goldens**

In `engine/orchestrator.py`, add to `SYSTEM_REGISTRY`:

```python
from engine.systems.astrology import AstrologyCalculator

SYSTEM_REGISTRY: dict[str, SystemCalculator] = {
    calc.key: calc
    for calc in (
        AstrologyCalculator(),
        NumerologyCalculator(),
        ChineseZodiacCalculator(),
    )
}
```

Run: `.venv/bin/python kb_tools/regenerate_golden.py`
Then **read the diff** (`git diff tests/golden/`) and confirm the new `astrology`
slot looks right — Ada Lovelace Sagittarius Sun, the `no_birth_time` fixture with
`"houses_available": false`.

Run: `.venv/bin/pytest -v`
Expected: full suite PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/systems/astrology.py kb/astrology/ tests/test_astrology.py \
        engine/orchestrator.py tests/golden/
git commit -m "feat: western astrology with placements, houses, aspects and no-time degradation"
```

---

### Task 3: I-Ching gate wheel and design-time solver

**Files:**
- Create: `engine/systems/hd_wheel.py`
- Test: `tests/test_hd_wheel.py`

**Interfaces:**
- Consumes: `engine.ephemeris.*`.
- Produces:
  - `engine.systems.hd_wheel.WHEEL: tuple[int, ...]` — the 64 gates in zodiacal
    order starting at 302.0°.
  - `engine.systems.hd_wheel.GATE_ARC = 5.625`, `LINE_ARC = 0.9375`,
    `WHEEL_START = 302.0`.
  - `engine.systems.hd_wheel.Activation` — frozen dataclass:
    `body: Body, gate: int, line: int, longitude: float`.
  - `engine.systems.hd_wheel.gate_line(longitude: float) -> tuple[int, int]`.
  - `engine.systems.hd_wheel.design_julian_day(eph, natal_jd: float) -> float` —
    the moment the Sun was exactly 88° of arc before its natal longitude.
  - `engine.systems.hd_wheel.activations(eph, jd: float) -> dict[str, Activation]`
    — keyed by body name plus the two derived points `"earth"` and `"south_node"`.

**Why this module is separate from `human_design.py`:** Gene Keys needs gates and
the design moment but not the bodygraph. Sharing the wheel here keeps Gene Keys
from importing the Human Design calculator (spec §3.3).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hd_wheel.py
import datetime as dt

import pytest

from engine.ephemeris import Body, get_ephemeris
from engine.ephemeris.base import arc_between
from engine.systems.hd_wheel import (
    GATE_ARC,
    LINE_ARC,
    WHEEL,
    WHEEL_START,
    activations,
    design_julian_day,
    gate_line,
)


@pytest.fixture(scope="module")
def eph():
    return get_ephemeris()


def test_wheel_contains_all_64_gates_exactly_once():
    assert len(WHEEL) == 64
    assert sorted(WHEEL) == list(range(1, 65))


def test_wheel_starts_at_gate_41():
    assert WHEEL[0] == 41
    assert WHEEL_START == 302.0


def test_gate_arithmetic_is_consistent():
    assert GATE_ARC * 64 == 360.0
    assert LINE_ARC * 6 == GATE_ARC


def test_gate_41_line_1_begins_at_two_degrees_aquarius():
    assert gate_line(302.0) == (41, 1)
    assert gate_line(302.0 + LINE_ARC) == (41, 2)
    assert gate_line(302.0 + 5 * LINE_ARC) == (41, 6)


def test_aries_point_falls_in_gate_25():
    """A standard cross-check on the wheel: 0 deg Aries sits in Gate 25."""
    assert gate_line(0.0)[0] == 25


def test_gate_lookup_wraps_past_360():
    assert gate_line(361.0) == gate_line(1.0)
    assert gate_line(-1.0) == gate_line(359.0)


def test_every_longitude_maps_to_a_valid_gate_and_line():
    for step in range(0, 3600):
        gate, line = gate_line(step / 10.0)
        assert 1 <= gate <= 64
        assert 1 <= line <= 6


def test_design_moment_is_exactly_88_degrees_of_solar_arc_earlier(eph):
    natal = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    design = design_julian_day(eph, natal)
    natal_sun = eph.position(natal, Body.SUN).longitude
    design_sun = eph.position(design, Body.SUN).longitude
    assert arc_between((design_sun + 88.0) % 360.0, natal_sun) < 0.001


def test_design_moment_is_roughly_88_days_before_birth(eph):
    natal = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    days_before = natal - design_julian_day(eph, natal)
    assert 84.0 < days_before < 94.0


def test_design_solver_is_deterministic(eph):
    natal = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    assert design_julian_day(eph, natal) == design_julian_day(eph, natal)


def test_activations_include_the_derived_points(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    acts = activations(eph, jd)
    assert "earth" in acts and "south_node" in acts
    assert arc_between(acts["earth"].longitude, acts["sun"].longitude) == 180.0
    assert arc_between(acts["south_node"].longitude, acts["north_node"].longitude) == 180.0
    assert len(acts) == 14  # 12 bodies + earth + south node
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_hd_wheel.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.systems.hd_wheel'`

- [ ] **Step 3: Implement `engine/systems/hd_wheel.py`**

```python
"""The Human Design / Gene Keys I-Ching wheel (spec §3.2, §3.3).

The 64 hexagrams are laid over the ecliptic starting at Gate 41 at 2 deg Aquarius
(302.0 deg). Each gate spans 5.625 deg and each of its six lines 0.9375 deg. The
wheel order is a fixed constant, cross-checked in tests against two anchors: it
starts at Gate 41, and 0 deg Aries falls in Gate 25.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.ephemeris import Body
from engine.ephemeris.base import norm360

WHEEL_START = 302.0  # 2 degrees Aquarius
GATE_ARC = 360.0 / 64.0  # 5.625
LINE_ARC = GATE_ARC / 6.0  # 0.9375
SOLAR_ARC = 88.0  # degrees before the natal Sun for the design calculation

WHEEL: tuple[int, ...] = (
    41, 19, 13, 49, 30, 55, 37, 63,
    22, 36, 25, 17, 21, 51, 42, 3,
    27, 24, 2, 23, 8, 20, 16, 35,
    45, 12, 15, 52, 39, 53, 62, 56,
    31, 33, 7, 4, 29, 59, 40, 64,
    47, 6, 46, 18, 48, 57, 32, 50,
    28, 44, 1, 43, 14, 34, 9, 5,
    26, 11, 10, 58, 38, 54, 61, 60,
)


@dataclass(frozen=True)
class Activation:
    body: str
    gate: int
    line: int
    longitude: float


def gate_line(longitude: float) -> tuple[int, int]:
    offset = norm360(longitude - WHEEL_START)
    index = int(offset // GATE_ARC)
    within = offset - index * GATE_ARC
    line = int(within // LINE_ARC) + 1
    return WHEEL[index], min(line, 6)


def design_julian_day(eph, natal_jd: float) -> float:
    """Solve for the moment the Sun was SOLAR_ARC degrees before its natal position.

    Bisection on the unwrapped arc travelled. The Sun's motion is monotonic in
    longitude, so the bracket [natal - 95d, natal - 82d] always contains the root.
    """
    target = norm360(eph.position(natal_jd, Body.SUN).longitude - SOLAR_ARC)

    def travelled(jd: float) -> float:
        """Degrees the Sun still needs to travel from jd to reach the target."""
        return norm360(target - eph.position(jd, Body.SUN).longitude)

    low, high = natal_jd - 95.0, natal_jd - 82.0
    # travelled() is near 0 at the root and near 360 just past it; bisect on the
    # signed arc measured as a value in (-180, 180].
    def signed(jd: float) -> float:
        arc = travelled(jd)
        return arc - 360.0 if arc > 180.0 else arc

    for _ in range(80):  # ~1e-22 day resolution; converges long before that
        mid = (low + high) / 2.0
        if signed(mid) > 0.0:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def activations(eph, jd: float) -> dict[str, Activation]:
    """Gate/line for every body plus the derived Earth and South Node points."""
    result: dict[str, Activation] = {}
    positions = eph.positions(jd, list(Body))
    for body in sorted(positions, key=str):
        lon = positions[body].longitude
        gate, line = gate_line(lon)
        result[str(body)] = Activation(str(body), gate, line, round(lon, 6))

    for derived, source in (("earth", "sun"), ("south_node", "north_node")):
        lon = norm360(result[source].longitude + 180.0)
        gate, line = gate_line(lon)
        result[derived] = Activation(derived, gate, line, round(lon, 6))

    return result
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_hd_wheel.py -v`
Expected: PASS, 11 tests

If `test_aries_point_falls_in_gate_25` fails, the `WHEEL` constant is wrong — do
not adjust `WHEEL_START` to compensate. Re-derive the wheel order against a
published gate table and fix the constant.

- [ ] **Step 5: Commit**

```bash
git add engine/systems/hd_wheel.py tests/test_hd_wheel.py
git commit -m "feat: I-Ching gate wheel and 88-degree design-moment solver"
```

---

### Task 4: Human Design bodygraph

**Files:**
- Create: `engine/systems/data/hd_gates.yaml`, `engine/systems/data/hd_channels.yaml`
- Create: `engine/systems/human_design.py`
- Create: `kb/human_design/types.yaml`, `kb/human_design/authorities.yaml`,
  `kb/human_design/profiles.yaml`, `kb/human_design/centers.yaml`
- Test: `tests/test_human_design.py`

**Interfaces:**
- Consumes: `engine.systems.hd_wheel.*`, `engine.ephemeris.*`, `engine.kb.loader`.
- Produces:
  - `engine.systems.human_design.CENTERS: tuple[str, ...]` — the nine centers.
  - `engine.systems.human_design.MOTORS: frozenset[str]` —
    `{"sacral", "heart", "solar_plexus", "root"}`.
  - `engine.systems.human_design.gate_center(gate: int) -> str`
  - `engine.systems.human_design.defined_channels(gates: set[int]) -> list[str]` —
    channel keys like `"10-20"`, sorted.
  - `engine.systems.human_design.HumanDesignCalculator` — `key = "human_design"`,
    `required_inputs = {BIRTH_DATE, BIRTH_TIME, BIRTH_PLACE}`.
  - `raw` shape:

```jsonc
{
  "type": "Projector",
  "strategy": "Wait for the invitation",
  "authority": "Splenic",
  "profile": "3/5",
  "definition": "single",
  "defined_centers": ["ajna", "spleen", "throat"],
  "open_centers": ["g", "heart", "head", "root", "sacral", "solar_plexus"],
  "channels": ["20-57"],
  "gates": [20, 57, ...],
  "personality": {"sun": {"gate": 26, "line": 3}, ...},
  "design": {"sun": {"gate": 45, "line": 5}, ...}
}
```

**Type rules (implement exactly):**
| Sacral | Motor→Throat | Any centre defined | Type |
|---|---|---|---|
| defined | yes | — | Manifesting Generator |
| defined | no | — | Generator |
| undefined | yes | — | Manifestor |
| undefined | no | yes | Projector |
| — | — | no | Reflector |

**Authority hierarchy (first match wins):** Solar Plexus defined → `Emotional`;
else Sacral defined → `Sacral`; else Spleen defined → `Splenic`; else Heart defined
and connected to Throat → `Ego Manifested`; else Heart defined → `Ego Projected`;
else G defined and connected to Throat → `Self-Projected`; else Reflector →
`Lunar`; else → `Mental Projected` (outer authority).

**Profile:** `f"{personality_sun_line}/{design_sun_line}"`.

**Definition:** count connected components among defined centers linked by defined
channels — `1 → "single"`, `2 → "split"`, `3 → "triple split"`,
`4 → "quadruple split"`, `0 → "none"`.

- [ ] **Step 1: Write the gate→center and channel data files**

```yaml
# engine/systems/data/hd_gates.yaml
# Gate -> center. All 64 gates; counts per center: head 3, ajna 6, throat 11,
# g 8, heart 4, sacral 9, solar_plexus 7, spleen 7, root 9.
schema: hd.gates.v1
centers:
  head:         [61, 63, 64]
  ajna:         [4, 11, 17, 24, 43, 47]
  throat:       [8, 12, 16, 20, 23, 31, 33, 35, 45, 56, 62]
  g:            [1, 2, 7, 10, 13, 15, 25, 46]
  heart:        [21, 26, 40, 51]
  sacral:       [3, 5, 9, 14, 27, 29, 34, 42, 59]
  solar_plexus: [6, 22, 30, 36, 37, 49, 55]
  spleen:       [18, 28, 32, 44, 48, 50, 57]
  root:         [19, 38, 39, 41, 52, 53, 54, 58, 60]
```

```yaml
# engine/systems/data/hd_channels.yaml
# The 36 channels. Each is a gate pair; a channel is defined when BOTH gates are
# activated (by either the personality or the design side).
schema: hd.channels.v1
channels:
  - [1, 8]
  - [2, 14]
  - [3, 60]
  - [4, 63]
  - [5, 15]
  - [6, 59]
  - [7, 31]
  - [9, 52]
  - [10, 20]
  - [10, 34]
  - [10, 57]
  - [11, 56]
  - [12, 22]
  - [13, 33]
  - [16, 48]
  - [17, 62]
  - [18, 58]
  - [19, 49]
  - [20, 34]
  - [20, 57]
  - [21, 45]
  - [23, 43]
  - [24, 61]
  - [25, 51]
  - [26, 44]
  - [27, 50]
  - [28, 38]
  - [29, 46]
  - [30, 41]
  - [32, 54]
  - [34, 57]
  - [35, 36]
  - [37, 40]
  - [39, 55]
  - [42, 53]
  - [47, 64]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_human_design.py
import datetime as dt

import pytest

from engine.systems.human_design import (
    CENTERS,
    MOTORS,
    HumanDesignCalculator,
    defined_channels,
    gate_center,
    load_channels,
    load_gate_centers,
)
from engine.types import BirthInput, InputField


def make_input(**over):
    base = dict(full_name="Casey Rivera", birth_date=dt.date(1990, 5, 5),
                birth_time=dt.time(3, 0), lat=40.7128, lon=-74.0060,
                tz="America/New_York", hebrew_name=None)
    base.update(over)
    return BirthInput(**base)


def test_all_64_gates_are_assigned_to_exactly_one_center():
    mapping = load_gate_centers()
    assert sorted(mapping) == list(range(1, 65))
    assert set(mapping.values()) == set(CENTERS)


def test_there_are_nine_centers_and_four_motors():
    assert len(CENTERS) == 9
    assert MOTORS == {"sacral", "heart", "solar_plexus", "root"}
    assert MOTORS <= set(CENTERS)


def test_there_are_exactly_36_channels_all_over_known_gates():
    channels = load_channels()
    assert len(channels) == 36
    assert len(set(channels)) == 36
    for a, b in channels:
        assert gate_center(a) and gate_center(b)


def test_channel_requires_both_gates():
    assert defined_channels({10, 20}) == ["10-20"]
    assert defined_channels({10}) == []
    assert defined_channels({10, 20, 34}) == ["10-20", "10-34", "20-34"]


def test_channel_keys_are_sorted_and_low_gate_first():
    assert defined_channels({34, 10}) == ["10-34"]


def test_known_chart_produces_a_coherent_bodygraph():
    raw = HumanDesignCalculator().compute(make_input()).raw
    assert raw["type"] in {
        "Generator", "Manifesting Generator", "Projector", "Manifestor", "Reflector"
    }
    assert raw["authority"]
    assert "/" in raw["profile"]
    assert set(raw["defined_centers"]) | set(raw["open_centers"]) == set(CENTERS)
    assert not set(raw["defined_centers"]) & set(raw["open_centers"])


def test_every_defined_center_is_backed_by_a_defined_channel():
    raw = HumanDesignCalculator().compute(make_input()).raw
    channel_gates = set()
    for key in raw["channels"]:
        a, b = (int(x) for x in key.split("-"))
        channel_gates |= {a, b}
    backed = {gate_center(g) for g in channel_gates}
    assert set(raw["defined_centers"]) == backed


def test_profile_is_personality_over_design_sun_lines():
    raw = HumanDesignCalculator().compute(make_input()).raw
    personality_line = raw["personality"]["sun"]["line"]
    design_line = raw["design"]["sun"]["line"]
    assert raw["profile"] == f"{personality_line}/{design_line}"


def test_both_sides_carry_fourteen_activations():
    raw = HumanDesignCalculator().compute(make_input()).raw
    assert len(raw["personality"]) == 14
    assert len(raw["design"]) == 14


def test_missing_birth_time_yields_zero_confidence_and_no_tags():
    """Spec §3.2 and §8: HD is excluded from synthesis without a birth time."""
    calc = HumanDesignCalculator()
    assert InputField.BIRTH_TIME in calc.required_inputs
    out = calc.compute(make_input(birth_time=None))
    assert out.confidence == 0.0
    assert out.tags == []
    assert any("birth time" in n.lower() for n in out.notes)
    assert out.raw["available"] is False


def test_emits_type_authority_and_profile_tags():
    out = HumanDesignCalculator().compute(make_input())
    elements = {t.element for t in out.tags}
    assert "types" in elements
    assert "authorities" in elements


def test_output_is_deterministic():
    a = HumanDesignCalculator().compute(make_input())
    b = HumanDesignCalculator().compute(make_input())
    assert a.raw == b.raw
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_human_design.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.systems.human_design'`

- [ ] **Step 4: Implement `engine/systems/human_design.py`**

```python
"""Human Design bodygraph (spec §3.2).

Requires a birth time. Without one the module returns confidence 0.0 and is
excluded from synthesis rather than guessing — an HD chart computed for noon is
wrong often enough to be worse than absent.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

from engine.ephemeris import get_ephemeris
from engine.kb.loader import load_kb
from engine.systems.hd_wheel import activations, design_julian_day
from engine.types import BirthInput, InputField, SystemOutput, TraitTag

DATA_DIR = Path(__file__).parent / "data"

CENTERS = (
    "head", "ajna", "throat", "g", "heart",
    "sacral", "solar_plexus", "spleen", "root",
)
MOTORS = frozenset({"sacral", "heart", "solar_plexus", "root"})

STRATEGY = {
    "Generator": "Wait to respond",
    "Manifesting Generator": "Wait to respond, then inform",
    "Projector": "Wait for the invitation",
    "Manifestor": "Inform before acting",
    "Reflector": "Wait a lunar cycle",
}

DEFINITION_NAMES = {0: "none", 1: "single", 2: "split", 3: "triple split",
                    4: "quadruple split"}


@functools.lru_cache(maxsize=1)
def load_gate_centers() -> dict[int, str]:
    doc = yaml.safe_load((DATA_DIR / "hd_gates.yaml").read_text(encoding="utf-8"))
    return {gate: center for center, gates in doc["centers"].items() for gate in gates}


@functools.lru_cache(maxsize=1)
def load_channels() -> tuple[tuple[int, int], ...]:
    doc = yaml.safe_load((DATA_DIR / "hd_channels.yaml").read_text(encoding="utf-8"))
    return tuple(tuple(sorted(pair)) for pair in doc["channels"])  # type: ignore[misc]


def gate_center(gate: int) -> str:
    return load_gate_centers()[gate]


def defined_channels(gates: set[int]) -> list[str]:
    return sorted(
        (f"{a}-{b}" for a, b in load_channels() if a in gates and b in gates),
        key=lambda key: tuple(int(x) for x in key.split("-")),
    )


def _components(defined: set[str], channels: list[str]) -> int:
    """Count connected components among defined centers linked by channels."""
    parent = {c: c for c in defined}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for key in channels:
        a, b = (gate_center(int(g)) for g in key.split("-"))
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


def _motor_reaches_throat(defined: set[str], channels: list[str]) -> bool:
    """True when any motor center is connected to the throat through defined channels."""
    if "throat" not in defined:
        return False
    adjacency: dict[str, set[str]] = {c: set() for c in defined}
    for key in channels:
        a, b = (gate_center(int(g)) for g in key.split("-"))
        adjacency[a].add(b)
        adjacency[b].add(a)

    seen, stack = {"throat"}, ["throat"]
    while stack:
        node = stack.pop()
        if node in MOTORS:
            return True
        for neighbour in sorted(adjacency[node]):
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return False


def _determine_authority(defined: set[str], channels: list[str], hd_type: str) -> str:
    if "solar_plexus" in defined:
        return "Emotional"
    if "sacral" in defined:
        return "Sacral"
    if "spleen" in defined:
        return "Splenic"
    if "heart" in defined:
        return "Ego Manifested" if _connected(defined, channels, "heart", "throat") \
            else "Ego Projected"
    if "g" in defined and _connected(defined, channels, "g", "throat"):
        return "Self-Projected"
    if hd_type == "Reflector":
        return "Lunar"
    return "Mental Projected"


def _connected(defined: set[str], channels: list[str], a: str, b: str) -> bool:
    if a not in defined or b not in defined:
        return False
    adjacency: dict[str, set[str]] = {c: set() for c in defined}
    for key in channels:
        x, y = (gate_center(int(g)) for g in key.split("-"))
        adjacency[x].add(y)
        adjacency[y].add(x)
    seen, stack = {a}, [a]
    while stack:
        node = stack.pop()
        if node == b:
            return True
        for neighbour in sorted(adjacency[node]):
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return False


def _side(acts) -> dict[str, dict]:
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

        eph = get_ephemeris()
        natal_jd = eph.julian_day(inp.utc_datetime)
        design_jd = design_julian_day(eph, natal_jd)

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
            "definition": DEFINITION_NAMES.get(_components(defined, channels), "multiple"),
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

        return SystemOutput(raw=raw, tags=tags, confidence=1.0, notes=[])
```

- [ ] **Step 5: Write the Human Design KB files**

`kb/human_design/types.yaml` — five keys: `generator`, `manifesting_generator`,
`projector`, `manifestor`, `reflector`.

```yaml
schema: kb.mapping.v1
system: human_design
element: types
reviewed: true
source: >-
  Human Design as taught in the mainstream Jovian-derived lineage. Interpretive
  choice: type is read as energy mechanics and correct entry to action, not as
  personality.
entries:
  generator:
    label: "Generator"
    text: "Sustainable working energy that switches on in response to what is in front of it, not to what it initiates from scratch."
    tags:
      - {facet: drive.initiative, weight: 0.7, direction: low}
      - {facet: work_energy.endurance, weight: 0.9, direction: high}
      - {facet: work_energy.rhythm, weight: 0.7, direction: low}
      - {facet: decision_making.gut_vs_deliberation, weight: 0.8, direction: high}
  projector:
    label: "Projector"
    text: "Reads systems and people rather than out-working them; runs best on recognition and rest, worst on grind."
    tags:
      - {facet: drive.recognition, weight: 0.9, direction: high}
      - {facet: work_energy.endurance, weight: 0.8, direction: low}
      - {facet: work_energy.role_shape, weight: 0.6, direction: high}
      - {facet: communication.listening, weight: 0.7, direction: high}
  manifestor:
    label: "Manifestor"
    text: "Initiates without waiting; the friction comes from other people not being told first."
    tags:
      - {facet: drive.initiative, weight: 0.9, direction: high}
      - {facet: relational.autonomy, weight: 0.9, direction: high}
      - {facet: decision_making.timing, weight: 0.8, direction: high}
  manifesting_generator:
    label: "Manifesting Generator"
    text: "Responds like a Generator but skips steps; several things at once is the natural state, not a failure of focus."
    tags:
      - {facet: work_energy.endurance, weight: 0.8, direction: high}
      - {facet: communication.pace, weight: 0.7, direction: high}
      - {facet: drive.novelty_seeking, weight: 0.7, direction: high}
  reflector:
    label: "Reflector"
    text: "Samples the environment rather than carrying a fixed energy; who they are around changes what they are."
    tags:
      - {facet: emotional.sensitivity, weight: 0.9, direction: high}
      - {facet: decision_making.timing, weight: 0.9, direction: low}
      - {facet: core_essence.archetype_force, weight: 0.8, direction: low}
```

Then write:
- `kb/human_design/authorities.yaml` — keys `emotional`, `sacral`, `splenic`,
  `ego_manifested`, `ego_projected`, `self-projected` (use `self_projected` after
  the `.replace(" ", "_")` — note the calculator lowercases and replaces spaces,
  so `Self-Projected` becomes `self-projected`; **use that exact key**),
  `mental_projected`, `lunar`. These weight `decision_making.*` heavily per §4.1.
- `kb/human_design/profiles.yaml` — the twelve profiles keyed `1_3`, `1_4`, `2_4`,
  `2_5`, `3_5`, `3_6`, `4_6`, `4_1`, `5_1`, `5_2`, `6_2`, `6_3`.
- `kb/human_design/centers.yaml` — nine keys `head_defined` … `root_defined`.

Append to `kb/manifest.yaml`:

```yaml
  human_design/types:
    keys: ["generator", "manifesting_generator", "projector", "manifestor", "reflector"]
  human_design/authorities:
    keys: ["emotional", "sacral", "splenic", "ego_manifested", "ego_projected",
           "self-projected", "mental_projected", "lunar"]
  human_design/profiles:
    keys: ["1_3", "1_4", "2_4", "2_5", "3_5", "3_6",
           "4_6", "4_1", "5_1", "5_2", "6_2", "6_3"]
  human_design/centers:
    keys: ["head_defined", "ajna_defined", "throat_defined", "g_defined",
           "heart_defined", "sacral_defined", "solar_plexus_defined",
           "spleen_defined", "root_defined"]
```

The `self-projected` key keeps its hyphen because the calculator derives KB keys
with `.lower().replace(" ", "_")`, which leaves `Self-Projected` as
`self-projected`. Match the calculator, not your instinct for consistency —
`tests/test_kb_completeness.py` will catch a mismatch either way.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_human_design.py tests/test_kb_validation.py \
      tests/test_kb_completeness.py -v`
Expected: PASS, 12 tests plus the completeness parametrization

- [ ] **Step 7: Register, regenerate goldens, commit**

Add `HumanDesignCalculator()` to `SYSTEM_REGISTRY` in `engine/orchestrator.py`.

Run: `.venv/bin/python kb_tools/regenerate_golden.py && .venv/bin/pytest -v`

Review `git diff tests/golden/` — check the `no_birth_time` fixture shows
`"human_design": {"available": false, "confidence": 0.0, ...}`.

```bash
git add engine/systems/human_design.py engine/systems/data/ kb/human_design/ \
        tests/test_human_design.py engine/orchestrator.py tests/golden/
git commit -m "feat: Human Design bodygraph with type, authority, profile and definition"
```

---

### Task 5: Gene Keys activation sequence

**Files:**
- Create: `engine/systems/gene_keys.py`
- Create: `kb/gene_keys/keys.yaml`
- Test: `tests/test_gene_keys.py`

**Interfaces:**
- Consumes: `engine.systems.hd_wheel.*` (**not** `human_design.py`).
- Produces:
  - `engine.systems.gene_keys.SEQUENCE: tuple[tuple[str, str, str], ...]` —
    `(label, side, point)` triples defining the Activation Sequence.
  - `engine.systems.gene_keys.GeneKeysCalculator` — `key = "gene_keys"`,
    `required_inputs = {BIRTH_DATE, BIRTH_TIME, BIRTH_PLACE}`.
  - `raw` shape:

```jsonc
{
  "activation_sequence": {
    "lifes_work":  {"gene_key": 26, "line": 3, "shadow": "Pride", "gift": "Artfulness", "siddhi": "Invisibility"},
    "evolution":   {"gene_key": 45, "line": 3, ...},
    "radiance":    {"gene_key": 12, "line": 5, ...},
    "purpose":     {"gene_key": 11, "line": 5, ...}
  },
  "available": true
}
```

**The four points (spec §3.3):** Life's Work = personality Sun; Evolution =
personality Earth; Radiance = design Sun; Purpose = design Earth.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gene_keys.py
import datetime as dt

from engine.systems.gene_keys import SEQUENCE, GeneKeysCalculator
from engine.types import BirthInput


def make_input(**over):
    base = dict(full_name="Casey Rivera", birth_date=dt.date(1990, 5, 5),
                birth_time=dt.time(3, 0), lat=40.7128, lon=-74.0060,
                tz="America/New_York", hebrew_name=None)
    base.update(over)
    return BirthInput(**base)


def test_sequence_is_the_four_spec_points():
    assert [label for label, _, _ in SEQUENCE] == [
        "lifes_work", "evolution", "radiance", "purpose"
    ]


def test_all_four_points_are_populated():
    raw = GeneKeysCalculator().compute(make_input()).raw
    seq = raw["activation_sequence"]
    assert set(seq) == {"lifes_work", "evolution", "radiance", "purpose"}
    for point in seq.values():
        assert 1 <= point["gene_key"] <= 64
        assert 1 <= point["line"] <= 6
        assert point["shadow"] and point["gift"] and point["siddhi"]


def test_lifes_work_and_evolution_are_opposite_hexagrams():
    """Personality Sun and Earth are 180 deg apart, so their gates are the wheel opposites."""
    seq = GeneKeysCalculator().compute(make_input()).raw["activation_sequence"]
    assert seq["lifes_work"]["gene_key"] != seq["evolution"]["gene_key"]


def test_gene_keys_match_the_human_design_sun_gates():
    """Gene Keys reuses the HD gate math (spec §3.3) — the numbers must agree."""
    from engine.systems.human_design import HumanDesignCalculator

    inp = make_input()
    hd = HumanDesignCalculator().compute(inp).raw
    gk = GeneKeysCalculator().compute(inp).raw["activation_sequence"]
    assert gk["lifes_work"]["gene_key"] == hd["personality"]["sun"]["gate"]
    assert gk["evolution"]["gene_key"] == hd["personality"]["earth"]["gate"]
    assert gk["radiance"]["gene_key"] == hd["design"]["sun"]["gate"]
    assert gk["purpose"]["gene_key"] == hd["design"]["earth"]["gate"]


def test_gene_keys_does_not_import_the_human_design_calculator():
    """Spec §3.3: Gene Keys reuses the wheel, not the bodygraph module."""
    import pathlib

    source = pathlib.Path("engine/systems/gene_keys.py").read_text(encoding="utf-8")
    assert "human_design" not in source


def test_missing_birth_time_excludes_the_system():
    out = GeneKeysCalculator().compute(make_input(birth_time=None))
    assert out.confidence == 0.0
    assert out.tags == []
    assert out.raw["available"] is False


def test_emits_tags_for_each_populated_point():
    out = GeneKeysCalculator().compute(make_input())
    assert out.tags
    assert all(t.system == "gene_keys" for t in out.tags)


def test_output_is_deterministic():
    a = GeneKeysCalculator().compute(make_input())
    b = GeneKeysCalculator().compute(make_input())
    assert a.raw == b.raw
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_gene_keys.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.systems.gene_keys'`

- [ ] **Step 3: Implement `engine/systems/gene_keys.py`**

```python
"""Gene Keys Activation Sequence (spec §3.3).

Reuses the shared I-Ching wheel from hd_wheel, deliberately not the Human Design
calculator: the two systems share gate math, not bodygraph logic.
"""

from __future__ import annotations

from engine.ephemeris import get_ephemeris
from engine.kb.loader import load_kb
from engine.systems.hd_wheel import activations, design_julian_day
from engine.types import BirthInput, InputField, SystemOutput, TraitTag

# (label, side, point)
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
                    "birth time missing: Gene Keys derives from the Human Design "
                    "gate math and is excluded from synthesis"
                ],
            )

        eph = get_ephemeris()
        natal_jd = eph.julian_day(inp.utc_datetime)
        sides = {
            "personality": activations(eph, natal_jd),
            "design": activations(eph, design_julian_day(eph, natal_jd)),
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


def _spectrum(entry) -> dict[str, str]:
    """Shadow/gift/siddhi keywords, encoded in the KB entry label as 'Shadow|Gift|Siddhi'."""
    if entry is None:
        return {"shadow": "", "gift": "", "siddhi": ""}
    parts = [p.strip() for p in entry.label.split("|")]
    while len(parts) < 3:
        parts.append("")
    return {"shadow": parts[0], "gift": parts[1], "siddhi": parts[2]}
```

- [ ] **Step 4: Write `kb/gene_keys/keys.yaml`**

64 entries keyed `"1"` … `"64"`. The `label` encodes the spectrum as
`Shadow|Gift|Siddhi` — that is what `_spectrum()` parses, so the pipe format is
load-bearing, not cosmetic. Four shown; write all 64.

```yaml
schema: kb.mapping.v1
system: gene_keys
element: keys
reviewed: true
source: >-
  Gene Keys spectrum keywords (shadow / gift / siddhi) per Richard Rudd's
  published sequence. Interpretive choice: the label field encodes the three
  spectrum words separated by '|', which the calculator parses.
entries:
  "1":
    label: "Entropy|Freshness|Beauty"
    text: "Creative force that stalls when it waits for permission; freshness returns by starting again rather than repairing."
    tags:
      - {facet: life_themes.transformation, weight: 0.7, direction: high}
      - {facet: drive.initiative, weight: 0.6, direction: high}
  "2":
    label: "Dislocation|Orientation|Unity"
    text: "A search for one's own direction; settles when the inner compass is trusted over the map others hand over."
    tags:
      - {facet: core_essence.self_image, weight: 0.7, direction: low}
      - {facet: life_themes.seeking, weight: 0.7, direction: high}
  "11":
    label: "Obscurity|Idealism|Light"
    text: "Ideas arrive faster than they can be built; the gift is holding a vision without demanding it arrive on schedule."
    tags:
      - {facet: life_themes.seeking, weight: 0.8, direction: high}
      - {facet: growth_edges.patience, weight: 0.6, direction: high}
  "26":
    label: "Pride|Artfulness|Invisibility"
    text: "Persuasive and self-selling; the growth edge is knowing when the pitch has become the point."
    tags:
      - {facet: communication.register, weight: 0.8, direction: high}
      - {facet: growth_edges.self_worth, weight: 0.7, direction: high}
```

Append to `kb/manifest.yaml` — all 64, which is what forces the file to be
finished rather than sampled:

```yaml
  gene_keys/keys:
    keys: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13",
           "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24",
           "25", "26", "27", "28", "29", "30", "31", "32", "33", "34", "35",
           "36", "37", "38", "39", "40", "41", "42", "43", "44", "45", "46",
           "47", "48", "49", "50", "51", "52", "53", "54", "55", "56", "57",
           "58", "59", "60", "61", "62", "63", "64"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_gene_keys.py tests/test_kb_validation.py \
      tests/test_kb_completeness.py -v`
Expected: PASS, 8 tests plus the completeness parametrization

- [ ] **Step 6: Register, regenerate goldens, commit**

Add `GeneKeysCalculator()` to `SYSTEM_REGISTRY`, then:

```bash
.venv/bin/python kb_tools/regenerate_golden.py && .venv/bin/pytest -v
git add engine/systems/gene_keys.py kb/gene_keys/ tests/test_gene_keys.py \
        engine/orchestrator.py tests/golden/
git commit -m "feat: Gene Keys activation sequence over the shared gate wheel"
```

---

### Task 6: Jewish numerology and Kabbalah

**Files:**
- Create: `engine/systems/kabbalah.py`
- Create: `kb/kabbalah/sefirot.yaml`, `kb/kabbalah/hebrew_months.yaml`,
  `kb/kabbalah/equivalences.yaml`
- Test: `tests/test_kabbalah.py`

**Interfaces:**
- Consumes: `engine.names.normalize`, `pyluach`, `engine.kb.loader`.
- Produces:
  - `engine.systems.kabbalah.MISPAR_HECHRECHI: dict[str, int]` — standard letter
    values, with the five final forms mapping to their base values.
  - `engine.systems.kabbalah.gematria(text: str) -> int`
  - `engine.systems.kabbalah.gematria_reduced(value: int) -> int` — digit-sum to
    a single digit (no master-number preservation here; that is a numerology rule,
    not a gematria one).
  - `engine.systems.kabbalah.sefirah_for(value: int) -> str` — the ten sefirot
    cycled by `((reduced - 1) % 10)`, with `Keter` at reduced value 1.
  - `engine.systems.kabbalah.KabbalahCalculator` — `key = "kabbalah"`,
    `required_inputs = {InputField.FULL_NAME, InputField.BIRTH_DATE}`.
  - `raw` shape:

```jsonc
{
  "hebrew_name": "אברהם כהן",
  "hebrew_name_quality": "provided",
  "gematria": {"standard": 315, "reduced": 9},
  "sefirah": "Yesod",
  "hebrew_date": {"year": 5707, "month": 2, "month_name": "Iyar", "day": 24,
                  "day_of_week": 4},
  "equivalences": ["chai"]
}
```

**Curation note (spec §3.5):** this module has the least standardized source
material of the six. Every KB file here must carry a `source` header naming the
tradition whose correspondences it uses, and the review bar is the highest.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kabbalah.py
import datetime as dt

from engine.systems.kabbalah import (
    MISPAR_HECHRECHI,
    KabbalahCalculator,
    gematria,
    gematria_reduced,
    sefirah_for,
)
from engine.types import BirthInput


def make_input(**over):
    base = dict(full_name="Avraham Cohen", birth_date=dt.date(1947, 5, 14),
                birth_time=dt.time(18, 30), lat=31.7683, lon=35.2137,
                tz="Asia/Jerusalem", hebrew_name="אברהם כהן")
    base.update(over)
    return BirthInput(**base)


def test_letter_values_follow_mispar_hechrechi():
    assert MISPAR_HECHRECHI["א"] == 1
    assert MISPAR_HECHRECHI["י"] == 10
    assert MISPAR_HECHRECHI["ק"] == 100
    assert MISPAR_HECHRECHI["ת"] == 400


def test_final_forms_take_their_base_values():
    assert MISPAR_HECHRECHI["ך"] == MISPAR_HECHRECHI["כ"] == 20
    assert MISPAR_HECHRECHI["ם"] == MISPAR_HECHRECHI["מ"] == 40
    assert MISPAR_HECHRECHI["ן"] == MISPAR_HECHRECHI["נ"] == 50
    assert MISPAR_HECHRECHI["ף"] == MISPAR_HECHRECHI["פ"] == 80
    assert MISPAR_HECHRECHI["ץ"] == MISPAR_HECHRECHI["צ"] == 90


def test_known_gematria_values():
    assert gematria("חי") == 18          # chai
    assert gematria("אמת") == 441        # emet
    assert gematria("שלום") == 376       # shalom
    assert gematria("אברהם") == 248      # Avraham


def test_gematria_ignores_spaces_and_latin_characters():
    assert gematria("אברהם כהן") == gematria("אברהםכהן")
    assert gematria("Avraham") == 0


def test_reduction_is_a_plain_digit_sum():
    assert gematria_reduced(248) == 5   # 2+4+8=14 -> 5
    assert gematria_reduced(18) == 9
    assert gematria_reduced(11) == 2    # no master-number preservation here


def test_sefirah_cycles_through_ten():
    assert sefirah_for(1) == "Keter"
    assert sefirah_for(10) == "Malkhut"
    assert len({sefirah_for(n) for n in range(1, 11)}) == 10


def test_hebrew_date_conversion_for_a_known_date():
    """1947-05-14 (after sunset conventions ignored) is 24 Iyar 5707."""
    raw = KabbalahCalculator().compute(make_input()).raw
    assert raw["hebrew_date"]["year"] == 5707
    assert raw["hebrew_date"]["month_name"] == "Iyar"
    assert raw["hebrew_date"]["day"] == 24


def test_pre_1948_hebrew_date_is_supported():
    raw = KabbalahCalculator().compute(make_input(birth_date=dt.date(1901, 3, 3))).raw
    assert raw["hebrew_date"]["year"] > 5000


def test_supplied_hebrew_name_is_full_confidence():
    out = KabbalahCalculator().compute(make_input())
    assert out.raw["hebrew_name_quality"] == "provided"
    assert out.confidence == 1.0
    assert out.notes == []


def test_derived_hebrew_name_degrades_confidence_and_notes():
    out = KabbalahCalculator().compute(make_input(hebrew_name=None))
    assert out.raw["hebrew_name_quality"] == "derived"
    assert out.confidence < 1.0
    assert out.notes


def test_emits_sefirah_and_month_tags():
    out = KabbalahCalculator().compute(make_input())
    elements = {t.element for t in out.tags}
    assert "sefirot" in elements
    assert "hebrew_months" in elements


def test_output_is_deterministic():
    a = KabbalahCalculator().compute(make_input())
    b = KabbalahCalculator().compute(make_input())
    assert a.raw == b.raw
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_kabbalah.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.systems.kabbalah'`

- [ ] **Step 3: Implement `engine/systems/kabbalah.py`**

```python
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
    "א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9,
    "י": 10, "כ": 20, "ל": 30, "מ": 40, "נ": 50, "ס": 60, "ע": 70, "פ": 80,
    "צ": 90, "ק": 100, "ר": 200, "ש": 300, "ת": 400,
}
# Final forms take their base values in mispar hechrechi.
_FINALS = {"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}

MISPAR_HECHRECHI: dict[str, int] = {
    **_BASE_VALUES,
    **{final: _BASE_VALUES[base] for final, base in _FINALS.items()},
}

SEFIROT = (
    "Keter", "Chokhmah", "Binah", "Chesed", "Gevurah",
    "Tiferet", "Netzach", "Hod", "Yesod", "Malkhut",
)

HEBREW_MONTH_NAMES = {
    1: "Nisan", 2: "Iyar", 3: "Sivan", 4: "Tammuz", 5: "Av", 6: "Elul",
    7: "Tishrei", 8: "Cheshvan", 9: "Kislev", 10: "Tevet", 11: "Shevat",
    12: "Adar", 13: "Adar II",
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
```

- [ ] **Step 4: Write the Kabbalah KB files**

`kb/kabbalah/sefirot.yaml` — ten lowercase keys, `keter` … `malkhut`.

```yaml
schema: kb.mapping.v1
system: kabbalah
element: sefirot
reviewed: true
source: >-
  Lurianic-derived popular Kabbalah as commonly presented in contemporary
  English-language sources. This is the least standardized of the six systems;
  the correspondence used here assigns a sefirah from the reduced standard
  gematria (mispar hechrechi) of the Hebrew name, with Keter at 1 and Malkhut
  at 10. Other traditions assign differently — that choice is recorded here on
  purpose rather than presented as the only reading.
entries:
  keter:
    label: "Keter"
    text: "An orientation toward the not-yet-formed; comfortable with what has no shape yet, less so with committing it to one."
    tags:
      - {facet: life_themes.seeking, weight: 0.8, direction: high}
      - {facet: work_energy.structure, weight: 0.6, direction: low}
  chokhmah:
    label: "Chokhmah"
    text: "Insight arrives whole rather than assembled; the work is trusting the flash before it can be justified."
    tags:
      - {facet: decision_making.gut_vs_deliberation, weight: 0.8, direction: high}
      - {facet: communication.pace, weight: 0.6, direction: high}
  yesod:
    label: "Yesod"
    text: "A connector and translator; carries what others produce into a form that can actually land."
    tags:
      - {facet: relational.bonding, weight: 0.7, direction: high}
      - {facet: work_energy.role_shape, weight: 0.6, direction: low}
      - {facet: communication.listening, weight: 0.6, direction: high}
```

`kb/kabbalah/hebrew_months.yaml` — thirteen keys `"1"` … `"13"`, each with the
month's traditional meaning in `text` and its own `source` header.

`kb/kabbalah/equivalences.yaml` — the small curated table from §3.5. The `label`
holds the numeric value as a string:

```yaml
schema: kb.mapping.v1
system: kabbalah
element: equivalences
reviewed: true
source: >-
  A small curated set of widely-cited gematria equivalences. Deliberately short:
  the space of coincidental equalities is large and most of it is noise.
entries:
  chai:
    label: "18"
    text: "Shares its value with chai (life) — traditionally read as a vitality signature."
    tags:
      - {facet: drive.intensity, weight: 0.5, direction: high}
  emet:
    label: "441"
    text: "Shares its value with emet (truth) — traditionally read as a directness signature."
    tags:
      - {facet: communication.directness, weight: 0.5, direction: high}
```

Append to `kb/manifest.yaml`. Note `equivalences` is **not** declared — it is a
curated, deliberately open-ended table, and Plan 1 Task 12's
`test_every_declared_entry_carries_at_least_one_tag` would otherwise fight the
untagged numeric entries.

```yaml
  kabbalah/sefirot:
    keys: ["keter", "chokhmah", "binah", "chesed", "gevurah",
           "tiferet", "netzach", "hod", "yesod", "malkhut"]
  kabbalah/hebrew_months:
    keys: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kabbalah.py tests/test_kb_validation.py \
      tests/test_kb_completeness.py -v`
Expected: PASS, 12 tests plus the completeness parametrization

- [ ] **Step 6: Register the sixth system and regenerate goldens**

`engine/orchestrator.py` now registers all six:

```python
SYSTEM_REGISTRY: dict[str, SystemCalculator] = {
    calc.key: calc
    for calc in (
        AstrologyCalculator(),
        ChineseZodiacCalculator(),
        GeneKeysCalculator(),
        HumanDesignCalculator(),
        KabbalahCalculator(),
        NumerologyCalculator(),
    )
}
```

Run: `.venv/bin/python kb_tools/regenerate_golden.py && .venv/bin/pytest -v`

- [ ] **Step 7: Commit**

```bash
git add engine/systems/kabbalah.py kb/kabbalah/ tests/test_kabbalah.py \
        engine/orchestrator.py tests/golden/
git commit -m "feat: gematria, Hebrew calendar and sefirot correspondences"
```

---

### Task 7: Six-system integration and degradation tests

**Files:**
- Create: `tests/test_six_systems.py`
- Modify: `tests/test_determinism.py` (no change needed if it parametrizes over
  `FIXTURES` — verify it does)

**Interfaces:**
- Consumes: `engine.orchestrator.build_profile`, `tests.fixtures.people.FIXTURES`.
- Produces: no new module — this task's deliverable is the evidence that spec §12
  criteria 1, 2 and 4 hold with all six systems registered.

- [ ] **Step 1: Write the integration test**

```python
# tests/test_six_systems.py
"""Spec §12 criteria 1, 2 and 4 with the full six-system registry."""

import time

import pytest

from engine.orchestrator import SYSTEM_REGISTRY, build_profile, profile_bytes
from tests.fixtures.people import FIXTURES

EXPECTED_SYSTEMS = {
    "astrology", "chinese_zodiac", "gene_keys",
    "human_design", "kabbalah", "numerology",
}


def test_all_six_systems_are_registered():
    assert set(SYSTEM_REGISTRY) == EXPECTED_SYSTEMS


def test_full_input_produces_a_complete_six_system_profile():
    """Spec §12 criterion 1."""
    profile = build_profile(FIXTURES["standard"])
    assert set(profile["raw"]) == EXPECTED_SYSTEMS
    assert all(profile["raw"][s]["confidence"] > 0 for s in EXPECTED_SYSTEMS)
    assert profile["synthesis"]["dimensions"]


def test_synthesis_spans_multiple_dimensions_with_provenance():
    profile = build_profile(FIXTURES["standard"])
    dims = profile["synthesis"]["dimensions"]
    assert len(dims) >= 5
    systems_seen = {
        p["system"]
        for dim in dims.values()
        for facet in dim["facets"]
        for p in facet["provenance"]
    }
    assert len(systems_seen) >= 4


def test_convergence_is_reported_on_every_facet():
    for dim in build_profile(FIXTURES["standard"])["synthesis"]["dimensions"].values():
        for facet in dim["facets"]:
            assert 0.0 < facet["convergence"] <= 1.0


def test_missing_birth_time_degrades_exactly_per_spec_section_8():
    """Spec §12 criterion 4."""
    profile = build_profile(FIXTURES["no_birth_time"])
    raw = profile["raw"]

    # Human Design and Gene Keys excluded outright.
    for key in ("human_design", "gene_keys"):
        assert raw[key]["confidence"] == 0.0
        assert raw[key]["available"] is False
        assert raw[key]["notes"]

    # Astrology present but without houses or angles.
    assert raw["astrology"]["confidence"] < 1.0
    assert raw["astrology"]["houses_available"] is False
    assert raw["astrology"]["angles"] is None

    # Date-only systems unaffected.
    assert raw["numerology"]["confidence"] == 1.0
    assert raw["chinese_zodiac"]["confidence"] == 1.0

    # Excluded systems contribute no provenance.
    provenance_systems = {
        p["system"]
        for dim in profile["synthesis"]["dimensions"].values()
        for facet in dim["facets"]
        for p in facet["provenance"]
    }
    assert "human_design" not in provenance_systems
    assert "gene_keys" not in provenance_systems


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_every_fixture_produces_a_profile_without_raising(name):
    profile = build_profile(FIXTURES[name])
    assert profile["versions"]["engine"]
    assert profile["disclaimer"]


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_full_six_system_recompute_is_byte_identical(name):
    """Spec §12 criterion 2."""
    inp = FIXTURES[name]
    assert profile_bytes(build_profile(inp)) == profile_bytes(build_profile(inp))


def test_cold_compute_stays_under_two_seconds():
    """Spec §12 criterion 1: p95 < 2s cold compute."""
    from engine.ephemeris import get_ephemeris
    from engine.kb.facets import load_taxonomy
    from engine.kb.loader import load_kb

    get_ephemeris.cache_clear()
    load_kb.cache_clear()
    load_taxonomy.cache_clear()

    start = time.perf_counter()
    build_profile(FIXTURES["standard"])
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"cold compute took {elapsed:.3f}s"


def test_warm_compute_is_well_under_the_cold_budget():
    build_profile(FIXTURES["standard"])  # warm the caches
    start = time.perf_counter()
    for _ in range(5):
        build_profile(FIXTURES["standard"])
    assert (time.perf_counter() - start) / 5 < 1.0


def test_no_network_import_anywhere_in_the_engine():
    """Spec §2: no external network calls in the request path."""
    import pathlib
    import re

    pattern = re.compile(r"^\s*(import|from)\s+(requests|httpx|urllib|socket|aiohttp)\b", re.M)
    offenders = [
        str(p) for p in pathlib.Path("engine").rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
```

- [ ] **Step 2: Run the whole suite**

Run: `.venv/bin/pytest -v && .venv/bin/ruff check .`
Expected: all PASS, no lint findings.

If `test_cold_compute_stays_under_two_seconds` fails, the likely cause is the
design-time bisection calling the ephemeris 80 times. Reduce the iteration count
to 40 (still ~1e-10 day resolution) before reaching for anything cleverer, and
re-run `test_design_moment_is_exactly_88_degrees_of_solar_arc_earlier` to confirm
the tolerance still holds.

- [ ] **Step 3: Commit**

```bash
git add tests/test_six_systems.py
git commit -m "test: six-system integration, degradation and latency guards"
```

---

## Plan 2 Done-When

- [ ] `pytest` passes and `ruff check .` is clean.
- [ ] `SYSTEM_REGISTRY` holds all six systems from spec §3.
- [ ] `swisseph` is imported in exactly one file, enforced by a test.
- [ ] The gate wheel passes both anchors: starts at Gate 41 at 302°, and 0° Aries
      falls in Gate 25.
- [ ] The design moment is within 0.001° of 88° of solar arc before the natal Sun.
- [ ] Gene Keys gate numbers agree with Human Design's Sun/Earth gates.
- [ ] Missing birth time degrades exactly per §8 — astrology keeps placements and
      loses houses; Human Design and Gene Keys drop to confidence 0.0 and
      contribute no provenance.
- [ ] Golden fixtures regenerated, diffed, and human-checked at each registration.
- [ ] `kb/manifest.yaml` declares all four new systems' files and
      `tests/test_kb_completeness.py` passes — no half-written KB file ships.
- [ ] Cold compute of a full six-system profile is under 2 seconds.

Plan 3 picks up here: `build_profile()` now returns everything the API needs to
store and serve.
