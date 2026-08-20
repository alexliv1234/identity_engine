# Identity Engine — Plan 1: Core Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic core of the identity engine — domain types, input
normalization, the versioned YAML knowledge base, the synthesis layer, and the two
systems that need no ephemeris (Numerology and Chinese zodiac) — so that a birth
input can be turned into a complete two-layer profile in-process.

**Architecture:** A `SystemCalculator` protocol lets each esoteric system be a
self-contained module that emits (a) system-native `raw` output and (b) weighted
`TraitTag`s. A curated YAML knowledge base maps system elements to trait tags
against a fixed facet taxonomy. A synthesis engine aggregates tags into per-facet
scores with provenance, convergence, and explicit tension. An orchestrator wires
a registry of calculators together and emits canonical, byte-stable JSON. No LLM
anywhere in this path.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, `unidecode`, `convertdate`,
pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-19-identity-engine-design.md`

**Follow-on plans:** Plan 2 (chart systems) adds astrology, Human Design, Gene Keys
and Kabbalah behind the same protocol. Plan 3 (API platform) puts FastAPI,
persistence and the playground on top. Neither is required for this plan to be
complete and testable.

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.12.** Pydantic v2 (not v1). pytest for all tests.
- **No external network calls in the request path** — no geocoding APIs, no LLM
  APIs. Place lookup is a bundled offline dataset.
- **Determinism guard:** identical input + versions ⇒ byte-identical profile JSON.
  Stable key ordering, no timestamps inside the profile body.
- **Engine version is semver** (`1.0.0` for v1). **KB version is date-based**
  (`kb-2026.08`). A profile records both.
- **Supported birth date range: 1800-01-01 .. today.** Out of range is an error.
- **Master numbers 11/22/33 are preserved, never reduced.**
- **Tension threshold default `0.4`**, a KB-config tunable — read from
  `kb/facets.yaml`, never hardcoded at a call site.
- **Every KB file requires `reviewed: true`** — validation fails the build otherwise.
- **Every profile carries this exact disclaimer string:**
  `"Reflective and entertainment insight; not medical, psychological, or financial advice."`
- **Stable error codes** (used by Plan 3, defined here):
  `INVALID_BIRTH_DATE`, `INVALID_BIRTH_TIME`, `UNKNOWN_TIMEZONE`, `UNKNOWN_PLACE`,
  `NAME_UNMAPPABLE`, `PERSON_NOT_FOUND`, `UNAUTHORIZED`.
- **No claims of scientific validity** in any user-visible copy or KB text.
- **The engine never fakes precision** — missing inputs degrade `confidence` and
  add a `note`; they never produce invented values.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, deps, pytest/ruff config |
| `engine/__init__.py` | `__version__ = "1.0.0"` — the engine semver |
| `engine/canonical.py` | Canonical JSON serialization + float quantization |
| `engine/types.py` | `BirthInput`, `InputField`, `TraitTag`, `SystemOutput`, `SystemCalculator` |
| `engine/errors.py` | `EngineError` + the stable error-code enum |
| `engine/places/lookup.py` | Offline city → lat/lon/tz resolution |
| `engine/places/data/cities.csv` | Vendored GeoNames-derived dataset |
| `engine/names.py` | Latin + Hebrew transliteration, provenance flags |
| `engine/kb/facets.py` | Facet taxonomy loader (`kb/facets.yaml`) |
| `engine/kb/loader.py` | KB file loader, schema validation, `reviewed` enforcement |
| `engine/kb/manifest.py` | Completeness manifest — what each KB file *must* contain |
| `engine/kb/version.py` | Reads `kb/VERSION` |
| `engine/systems/numerology.py` | Pythagorean numerology calculator |
| `engine/systems/chinese_zodiac.py` | Animal + element with CNY boundary |
| `engine/synthesis.py` | Facet scoring, provenance, convergence, tension |
| `engine/orchestrator.py` | Registry, availability gating, profile assembly |
| `kb/facets.yaml` | The nine-dimension facet taxonomy + config |
| `kb/manifest.yaml` | Required entry keys per KB file |
| `kb/VERSION` | `kb-2026.08` |
| `kb/numerology/*.yaml`, `kb/chinese_zodiac/*.yaml` | Trait mappings |
| `kb_tools/build_cities.py` | One-shot script that vendors the GeoNames extract |
| `kb_tools/draft_kb.py`, `kb_tools/style_guide.md` | Offline LLM-assisted KB authoring ("B assist") |
| `tests/` | Unit, golden-fixture, and property tests mirroring the above |

Files split by responsibility, not layer: each system module owns its own math and
its own tag emission, and its KB files live under a directory named for it.

---

### Task 1: Project scaffolding and canonical JSON

**Files:**
- Create: `pyproject.toml`, `engine/__init__.py`, `engine/canonical.py`,
  `.gitignore`, `README.md`
- Test: `tests/test_canonical.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `engine.__version__: str` — `"1.0.0"`
  - `engine.canonical.quantize(value: Any) -> Any` — recursively rounds every
    `float` to 6 decimal places, leaves other types untouched.
  - `engine.canonical.canonical_json(obj: Any) -> str` — quantizes then dumps with
    `sort_keys=True, separators=(",", ":"), ensure_ascii=False`.

- [ ] **Step 1: Create the package skeleton and config**

```toml
# pyproject.toml
[project]
name = "identity-engine"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.7",
    "PyYAML>=6.0",
    "Unidecode>=1.3",
    "convertdate>=2.4",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=5.0", "ruff>=0.5"]

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["engine*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

```python
# engine/__init__.py
__version__ = "1.0.0"
```

```gitignore
# .gitignore
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.coverage
*.egg-info/
```

Create empty `engine/systems/__init__.py`, `engine/kb/__init__.py`,
`engine/places/__init__.py`, `tests/__init__.py` so imports resolve.

Then set up the environment:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"    # Windows: .venv\Scripts\pip
```

- [ ] **Step 2: Write the failing test for canonical JSON**

```python
# tests/test_canonical.py
import json

from engine.canonical import canonical_json, quantize


def test_quantize_rounds_floats_recursively():
    src = {"a": 0.1234567891, "b": [1.9999999, {"c": 2.0000004}], "d": "x", "e": 3}
    assert quantize(src) == {
        "a": 0.123457,
        "b": [2.0, {"c": 2.0}],
        "d": "x",
        "e": 3,
    }


def test_canonical_json_is_key_order_independent():
    a = canonical_json({"z": 1, "a": {"n": 2, "m": 3}})
    b = canonical_json({"a": {"m": 3, "n": 2}, "z": 1})
    assert a == b
    assert a == '{"a":{"m":3,"n":2},"z":1}'


def test_canonical_json_absorbs_float_noise():
    # The same value arrived at by two float paths must serialize identically.
    left = canonical_json({"deg": 0.1 + 0.2})
    right = canonical_json({"deg": 0.3})
    assert left == right


def test_canonical_json_keeps_non_ascii_literal():
    assert canonical_json({"name": "אברהם"}) == '{"name":"אברהם"}'


def test_canonical_json_round_trips():
    obj = {"a": [1, 2.5, "x", None, True]}
    assert json.loads(canonical_json(obj)) == obj
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_canonical.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.canonical'`

- [ ] **Step 4: Implement `engine/canonical.py`**

```python
"""Canonical JSON serialization.

The determinism guarantee in the spec (§8) is "identical input + versions =>
byte-identical profile JSON". Two things break that: dict key ordering and
float representation noise. This module fixes both.
"""

from __future__ import annotations

import json
from typing import Any

FLOAT_PRECISION = 6


def quantize(value: Any) -> Any:
    """Recursively round floats so equal-in-principle values are equal in bytes."""
    if isinstance(value, float):
        return round(value, FLOAT_PRECISION) + 0.0  # +0.0 normalizes -0.0 to 0.0
    if isinstance(value, dict):
        return {k: quantize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [quantize(v) for v in value]
    return value


def canonical_json(obj: Any) -> str:
    """Serialize with sorted keys, no whitespace, and quantized floats."""
    return json.dumps(
        quantize(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_canonical.py -v`
Expected: PASS, 5 tests

- [ ] **Step 6: Verify lint is clean**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: no findings. If `ruff format --check` reports files, run
`.venv/bin/ruff format .` and re-run.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore engine/ tests/
git commit -m "feat: project scaffolding and canonical JSON serialization"
```

---

### Task 2: Domain types and error codes

**Files:**
- Create: `engine/types.py`, `engine/errors.py`
- Test: `tests/test_types.py`

**Interfaces:**
- Consumes: `engine.canonical` (not directly, but types must be JSON-safe).
- Produces:
  - `engine.errors.ErrorCode` — `StrEnum` with members `INVALID_BIRTH_DATE`,
    `INVALID_BIRTH_TIME`, `UNKNOWN_TIMEZONE`, `UNKNOWN_PLACE`, `NAME_UNMAPPABLE`,
    `PERSON_NOT_FOUND`, `UNAUTHORIZED`.
  - `engine.errors.EngineError(code: ErrorCode, message: str, field: str | None = None)`
    — exception carrying a stable code; `.to_dict() -> dict`.
  - `engine.types.InputField` — `StrEnum`: `FULL_NAME`, `BIRTH_DATE`, `BIRTH_TIME`,
    `BIRTH_PLACE`, `HEBREW_NAME`.
  - `engine.types.BirthInput` — frozen Pydantic model, fields
    `full_name: str`, `birth_date: datetime.date`, `birth_time: datetime.time | None`,
    `lat: float`, `lon: float`, `tz: str`, `hebrew_name: str | None`.
    Property `available_fields -> set[InputField]`.
    Property `utc_datetime -> datetime | None` (None when `birth_time` is None).
  - `engine.types.TraitTag` — frozen dataclass:
    `facet: str, weight: float, direction: Literal["high","low"], system: str,
    element: str, text: str`.
  - `engine.types.SystemOutput` — frozen dataclass:
    `raw: dict, tags: list[TraitTag], confidence: float, notes: list[str]`.
  - `engine.types.SystemCalculator` — runtime-checkable Protocol with
    `key: str`, `required_inputs: set[InputField]`, `compute(inp: BirthInput) -> SystemOutput`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_types.py
import datetime as dt

import pytest
from pydantic import ValidationError

from engine.errors import EngineError, ErrorCode
from engine.types import BirthInput, InputField, SystemOutput, TraitTag


def make_input(**over):
    base = dict(
        full_name="Ada Lovelace",
        birth_date=dt.date(1815, 12, 10),
        birth_time=dt.time(13, 0),
        lat=51.5074,
        lon=-0.1278,
        tz="Europe/London",
        hebrew_name=None,
    )
    base.update(over)
    return BirthInput(**base)


def test_birth_input_is_frozen():
    inp = make_input()
    with pytest.raises(ValidationError):
        inp.full_name = "Someone Else"


def test_available_fields_reflects_optional_inputs():
    full = make_input(hebrew_name="אבא")
    assert full.available_fields == {
        InputField.FULL_NAME,
        InputField.BIRTH_DATE,
        InputField.BIRTH_TIME,
        InputField.BIRTH_PLACE,
        InputField.HEBREW_NAME,
    }
    sparse = make_input(birth_time=None)
    assert InputField.BIRTH_TIME not in sparse.available_fields
    assert InputField.HEBREW_NAME not in sparse.available_fields


def test_birth_date_below_range_rejected():
    with pytest.raises(ValidationError) as exc:
        make_input(birth_date=dt.date(1799, 12, 31))
    assert ErrorCode.INVALID_BIRTH_DATE in str(exc.value)


def test_birth_date_in_future_rejected():
    future = dt.date.today() + dt.timedelta(days=1)
    with pytest.raises(ValidationError) as exc:
        make_input(birth_date=future)
    assert ErrorCode.INVALID_BIRTH_DATE in str(exc.value)


def test_unknown_timezone_rejected():
    with pytest.raises(ValidationError) as exc:
        make_input(tz="Mars/Olympus_Mons")
    assert ErrorCode.UNKNOWN_TIMEZONE in str(exc.value)


def test_utc_datetime_applies_historical_offset():
    # London 1815 predates standard time zones; tzdb uses LMT (-00:01:15).
    inp = make_input()
    assert inp.utc_datetime.tzinfo is dt.UTC
    assert inp.utc_datetime.date() == dt.date(1815, 12, 10)


def test_utc_datetime_is_none_without_birth_time():
    assert make_input(birth_time=None).utc_datetime is None


def test_engine_error_carries_stable_code():
    err = EngineError(ErrorCode.UNKNOWN_PLACE, "no match for 'Atlantis'", field="birth_place")
    assert err.to_dict() == {
        "code": "UNKNOWN_PLACE",
        "message": "no match for 'Atlantis'",
        "field": "birth_place",
    }


def test_system_output_defaults_are_not_shared():
    a = SystemOutput(raw={}, tags=[], confidence=1.0, notes=[])
    b = SystemOutput(raw={}, tags=[], confidence=1.0, notes=[])
    a.notes.append("x")
    assert b.notes == []


def test_trait_tag_rejects_out_of_range_weight():
    with pytest.raises(ValueError):
        TraitTag(facet="drive.initiative", weight=1.5, direction="high",
                 system="numerology", element="life_path", text="t")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.errors'`

- [ ] **Step 3: Implement `engine/errors.py`**

```python
"""Stable error codes shared by the engine and the API layer (spec §5.4)."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_BIRTH_DATE = "INVALID_BIRTH_DATE"
    INVALID_BIRTH_TIME = "INVALID_BIRTH_TIME"
    UNKNOWN_TIMEZONE = "UNKNOWN_TIMEZONE"
    UNKNOWN_PLACE = "UNKNOWN_PLACE"
    NAME_UNMAPPABLE = "NAME_UNMAPPABLE"
    PERSON_NOT_FOUND = "PERSON_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"


class EngineError(Exception):
    """Raised for caller-fixable problems. The API layer maps these to 4xx."""

    def __init__(self, code: ErrorCode, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field

    def to_dict(self) -> dict:
        return {"code": str(self.code), "message": self.message, "field": self.field}
```

- [ ] **Step 4: Implement `engine/types.py`**

```python
"""Core domain types.

`BirthInput` is the single normalized input to every calculator. It validates
eagerly so no calculator has to re-check ranges or timezone names.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator

from engine.errors import ErrorCode

MIN_BIRTH_DATE = dt.date(1800, 1, 1)


class InputField(StrEnum):
    FULL_NAME = "full_name"
    BIRTH_DATE = "birth_date"
    BIRTH_TIME = "birth_time"
    BIRTH_PLACE = "birth_place"
    HEBREW_NAME = "hebrew_name"


class BirthInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    full_name: str
    birth_date: dt.date
    birth_time: dt.time | None = None
    lat: float
    lon: float
    tz: str
    hebrew_name: str | None = None

    @field_validator("full_name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(f"{ErrorCode.NAME_UNMAPPABLE}: full_name must not be blank")
        return v.strip()

    @field_validator("birth_date")
    @classmethod
    def _date_in_range(cls, v: dt.date) -> dt.date:
        if v < MIN_BIRTH_DATE or v > dt.date.today():
            raise ValueError(
                f"{ErrorCode.INVALID_BIRTH_DATE}: birth_date must be between "
                f"{MIN_BIRTH_DATE.isoformat()} and today"
            )
        return v

    @field_validator("lat")
    @classmethod
    def _lat_in_range(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError(f"{ErrorCode.UNKNOWN_PLACE}: lat out of range")
        return v

    @field_validator("lon")
    @classmethod
    def _lon_in_range(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError(f"{ErrorCode.UNKNOWN_PLACE}: lon out of range")
        return v

    @field_validator("tz")
    @classmethod
    def _tz_known(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"{ErrorCode.UNKNOWN_TIMEZONE}: {v!r} is not an IANA zone") from exc
        return v

    @property
    def available_fields(self) -> set[InputField]:
        present = {InputField.FULL_NAME, InputField.BIRTH_DATE, InputField.BIRTH_PLACE}
        if self.birth_time is not None:
            present.add(InputField.BIRTH_TIME)
        if self.hebrew_name:
            present.add(InputField.HEBREW_NAME)
        return present

    @property
    def utc_datetime(self) -> dt.datetime | None:
        """Birth moment in UTC, or None when birth_time was not supplied."""
        if self.birth_time is None:
            return None
        local = dt.datetime.combine(self.birth_date, self.birth_time, tzinfo=ZoneInfo(self.tz))
        return local.astimezone(dt.UTC)


@dataclass(frozen=True)
class TraitTag:
    """One system element's weighted contribution to one synthesis facet."""

    facet: str
    weight: float
    direction: Literal["high", "low"]
    system: str
    element: str
    text: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"weight must be in 0..1, got {self.weight}")
        if self.direction not in ("high", "low"):
            raise ValueError(f"direction must be 'high' or 'low', got {self.direction!r}")


@dataclass
class SystemOutput:
    raw: dict = field(default_factory=dict)
    tags: list[TraitTag] = field(default_factory=list)
    confidence: float = 1.0
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class SystemCalculator(Protocol):
    key: str
    required_inputs: set[InputField]

    def compute(self, inp: BirthInput) -> SystemOutput: ...
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_types.py -v`
Expected: PASS, 10 tests

- [ ] **Step 6: Commit**

```bash
git add engine/types.py engine/errors.py tests/test_types.py
git commit -m "feat: birth input domain types and stable error codes"
```

---

### Task 3: Offline place lookup

**Files:**
- Create: `engine/places/lookup.py`, `kb_tools/build_cities.py`
- Create (generated): `engine/places/data/cities.csv`
- Test: `tests/test_places.py`

**Interfaces:**
- Consumes: `engine.errors.EngineError`, `engine.errors.ErrorCode`.
- Produces:
  - `engine.places.lookup.Place` — frozen dataclass:
    `name: str, country: str, admin1: str, lat: float, lon: float, tz: str, population: int`.
  - `engine.places.lookup.resolve(query: str) -> Place` — raises
    `EngineError(UNKNOWN_PLACE)` when nothing matches. Query forms accepted:
    `"London"`, `"London, GB"`, `"London, United Kingdom"`.
  - `engine.places.lookup.search(query: str, limit: int = 5) -> list[Place]` —
    ranked candidates, used by the playground's typeahead in Plan 3.

**Why a vendored dataset:** the spec forbids network calls in the request path, so
geocoding must be local. GeoNames `cities15000` is CC BY 4.0 and ships timezone
per city, which is exactly the pair we need (lat/lon **and** IANA tz).

- [ ] **Step 1: Write the vendoring script**

```python
# kb_tools/build_cities.py
"""One-shot: turn the GeoNames cities15000 extract into a compact vendored CSV.

Source: https://download.geonames.org/export/dump/cities15000.zip  (CC BY 4.0)
Also needs countryInfo.txt for ISO -> country-name mapping.

Run manually, commit the output. NOT part of the request path.

    python kb_tools/build_cities.py ~/Downloads/cities15000.txt \
        ~/Downloads/countryInfo.txt engine/places/data/cities.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

GEONAMES_COLUMNS = {"name": 1, "asciiname": 2, "country": 8, "admin1": 10,
                    "population": 14, "lat": 4, "lon": 5, "timezone": 17}


def load_country_names(path: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        names[parts[0]] = parts[4]
    return names


def main(cities_txt: str, country_info: str, out_csv: str) -> None:
    countries = load_country_names(Path(country_info))
    rows = []
    with open(cities_txt, encoding="utf-8") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            rows.append(
                {
                    "name": p[GEONAMES_COLUMNS["name"]],
                    "ascii": p[GEONAMES_COLUMNS["asciiname"]],
                    "country_code": p[GEONAMES_COLUMNS["country"]],
                    "country_name": countries.get(p[GEONAMES_COLUMNS["country"]], ""),
                    "admin1": p[GEONAMES_COLUMNS["admin1"]],
                    "lat": p[GEONAMES_COLUMNS["lat"]],
                    "lon": p[GEONAMES_COLUMNS["lon"]],
                    "tz": p[GEONAMES_COLUMNS["timezone"]],
                    "population": p[GEONAMES_COLUMNS["population"]],
                }
            )
    # Deterministic file order: population desc, then ascii name, then country.
    rows.sort(key=lambda r: (-int(r["population"] or 0), r["ascii"], r["country_code"]))
    out = Path(out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} cities to {out}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
```

Run it against a downloaded GeoNames extract and commit
`engine/places/data/cities.csv`. Add the attribution line to `README.md`:
`City data © GeoNames (https://www.geonames.org), CC BY 4.0.`

- [ ] **Step 2: Write the failing test**

```python
# tests/test_places.py
import pytest

from engine.errors import EngineError, ErrorCode
from engine.places.lookup import resolve, search


def test_resolves_bare_city_to_most_populous_match():
    place = resolve("London")
    assert place.country == "GB"
    assert place.tz == "Europe/London"
    assert 51.0 < place.lat < 52.0
    assert -1.0 < place.lon < 1.0


def test_disambiguates_by_country_code():
    ca = resolve("London, CA")
    assert ca.country == "CA"
    assert ca.tz == "America/Toronto"


def test_disambiguates_by_country_name():
    assert resolve("London, United Kingdom").country == "GB"


def test_lookup_is_accent_and_case_insensitive():
    assert resolve("zurich").name == resolve("Zürich").name


def test_unknown_place_raises_stable_code():
    with pytest.raises(EngineError) as exc:
        resolve("Atlantis, Nowhere")
    assert exc.value.code is ErrorCode.UNKNOWN_PLACE


def test_search_returns_ranked_candidates():
    hits = search("springfield", limit=5)
    assert 1 < len(hits) <= 5
    populations = [h.population for h in hits]
    assert populations == sorted(populations, reverse=True)


def test_resolve_is_deterministic_across_calls():
    assert resolve("Paris") == resolve("Paris")


def test_southern_hemisphere_city_has_correct_sign():
    syd = resolve("Sydney, AU")
    assert syd.lat < 0
    assert syd.tz == "Australia/Sydney"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_places.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.places.lookup'`

- [ ] **Step 4: Implement `engine/places/lookup.py`**

```python
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_places.py -v`
Expected: PASS, 8 tests

- [ ] **Step 6: Commit**

```bash
git add engine/places/ kb_tools/build_cities.py tests/test_places.py README.md
git commit -m "feat: offline GeoNames-backed place lookup"
```

---

### Task 4: Name normalization and transliteration

**Files:**
- Create: `engine/names.py`
- Test: `tests/test_names.py`

**Interfaces:**
- Consumes: `engine.errors`.
- Produces:
  - `engine.names.NameQuality` — `StrEnum`: `PROVIDED`, `DERIVED`.
  - `engine.names.NormalizedName` — frozen dataclass:
    `latin: str, latin_quality: NameQuality, hebrew: str, hebrew_quality: NameQuality,
    notes: list[str]`.
  - `engine.names.normalize(full_name: str, hebrew_name: str | None) -> NormalizedName`
    — raises `EngineError(NAME_UNMAPPABLE)` when `full_name` yields no A–Z letters.
  - `engine.names.latin_letters(text: str) -> str` — uppercase A–Z only, spaces kept
    as word separators.
  - `engine.names.to_hebrew(latin: str) -> str` — deterministic Latin→Hebrew table.

**Transliteration rule (spec §8):** both directions use a *fixed table*, never a
model or a locale-dependent library call. Latin→Hebrew is longest-match-first over
digraphs then single letters, so `SH` → `ש` before `S` → `ס`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_names.py
import pytest

from engine.errors import EngineError, ErrorCode
from engine.names import NameQuality, latin_letters, normalize, to_hebrew


def test_latin_letters_strips_accents_and_punctuation():
    assert latin_letters("Jean-Luc Picard") == "JEAN LUC PICARD"
    assert latin_letters("Renée Zellweger") == "RENEE ZELLWEGER"
    assert latin_letters("O'Brien") == "OBRIEN"


def test_non_latin_name_is_transliterated_and_flagged():
    result = normalize("Владимир Иванов", hebrew_name=None)
    assert result.latin == "VLADIMIR IVANOV"
    assert result.latin_quality is NameQuality.DERIVED
    assert any("translit" in n.lower() for n in result.notes)


def test_latin_name_is_marked_provided():
    result = normalize("Ada Lovelace", hebrew_name=None)
    assert result.latin == "ADA LOVELACE"
    assert result.latin_quality is NameQuality.PROVIDED


def test_supplied_hebrew_name_is_used_verbatim():
    result = normalize("Avraham Cohen", hebrew_name="אברהם כהן")
    assert result.hebrew == "אברהם כהן"
    assert result.hebrew_quality is NameQuality.PROVIDED


def test_missing_hebrew_name_is_derived_and_flagged():
    result = normalize("Avraham Cohen", hebrew_name=None)
    assert result.hebrew_quality is NameQuality.DERIVED
    assert result.hebrew  # non-empty
    assert any("hebrew" in n.lower() for n in result.notes)


def test_hebrew_transliteration_prefers_digraphs():
    assert to_hebrew("SHALOM").startswith("ש")
    assert to_hebrew("CHAIM").startswith("ח")


def test_hebrew_transliteration_is_deterministic():
    assert to_hebrew("DAVID") == to_hebrew("DAVID")


def test_name_with_no_mappable_letters_raises():
    with pytest.raises(EngineError) as exc:
        normalize("123 !!!", hebrew_name=None)
    assert exc.value.code is ErrorCode.NAME_UNMAPPABLE
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_names.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.names'`

- [ ] **Step 3: Implement `engine/names.py`**

```python
"""Name normalization.

Numerology needs Latin letters; gematria needs Hebrew letters. When the caller
supplies only one, we derive the other through a fixed table and mark it DERIVED
so the profile can report reduced confidence rather than fake precision (§8).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from unidecode import unidecode

from engine.errors import EngineError, ErrorCode

_NON_LETTER = re.compile(r"[^A-Z ]+")
_SPACES = re.compile(r"\s+")

# Longest-match-first: digraphs must precede their leading single letters.
LATIN_TO_HEBREW: tuple[tuple[str, str], ...] = (
    ("SH", "ש"), ("CH", "ח"), ("KH", "כ"), ("TZ", "צ"), ("TS", "צ"),
    ("PH", "פ"), ("TH", "ת"), ("A", "א"), ("B", "ב"), ("C", "ק"),
    ("D", "ד"), ("E", "ע"), ("F", "פ"), ("G", "ג"), ("H", "ה"),
    ("I", "י"), ("J", "י"), ("K", "כ"), ("L", "ל"), ("M", "מ"),
    ("N", "נ"), ("O", "ו"), ("P", "פ"), ("Q", "ק"), ("R", "ר"),
    ("S", "ס"), ("T", "ט"), ("U", "ו"), ("V", "ב"), ("W", "ו"),
    ("X", "כס"), ("Y", "י"), ("Z", "ז"),
)

HEBREW_RANGE = re.compile(r"[֐-׿]")


class NameQuality(StrEnum):
    PROVIDED = "provided"
    DERIVED = "derived"


@dataclass(frozen=True)
class NormalizedName:
    latin: str
    latin_quality: NameQuality
    hebrew: str
    hebrew_quality: NameQuality
    notes: list[str] = field(default_factory=list)


def latin_letters(text: str) -> str:
    """Uppercase A-Z with single spaces between words; everything else dropped."""
    folded = unidecode(text).upper()
    stripped = _NON_LETTER.sub("", folded)
    return _SPACES.sub(" ", stripped).strip()


def to_hebrew(latin: str) -> str:
    """Fixed-table Latin -> Hebrew transliteration (deterministic, lossy)."""
    out: list[str] = []
    for word in latin.split(" "):
        i = 0
        while i < len(word):
            for src, dst in LATIN_TO_HEBREW:
                if word.startswith(src, i):
                    out.append(dst)
                    i += len(src)
                    break
            else:
                i += 1
        out.append(" ")
    return "".join(out).strip()


def normalize(full_name: str, hebrew_name: str | None) -> NormalizedName:
    notes: list[str] = []

    latin = latin_letters(full_name)
    if not latin:
        raise EngineError(
            ErrorCode.NAME_UNMAPPABLE,
            "full_name contains no letters that map to the Latin alphabet",
            field="full_name",
        )

    already_latin = bool(re.fullmatch(r"[A-Za-z .'\-]+", full_name.strip()))
    latin_quality = NameQuality.PROVIDED if already_latin else NameQuality.DERIVED
    if latin_quality is NameQuality.DERIVED:
        notes.append(
            "full_name is not Latin script: numerology uses a fixed-table "
            "transliteration, reducing confidence"
        )

    if hebrew_name and HEBREW_RANGE.search(hebrew_name):
        hebrew, hebrew_quality = hebrew_name.strip(), NameQuality.PROVIDED
    else:
        hebrew, hebrew_quality = to_hebrew(latin), NameQuality.DERIVED
        notes.append(
            "no hebrew_name supplied: gematria uses a fixed-table Latin->Hebrew "
            "transliteration, reducing confidence"
        )

    return NormalizedName(
        latin=latin,
        latin_quality=latin_quality,
        hebrew=hebrew,
        hebrew_quality=hebrew_quality,
        notes=notes,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_names.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add engine/names.py tests/test_names.py
git commit -m "feat: deterministic name normalization and transliteration"
```

---

### Task 5: Facet taxonomy

**Files:**
- Create: `kb/facets.yaml`, `kb/VERSION`, `engine/kb/facets.py`, `engine/kb/version.py`
- Test: `tests/test_facets.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `engine.kb.version.kb_version() -> str` — reads `kb/VERSION`, e.g. `"kb-2026.08"`.
  - `engine.kb.facets.Facet` — frozen dataclass:
    `id: str, dimension: str, label: str, high_label: str, low_label: str`.
  - `engine.kb.facets.Dimension` — frozen dataclass:
    `id: str, label: str, order: int, facets: dict[str, Facet]`.
  - `engine.kb.facets.Taxonomy` — frozen dataclass:
    `dimensions: dict[str, Dimension]`, `facets: dict[str, Facet]` (flat, keyed by
    full id like `"drive.initiative"`), `tension_threshold: float`.
    Methods: `has(facet_id) -> bool`, `get(facet_id) -> Facet` (raises `KeyError`),
    `dimension_of(facet_id) -> Dimension`.
  - `engine.kb.facets.load_taxonomy(root: Path | None = None) -> Taxonomy` — cached.

**Facet id format:** `"<dimension>.<facet>"`. Dimension ids are the nine from
spec §4.1: `core_essence`, `drive`, `decision_making`, `communication`,
`emotional`, `relational`, `work_energy`, `growth_edges`, `life_themes`.

- [ ] **Step 1: Write `kb/VERSION` and `kb/facets.yaml`**

```
kb-2026.08
```

```yaml
# kb/facets.yaml
schema: kb.facets.v1
version: kb-2026.08
reviewed: true
config:
  # Spec §4.2: when both directions on one facet score >= this, report a tension
  # instead of averaging it away.
  tension_threshold: 0.4
dimensions:
  core_essence:
    label: "Core essence"
    order: 1
    facets:
      self_image:      {label: "Self-image",        high: "self-assured",   low: "self-questioning"}
      archetype_force: {label: "Archetypal force",  high: "singular",       low: "adaptive"}
      visibility:      {label: "Visibility",        high: "outward",        low: "inward"}
  drive:
    label: "Drive & motivation"
    order: 2
    facets:
      initiative:      {label: "Initiative",        high: "self-starting",  low: "responsive"}
      intensity:       {label: "Intensity",         high: "high-burn",      low: "steady-burn"}
      novelty_seeking: {label: "Novelty seeking",   high: "novelty-seeking", low: "depth-seeking"}
      recognition:     {label: "Recognition need",  high: "needs-recognition", low: "self-validating"}
  decision_making:
    label: "Decision-making style"
    order: 3
    facets:
      gut_vs_deliberation: {label: "Gut vs deliberation", high: "gut", low: "deliberation"}
      timing:              {label: "Decision timing",     high: "immediate",  low: "needs-time"}
      pressure_response:   {label: "Under pressure",      high: "thrives",    low: "dislikes-pressure"}
      risk_appetite:       {label: "Risk appetite",       high: "risk-taking", low: "risk-averse"}
  communication:
    label: "Communication style"
    order: 4
    facets:
      directness:      {label: "Directness",        high: "direct",         low: "indirect"}
      pace:            {label: "Pace",              high: "fast",           low: "measured"}
      register:        {label: "Register",          high: "expressive",     low: "reserved"}
      listening:       {label: "Listening",         high: "absorbing",      low: "asserting"}
  emotional:
    label: "Emotional landscape"
    order: 5
    facets:
      processing:      {label: "Processing style",  high: "in-the-open",    low: "internal"}
      volatility:      {label: "Emotional weather", high: "wave-like",      low: "even"}
      sensitivity:     {label: "Sensitivity",       high: "highly-sensitive", low: "thick-skinned"}
  relational:
    label: "Relational style"
    order: 6
    facets:
      bonding:         {label: "Bonding",           high: "fast-bonding",   low: "slow-bonding"}
      autonomy:        {label: "Autonomy need",     high: "independent",    low: "interdependent"}
      conflict:        {label: "Conflict style",    high: "engages",        low: "avoids"}
      loyalty:         {label: "Loyalty",           high: "committed",      low: "free-ranging"}
  work_energy:
    label: "Work & energy style"
    order: 7
    facets:
      rhythm:          {label: "Sustainable rhythm", high: "sprint",        low: "marathon"}
      structure:       {label: "Structure need",     high: "structured",    low: "improvisational"}
      role_shape:      {label: "Role shape",         high: "leading",       low: "supporting"}
      endurance:       {label: "Endurance",          high: "high-capacity", low: "needs-recovery"}
  growth_edges:
    label: "Growth edges"
    order: 8
    facets:
      control:         {label: "Control",           high: "grips",          low: "drifts"}
      self_worth:      {label: "Self-worth",        high: "over-proves",    low: "under-claims"}
      patience:        {label: "Patience",          high: "impatient",      low: "over-waiting"}
  life_themes:
    label: "Life themes & purpose"
    order: 9
    facets:
      seeking:         {label: "Central seeking",   high: "meaning",        low: "mastery"}
      service:         {label: "Service orientation", high: "outward-serving", low: "self-realizing"}
      transformation:  {label: "Transformation arc", high: "reinvention",   low: "continuity"}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_facets.py
import pytest

from engine.kb.facets import load_taxonomy
from engine.kb.version import kb_version


def test_kb_version_is_date_based():
    assert kb_version().startswith("kb-")


def test_taxonomy_has_the_nine_spec_dimensions():
    tax = load_taxonomy()
    assert set(tax.dimensions) == {
        "core_essence", "drive", "decision_making", "communication", "emotional",
        "relational", "work_energy", "growth_edges", "life_themes",
    }


def test_flat_facet_ids_are_dimension_qualified():
    tax = load_taxonomy()
    assert "decision_making.gut_vs_deliberation" in tax.facets
    facet = tax.get("decision_making.gut_vs_deliberation")
    assert facet.dimension == "decision_making"
    assert facet.high_label == "gut"
    assert facet.low_label == "deliberation"


def test_tension_threshold_comes_from_config_not_code():
    assert load_taxonomy().tension_threshold == 0.4


def test_unknown_facet_raises_keyerror():
    tax = load_taxonomy()
    assert not tax.has("nope.nope")
    with pytest.raises(KeyError):
        tax.get("nope.nope")


def test_dimension_order_is_stable_and_contiguous():
    tax = load_taxonomy()
    orders = sorted(d.order for d in tax.dimensions.values())
    assert orders == list(range(1, 10))


def test_taxonomy_is_cached_singleton():
    assert load_taxonomy() is load_taxonomy()


def test_every_facet_has_distinct_direction_labels():
    for facet in load_taxonomy().facets.values():
        assert facet.high_label != facet.low_label
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_facets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.kb.facets'`

- [ ] **Step 4: Implement `engine/kb/version.py` and `engine/kb/facets.py`**

```python
# engine/kb/version.py
"""KB version, read from kb/VERSION. Date-based, e.g. kb-2026.08 (spec §4.3)."""

from __future__ import annotations

import functools
from pathlib import Path

KB_ROOT = Path(__file__).resolve().parents[2] / "kb"


@functools.lru_cache(maxsize=1)
def kb_version(root: Path | None = None) -> str:
    return (root or KB_ROOT).joinpath("VERSION").read_text(encoding="utf-8").strip()
```

```python
# engine/kb/facets.py
"""The fixed facet taxonomy (spec §4.1).

KB trait tags always use direction "high"/"low"; this taxonomy supplies the
human-readable label for each direction, which is what surfaces in the API
response (e.g. direction "gut" rather than "high").
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml

from engine.kb.version import KB_ROOT


@dataclass(frozen=True)
class Facet:
    id: str
    dimension: str
    label: str
    high_label: str
    low_label: str

    def label_for(self, direction: str) -> str:
        return self.high_label if direction == "high" else self.low_label


@dataclass(frozen=True)
class Dimension:
    id: str
    label: str
    order: int
    facets: dict[str, Facet]


@dataclass(frozen=True)
class Taxonomy:
    dimensions: dict[str, Dimension]
    facets: dict[str, Facet]
    tension_threshold: float

    def has(self, facet_id: str) -> bool:
        return facet_id in self.facets

    def get(self, facet_id: str) -> Facet:
        return self.facets[facet_id]

    def dimension_of(self, facet_id: str) -> Dimension:
        return self.dimensions[self.get(facet_id).dimension]


@functools.lru_cache(maxsize=1)
def load_taxonomy(root: Path | None = None) -> Taxonomy:
    path = (root or KB_ROOT) / "facets.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "kb.facets.v1":
        raise ValueError(f"{path}: expected schema kb.facets.v1, got {doc.get('schema')!r}")
    if doc.get("reviewed") is not True:
        raise ValueError(f"{path}: reviewed must be true")

    dimensions: dict[str, Dimension] = {}
    flat: dict[str, Facet] = {}
    for dim_id, dim in doc["dimensions"].items():
        facets: dict[str, Facet] = {}
        for facet_id, spec in dim["facets"].items():
            full_id = f"{dim_id}.{facet_id}"
            facet = Facet(
                id=full_id,
                dimension=dim_id,
                label=spec["label"],
                high_label=spec["high"],
                low_label=spec["low"],
            )
            facets[full_id] = facet
            flat[full_id] = facet
        dimensions[dim_id] = Dimension(
            id=dim_id, label=dim["label"], order=int(dim["order"]), facets=facets
        )

    return Taxonomy(
        dimensions=dimensions,
        facets=flat,
        tension_threshold=float(doc["config"]["tension_threshold"]),
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_facets.py -v`
Expected: PASS, 8 tests

- [ ] **Step 6: Commit**

```bash
git add kb/facets.yaml kb/VERSION engine/kb/ tests/test_facets.py
git commit -m "feat: nine-dimension facet taxonomy with configurable tension threshold"
```

---

### Task 6: Knowledge base loader and validator

**Files:**
- Create: `engine/kb/loader.py`
- Test: `tests/test_kb_loader.py`, `tests/test_kb_validation.py`

**Interfaces:**
- Consumes: `engine.kb.facets.load_taxonomy`, `engine.types.TraitTag`.
- Produces:
  - `engine.kb.loader.KBEntry` — frozen dataclass:
    `key: str, label: str, text: str, tags: tuple[TagSpec, ...]`.
  - `engine.kb.loader.TagSpec` — frozen dataclass: `facet: str, weight: float, direction: str`.
  - `engine.kb.loader.KBFile` — frozen dataclass:
    `system: str, element: str, source: str | None, entries: dict[str, KBEntry]`.
  - `engine.kb.loader.KnowledgeBase` — frozen dataclass with
    `files: dict[tuple[str, str], KBFile]` keyed by `(system, element)`.
    Methods: `entry(system, element, key) -> KBEntry | None`,
    `tags_for(system, element, key) -> list[TraitTag]` (returns `[]` when the key is
    absent — an unmapped element must never crash a profile),
    `text_for(system, element, key) -> str`.
  - `engine.kb.loader.load_kb(root: Path | None = None) -> KnowledgeBase` — cached;
    raises `KBValidationError` on any structural problem.
  - `engine.kb.loader.KBValidationError(Exception)`.

**Validation rules enforced at load (spec §4.3, §10):**
1. `schema: kb.mapping.v1` present.
2. `reviewed: true` present — otherwise refuse to load.
3. `system` and `element` present and non-empty.
4. Every tag's `facet` exists in `kb/facets.yaml`.
5. Every tag's `weight` is in `0..1` and `direction` is `high` or `low`.
6. Every entry has non-empty `label` and `text`.
7. No duplicate `(system, element)` across files.

- [ ] **Step 1: Write the failing loader test**

```python
# tests/test_kb_loader.py
from pathlib import Path

import pytest

from engine.kb.loader import KBValidationError, load_kb

VALID = """\
schema: kb.mapping.v1
system: demo
element: demo_element
reviewed: true
source: "Test fixture"
entries:
  alpha:
    label: "Alpha"
    text: "Direct, pioneering energy; initiates rather than waits."
    tags:
      - {facet: drive.initiative, weight: 0.9, direction: high}
      - {facet: communication.directness, weight: 0.7, direction: high}
"""


def write_kb(tmp_path, name, body):
    """Build a throwaway KB root: real facets.yaml, plus the file under test."""
    (tmp_path / "VERSION").write_text("kb-test", encoding="utf-8")
    facets = Path("kb/facets.yaml").read_text(encoding="utf-8")
    (tmp_path / "facets.yaml").write_text(facets, encoding="utf-8")
    demo_dir = tmp_path / "demo"
    demo_dir.mkdir(exist_ok=True)
    (demo_dir / name).write_text(body, encoding="utf-8")
    # Caches are keyed on root, but tmp_path is unique per test, so no clearing needed.
    return tmp_path


def test_loads_entries_and_tags(tmp_path):
    root = write_kb(tmp_path, "demo.yaml", VALID)
    kb = load_kb(root)
    tags = kb.tags_for("demo", "demo_element", "alpha")
    assert [t.facet for t in tags] == ["drive.initiative", "communication.directness"]
    assert tags[0].weight == 0.9
    assert tags[0].system == "demo"
    assert tags[0].element == "demo_element"
    assert "pioneering" in tags[0].text


def test_unknown_entry_key_returns_no_tags_not_an_error(tmp_path):
    root = write_kb(tmp_path, "demo.yaml", VALID)
    kb = load_kb(root)
    assert kb.tags_for("demo", "demo_element", "not_a_key") == []
    assert kb.entry("demo", "demo_element", "not_a_key") is None


def test_missing_reviewed_flag_is_rejected(tmp_path):
    body = VALID.replace("reviewed: true\n", "")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="reviewed"):
        load_kb(root)


def test_reviewed_false_is_rejected(tmp_path):
    body = VALID.replace("reviewed: true", "reviewed: false")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="reviewed"):
        load_kb(root)


def test_unknown_facet_is_rejected(tmp_path):
    body = VALID.replace("drive.initiative", "drive.not_a_real_facet")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="not_a_real_facet"):
        load_kb(root)


def test_out_of_range_weight_is_rejected(tmp_path):
    body = VALID.replace("weight: 0.9", "weight: 1.4")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="weight"):
        load_kb(root)


def test_bad_direction_is_rejected(tmp_path):
    body = VALID.replace("direction: high", "direction: sideways")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="direction"):
        load_kb(root)


def test_wrong_schema_is_rejected(tmp_path):
    body = VALID.replace("kb.mapping.v1", "kb.mapping.v99")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="schema"):
        load_kb(root)


def test_duplicate_system_element_pair_is_rejected(tmp_path):
    root = write_kb(tmp_path, "demo.yaml", VALID)
    (root / "demo" / "dupe.yaml").write_text(VALID, encoding="utf-8")
    with pytest.raises(KBValidationError, match="duplicate"):
        load_kb(root)


def test_empty_text_is_rejected(tmp_path):
    body = VALID.replace('text: "Direct, pioneering energy; initiates rather than waits."',
                         'text: ""')
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="text"):
        load_kb(root)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_kb_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.kb.loader'`

- [ ] **Step 3: Implement `engine/kb/loader.py`**

```python
"""KB loading and validation.

Every KB file is data, reviewed by a human and frozen (spec §4.3). Loading is
strict on purpose: an unreviewed or malformed file must fail the build, not
silently degrade a profile.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml

from engine.kb.facets import load_taxonomy
from engine.kb.version import KB_ROOT
from engine.types import TraitTag

SCHEMA = "kb.mapping.v1"


class KBValidationError(Exception):
    """Raised when a KB file violates the schema or references an unknown facet."""


@dataclass(frozen=True)
class TagSpec:
    facet: str
    weight: float
    direction: str


@dataclass(frozen=True)
class KBEntry:
    key: str
    label: str
    text: str
    tags: tuple[TagSpec, ...]


@dataclass(frozen=True)
class KBFile:
    system: str
    element: str
    source: str | None
    entries: dict[str, KBEntry]


@dataclass(frozen=True)
class KnowledgeBase:
    files: dict[tuple[str, str], KBFile]

    def entry(self, system: str, element: str, key: str) -> KBEntry | None:
        kb_file = self.files.get((system, element))
        return kb_file.entries.get(key) if kb_file else None

    def tags_for(self, system: str, element: str, key: str) -> list[TraitTag]:
        found = self.entry(system, element, key)
        if found is None:
            return []
        return [
            TraitTag(
                facet=t.facet,
                weight=t.weight,
                direction=t.direction,  # type: ignore[arg-type]
                system=system,
                element=element,
                text=found.text,
            )
            for t in found.tags
        ]

    def text_for(self, system: str, element: str, key: str) -> str:
        found = self.entry(system, element, key)
        return found.text if found else ""


def _validate_and_build(path: Path, doc: dict, taxonomy) -> KBFile:
    def fail(msg: str) -> None:
        raise KBValidationError(f"{path}: {msg}")

    if doc.get("schema") != SCHEMA:
        fail(f"expected schema {SCHEMA}, got {doc.get('schema')!r}")
    if doc.get("reviewed") is not True:
        fail("reviewed must be true — unreviewed KB drafts must not ship")
    system, element = doc.get("system"), doc.get("element")
    if not system or not element:
        fail("system and element are required")

    entries: dict[str, KBEntry] = {}
    for key, raw in (doc.get("entries") or {}).items():
        label, text = (raw.get("label") or "").strip(), (raw.get("text") or "").strip()
        if not label:
            fail(f"entry {key!r}: label must not be empty")
        if not text:
            fail(f"entry {key!r}: text must not be empty")
        specs: list[TagSpec] = []
        for tag in raw.get("tags") or []:
            facet = tag.get("facet")
            if not taxonomy.has(facet):
                fail(f"entry {key!r}: unknown facet {facet!r}")
            weight = float(tag.get("weight", 0.0))
            if not 0.0 <= weight <= 1.0:
                fail(f"entry {key!r}: weight {weight} outside 0..1")
            direction = tag.get("direction")
            if direction not in ("high", "low"):
                fail(f"entry {key!r}: direction must be 'high' or 'low', got {direction!r}")
            specs.append(TagSpec(facet=facet, weight=weight, direction=direction))
        entries[key] = KBEntry(key=key, label=label, text=text, tags=tuple(specs))

    return KBFile(system=system, element=element, source=doc.get("source"), entries=entries)


@functools.lru_cache(maxsize=4)
def load_kb(root: Path | None = None) -> KnowledgeBase:
    kb_root = Path(root or KB_ROOT)
    taxonomy = load_taxonomy(kb_root)
    files: dict[tuple[str, str], KBFile] = {}
    # sorted() so load order — and therefore any error reported — is deterministic.
    for path in sorted(kb_root.rglob("*.yaml")):
        if path.name == "facets.yaml":
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        kb_file = _validate_and_build(path, doc, taxonomy)
        key = (kb_file.system, kb_file.element)
        if key in files:
            raise KBValidationError(f"{path}: duplicate (system, element) pair {key}")
        files[key] = kb_file
    return KnowledgeBase(files=files)
```

Note: `load_taxonomy` is `lru_cache`d on `root`, so passing a test root works.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_kb_loader.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Write the repo-wide KB property test**

This is the spec §10 property test — it runs against the *real* `kb/` and is the
guard that keeps unreviewed or drifting KB files out of the build.

```python
# tests/test_kb_validation.py
"""Property tests over the shipped knowledge base (spec §10)."""

from pathlib import Path

import yaml

from engine.kb.facets import load_taxonomy
from engine.kb.loader import load_kb

KB_DIR = Path("kb")


def kb_files():
    return [p for p in sorted(KB_DIR.rglob("*.yaml")) if p.name != "facets.yaml"]


def test_shipped_kb_loads_clean():
    load_kb()  # raises KBValidationError on any problem


def test_every_shipped_kb_file_is_reviewed():
    for path in kb_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc.get("reviewed") is True, f"{path} is not marked reviewed"


def test_every_tag_references_a_known_facet():
    taxonomy = load_taxonomy()
    kb = load_kb()
    for (system, element), kb_file in kb.files.items():
        for entry in kb_file.entries.values():
            for tag in entry.tags:
                assert taxonomy.has(tag.facet), f"{system}/{element}/{entry.key}: {tag.facet}"


def test_no_kb_text_claims_scientific_validity():
    """Spec §11: no claims of scientific validity in user-visible copy."""
    banned = ("scientifically proven", "clinically", "proven to", "guaranteed")
    kb = load_kb()
    for (system, element), kb_file in kb.files.items():
        for entry in kb_file.entries.values():
            lowered = entry.text.lower()
            for phrase in banned:
                assert phrase not in lowered, f"{system}/{element}/{entry.key}: {phrase!r}"


def test_every_kb_file_declares_a_source():
    """Spec §3.5: interpretive choices are recorded in the KB file header."""
    kb = load_kb()
    for key, kb_file in kb.files.items():
        assert kb_file.source, f"{key} has no source header"
```

- [ ] **Step 6: Run the property test**

Run: `.venv/bin/pytest tests/test_kb_validation.py -v`
Expected: PASS (trivially — `kb/` has only `facets.yaml` and `VERSION` so far;
these tests start guarding real content from Task 7 onward).

- [ ] **Step 7: Commit**

```bash
git add engine/kb/loader.py tests/test_kb_loader.py tests/test_kb_validation.py
git commit -m "feat: strict KB loader with reviewed-flag and facet-reference validation"
```

---

### Task 7: Pythagorean numerology calculator

**Files:**
- Create: `engine/systems/numerology.py`
- Create: `kb/numerology/life_path.yaml`, `kb/numerology/expression.yaml`,
  `kb/numerology/soul_urge.yaml`
- Test: `tests/test_numerology.py`

**Interfaces:**
- Consumes: `engine.types.{BirthInput, InputField, SystemOutput, TraitTag}`,
  `engine.names.normalize`, `engine.kb.loader.load_kb`.
- Produces:
  - `engine.systems.numerology.reduce_number(n: int) -> int` — reduces to a single
    digit, **preserving 11, 22, 33**.
  - `engine.systems.numerology.letter_value(ch: str) -> int` — Pythagorean A=1..Z=8.
  - `engine.systems.numerology.is_vowel(word: str, index: int) -> bool` — the fixed
    Y rule.
  - `engine.systems.numerology.NumerologyCalculator` — implements `SystemCalculator`,
    `key = "numerology"`, `required_inputs = {FULL_NAME, BIRTH_DATE}`.
  - `raw` shape:
    `{"life_path": int, "expression": int, "soul_urge": int, "personality": int,
      "birthday": int, "master_numbers": list[int], "latin_name": str,
      "name_quality": str}`

**Fixed rules (record these in the KB file headers, they are interpretive choices):**
- Pythagorean grid: `A=1 B=2 … I=9, J=1 K=2 … R=9, S=1 T=2 … Z=8`.
- Life Path: reduce month, day, and year *separately* (each preserving masters),
  then sum and reduce once more.
- Vowels are `A E I O U`; **`Y` is a vowel iff neither its immediate predecessor
  nor its immediate successor within the same word is a vowel.** Deterministic and
  documented rather than syllable-based.
- Masters `11, 22, 33` are never reduced. `33` cannot arise from a birthday number.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_numerology.py
import datetime as dt

from engine.systems.numerology import (
    NumerologyCalculator,
    is_vowel,
    letter_value,
    reduce_number,
)
from engine.types import BirthInput, InputField


def make_input(name="Ada Lovelace", date=dt.date(1815, 12, 10), **over):
    base = dict(full_name=name, birth_date=date, birth_time=dt.time(13, 0),
                lat=51.5074, lon=-0.1278, tz="Europe/London", hebrew_name=None)
    base.update(over)
    return BirthInput(**base)


def test_letter_values_follow_the_pythagorean_grid():
    assert letter_value("A") == 1
    assert letter_value("I") == 9
    assert letter_value("J") == 1
    assert letter_value("R") == 9
    assert letter_value("S") == 1
    assert letter_value("Z") == 8


def test_reduce_preserves_master_numbers():
    assert reduce_number(11) == 11
    assert reduce_number(22) == 22
    assert reduce_number(33) == 33
    assert reduce_number(29) == 11  # 2+9=11, stop
    assert reduce_number(48) == 3   # 4+8=12 -> 3
    assert reduce_number(9) == 9


def test_y_is_a_vowel_only_between_consonants():
    assert is_vowel("LYNN", 1) is True     # L-Y-N: both neighbours consonants
    assert is_vowel("MAYA", 2) is False    # A-Y-A: neighbour is a vowel
    assert is_vowel("YARA", 0) is False    # next letter A is a vowel
    assert is_vowel("SKY", 2) is True      # end of word, previous is a consonant


def test_life_path_reduces_components_separately():
    # 1815-12-10 -> month 12->3, day 10->1, year 1815->1+8+1+5=15->6 ; 3+1+6=10->1
    out = NumerologyCalculator().compute(make_input())
    assert out.raw["life_path"] == 1


def test_life_path_preserves_a_master_result():
    # 1979-11-29: month 11 (master, kept), day 29->11 (master, kept),
    # year 1979 -> 26 -> 8 ; 11+11+8 = 30 -> 3
    out = NumerologyCalculator().compute(make_input(date=dt.date(1979, 11, 29)))
    assert out.raw["life_path"] == 3
    assert out.raw["birthday"] == 11
    assert 11 in out.raw["master_numbers"]


def test_expression_soul_urge_and_personality_partition_the_name():
    out = NumerologyCalculator().compute(make_input(name="Ada"))
    # A=1 D=4 A=1 -> expression 6 ; vowels A,A -> 2 ; consonant D -> 4
    assert out.raw["expression"] == 6
    assert out.raw["soul_urge"] == 2
    assert out.raw["personality"] == 4


def test_required_inputs_do_not_include_birth_time():
    calc = NumerologyCalculator()
    assert calc.required_inputs == {InputField.FULL_NAME, InputField.BIRTH_DATE}
    out = calc.compute(make_input(birth_time=None))
    assert out.confidence == 1.0  # numerology is unaffected by missing time


def test_non_latin_name_degrades_confidence_and_notes():
    out = NumerologyCalculator().compute(make_input(name="Владимир Иванов"))
    assert out.confidence < 1.0
    assert out.notes


def test_emits_tags_for_the_life_path_entry():
    out = NumerologyCalculator().compute(make_input())
    facets = {t.facet for t in out.tags}
    assert facets  # at least one mapped facet
    assert all(t.system == "numerology" for t in out.tags)


def test_output_is_deterministic():
    a = NumerologyCalculator().compute(make_input())
    b = NumerologyCalculator().compute(make_input())
    assert a.raw == b.raw
    assert a.tags == b.tags
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_numerology.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.systems.numerology'`

- [ ] **Step 3: Implement `engine/systems/numerology.py`**

```python
"""Pythagorean numerology (spec §3.4).

Pure arithmetic — no ephemeris, no birth time. The interpretive choices (how
Life Path components reduce, when Y is a vowel) are fixed here and documented in
the matching KB file headers so a profile is reproducible from the record alone.
"""

from __future__ import annotations

import datetime as dt

from engine.kb.loader import load_kb
from engine.names import NameQuality, normalize
from engine.types import BirthInput, InputField, SystemOutput, TraitTag

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PYTHAGOREAN = {ch: (i % 9) + 1 for i, ch in enumerate(ALPHABET)}
MASTERS = frozenset({11, 22, 33})
BASE_VOWELS = frozenset("AEIOU")


def letter_value(ch: str) -> int:
    return PYTHAGOREAN.get(ch.upper(), 0)


def reduce_number(n: int) -> int:
    """Digit-sum to a single digit, stopping at a master number."""
    while n > 9 and n not in MASTERS:
        n = sum(int(d) for d in str(n))
    return n


def is_vowel(word: str, index: int) -> bool:
    """Fixed Y rule: Y is a vowel iff both neighbours in the word are consonants."""
    ch = word[index]
    if ch in BASE_VOWELS:
        return True
    if ch != "Y":
        return False
    prev_is_vowel = index > 0 and word[index - 1] in BASE_VOWELS
    next_is_vowel = index + 1 < len(word) and word[index + 1] in BASE_VOWELS
    return not (prev_is_vowel or next_is_vowel)


def _name_sum(latin: str, selector) -> int:
    total = 0
    for word in latin.split(" "):
        for i, ch in enumerate(word):
            if selector(word, i):
                total += letter_value(ch)
    return reduce_number(total)


def life_path(date: dt.date) -> int:
    parts = (
        reduce_number(date.month),
        reduce_number(date.day),
        reduce_number(sum(int(d) for d in str(date.year))),
    )
    return reduce_number(sum(parts))


def personal_year(date: dt.date, year: int) -> int:
    parts = (
        reduce_number(date.month),
        reduce_number(date.day),
        reduce_number(sum(int(d) for d in str(year))),
    )
    return reduce_number(sum(parts))


def personal_month(py: int, month: int) -> int:
    return reduce_number(py + month)


class NumerologyCalculator:
    key = "numerology"
    required_inputs = {InputField.FULL_NAME, InputField.BIRTH_DATE}

    def compute(self, inp: BirthInput) -> SystemOutput:
        name = normalize(inp.full_name, inp.hebrew_name)
        latin = name.latin

        lp = life_path(inp.birth_date)
        expression = _name_sum(latin, lambda w, i: True)
        soul_urge = _name_sum(latin, is_vowel)
        personality = _name_sum(latin, lambda w, i: not is_vowel(w, i))
        birthday = reduce_number(inp.birth_date.day)

        raw = {
            "life_path": lp,
            "expression": expression,
            "soul_urge": soul_urge,
            "personality": personality,
            "birthday": birthday,
            "master_numbers": sorted(
                {n for n in (lp, expression, soul_urge, personality, birthday) if n in MASTERS}
            ),
            "latin_name": latin,
            "name_quality": str(name.latin_quality),
        }

        kb = load_kb()
        tags: list[TraitTag] = []
        for element, value in (
            ("life_path", lp),
            ("expression", expression),
            ("soul_urge", soul_urge),
        ):
            tags.extend(kb.tags_for(self.key, element, str(value)))

        notes = list(name.notes) if name.latin_quality is NameQuality.DERIVED else []
        confidence = 0.7 if name.latin_quality is NameQuality.DERIVED else 1.0

        return SystemOutput(raw=raw, tags=tags, confidence=confidence, notes=notes)
```

- [ ] **Step 4: Write the numerology KB files**

`kb/numerology/life_path.yaml` — all keys `1..9, 11, 22, 33`. First three shown;
write all twelve following the same shape.

```yaml
schema: kb.mapping.v1
system: numerology
element: life_path
reviewed: true
source: >-
  Pythagorean tradition, common contemporary synthesis. Interpretive choices:
  month/day/year reduced separately before summing; master numbers 11/22/33 are
  never reduced.
entries:
  "1":
    label: "Life Path 1"
    text: "A path of initiation and self-direction; comfortable going first, less comfortable being led."
    tags:
      - {facet: drive.initiative, weight: 0.9, direction: high}
      - {facet: relational.autonomy, weight: 0.7, direction: high}
      - {facet: work_energy.role_shape, weight: 0.6, direction: high}
  "2":
    label: "Life Path 2"
    text: "A path of partnership and attunement; reads the room before moving, works best in tandem."
    tags:
      - {facet: drive.initiative, weight: 0.6, direction: low}
      - {facet: relational.autonomy, weight: 0.7, direction: low}
      - {facet: communication.listening, weight: 0.8, direction: high}
      - {facet: emotional.sensitivity, weight: 0.6, direction: high}
  "3":
    label: "Life Path 3"
    text: "A path of expression and play; ideas arrive fast and want an audience."
    tags:
      - {facet: communication.register, weight: 0.9, direction: high}
      - {facet: communication.pace, weight: 0.7, direction: high}
      - {facet: drive.novelty_seeking, weight: 0.7, direction: high}
```

Write `kb/numerology/expression.yaml` and `kb/numerology/soul_urge.yaml` with the
same twelve keys, same structure, and their own `source` headers
(`element: expression`, `element: soul_urge`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_numerology.py tests/test_kb_validation.py -v`
Expected: PASS. The KB validation tests now have real content to check.

- [ ] **Step 6: Commit**

```bash
git add engine/systems/numerology.py kb/numerology/ tests/test_numerology.py
git commit -m "feat: Pythagorean numerology calculator with life path, expression and soul urge KB"
```

---

### Task 8: Chinese zodiac calculator

**Files:**
- Create: `engine/systems/chinese_zodiac.py`
- Create: `kb/chinese_zodiac/animals.yaml`, `kb/chinese_zodiac/elements.yaml`
- Test: `tests/test_chinese_zodiac.py`

**Interfaces:**
- Consumes: `engine.types.*`, `engine.kb.loader.load_kb`, `convertdate.chinese`.
- Produces:
  - `engine.systems.chinese_zodiac.zodiac_year(date: dt.date) -> int` — the Chinese
    year a Gregorian date belongs to, with the boundary at **Chinese New Year**, not
    January 1.
  - `engine.systems.chinese_zodiac.ChineseZodiacCalculator` —
    `key = "chinese_zodiac"`, `required_inputs = {InputField.BIRTH_DATE}`.
  - `raw` shape:
    `{"animal": str, "element": str, "polarity": "yang"|"yin", "zodiac_year": int,
      "new_year_date": "YYYY-MM-DD"}`

**Cycle anchors:** 1984 is Wood Rat, yang — the start of a 60-year cycle.
`animal_index = (year - 4) % 12` over
`Rat Ox Tiger Rabbit Dragon Snake Horse Goat Monkey Rooster Dog Pig`;
`element_index = ((year - 4) % 10) // 2` over `Wood Fire Earth Metal Water`;
polarity is `yang` for even years, `yin` for odd.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chinese_zodiac.py
import datetime as dt

from engine.systems.chinese_zodiac import ChineseZodiacCalculator, zodiac_year
from engine.types import BirthInput, InputField


def make_input(date, **over):
    base = dict(full_name="Test Person", birth_date=date, birth_time=None,
                lat=39.9042, lon=116.4074, tz="Asia/Shanghai", hebrew_name=None)
    base.update(over)
    return BirthInput(**base)


def compute(date):
    return ChineseZodiacCalculator().compute(make_input(date)).raw


def test_anchor_year_1984_is_yang_wood_rat():
    raw = compute(dt.date(1984, 6, 1))
    assert raw == {
        "animal": "Rat",
        "element": "Wood",
        "polarity": "yang",
        "zodiac_year": 1984,
        "new_year_date": "1984-02-02",
    }


def test_january_birthday_belongs_to_the_previous_zodiac_year():
    # CNY 1984 fell on 1984-02-02, so 1984-01-15 is still the 1983 Water Pig year.
    assert zodiac_year(dt.date(1984, 1, 15)) == 1983
    raw = compute(dt.date(1984, 1, 15))
    assert raw["animal"] == "Pig"
    assert raw["element"] == "Water"
    assert raw["polarity"] == "yin"


def test_day_before_and_day_of_new_year_differ():
    before = compute(dt.date(1984, 2, 1))
    on = compute(dt.date(1984, 2, 2))
    assert before["animal"] != on["animal"]
    assert on["animal"] == "Rat"


def test_element_advances_every_two_years():
    assert compute(dt.date(1984, 6, 1))["element"] == "Wood"
    assert compute(dt.date(1985, 6, 1))["element"] == "Wood"
    assert compute(dt.date(1986, 6, 1))["element"] == "Fire"


def test_sixty_year_cycle_repeats():
    a = compute(dt.date(1984, 6, 1))
    b = compute(dt.date(2044, 6, 1)) if dt.date(2044, 6, 1) <= dt.date.today() else None
    older = compute(dt.date(1924, 6, 1))
    assert (older["animal"], older["element"], older["polarity"]) == (
        a["animal"], a["element"], a["polarity"],
    )
    assert b is None or (b["animal"], b["element"]) == (a["animal"], a["element"])


def test_requires_only_birth_date():
    assert ChineseZodiacCalculator().required_inputs == {InputField.BIRTH_DATE}
    out = ChineseZodiacCalculator().compute(make_input(dt.date(1984, 6, 1)))
    assert out.confidence == 1.0
    assert out.notes == []


def test_emits_animal_and_element_tags():
    out = ChineseZodiacCalculator().compute(make_input(dt.date(1984, 6, 1)))
    elements = {t.element for t in out.tags}
    assert elements == {"animals", "elements"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_chinese_zodiac.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.systems.chinese_zodiac'`

- [ ] **Step 3: Implement `engine/systems/chinese_zodiac.py`**

```python
"""Chinese zodiac (spec §3.6).

The year boundary is Chinese New Year, not January 1 — a naive Jan-1 boundary
mislabels roughly one birthday in nine.
"""

from __future__ import annotations

import datetime as dt
import functools

from convertdate import chinese

from engine.kb.loader import load_kb
from engine.types import BirthInput, InputField, SystemOutput, TraitTag

ANIMALS = (
    "Rat", "Ox", "Tiger", "Rabbit", "Dragon", "Snake",
    "Horse", "Goat", "Monkey", "Rooster", "Dog", "Pig",
)
ELEMENTS = ("Wood", "Fire", "Earth", "Metal", "Water")
ANCHOR = 4  # 1984 == Wood Rat, yang; (1984 - 4) % 12 == 0 and % 10 == 0


@functools.lru_cache(maxsize=512)
def new_year(gregorian_year: int) -> dt.date:
    """Gregorian date of Chinese New Year for a given Gregorian year."""
    return dt.date.fromordinal(int(chinese.newyear(gregorian_year)))


def zodiac_year(date: dt.date) -> int:
    return date.year - 1 if date < new_year(date.year) else date.year


def animal_for(year: int) -> str:
    return ANIMALS[(year - ANCHOR) % 12]


def element_for(year: int) -> str:
    return ELEMENTS[((year - ANCHOR) % 10) // 2]


def polarity_for(year: int) -> str:
    return "yang" if year % 2 == 0 else "yin"


class ChineseZodiacCalculator:
    key = "chinese_zodiac"
    required_inputs = {InputField.BIRTH_DATE}

    def compute(self, inp: BirthInput) -> SystemOutput:
        year = zodiac_year(inp.birth_date)
        animal, element = animal_for(year), element_for(year)
        raw = {
            "animal": animal,
            "element": element,
            "polarity": polarity_for(year),
            "zodiac_year": year,
            "new_year_date": new_year(inp.birth_date.year).isoformat(),
        }

        kb = load_kb()
        tags: list[TraitTag] = [
            *kb.tags_for(self.key, "animals", animal.lower()),
            *kb.tags_for(self.key, "elements", element.lower()),
        ]
        return SystemOutput(raw=raw, tags=tags, confidence=1.0, notes=[])
```

- [ ] **Step 4: Write the Chinese zodiac KB files**

`kb/chinese_zodiac/animals.yaml` — twelve keys, lowercase animal names. Three shown;
write all twelve.

```yaml
schema: kb.mapping.v1
system: chinese_zodiac
element: animals
reviewed: true
source: >-
  Common contemporary synthesis of the twelve earthly branches. Year boundary is
  Chinese New Year (lunisolar), computed via convertdate, not January 1.
entries:
  rat:
    label: "Rat"
    text: "Quick, resourceful, alert to opportunity; prefers to move before the room catches up."
    tags:
      - {facet: decision_making.timing, weight: 0.7, direction: high}
      - {facet: drive.novelty_seeking, weight: 0.6, direction: high}
      - {facet: communication.pace, weight: 0.6, direction: high}
  ox:
    label: "Ox"
    text: "Steady and dependable; builds by accumulation rather than by leap."
    tags:
      - {facet: work_energy.rhythm, weight: 0.8, direction: low}
      - {facet: work_energy.structure, weight: 0.7, direction: high}
      - {facet: decision_making.timing, weight: 0.6, direction: low}
  tiger:
    label: "Tiger"
    text: "Bold and confrontational in the useful sense; energised by a challenge worth taking."
    tags:
      - {facet: drive.intensity, weight: 0.8, direction: high}
      - {facet: decision_making.risk_appetite, weight: 0.7, direction: high}
      - {facet: relational.conflict, weight: 0.6, direction: high}
```

`kb/chinese_zodiac/elements.yaml` — five keys: `wood`, `fire`, `earth`, `metal`,
`water`, same structure, own `source` header.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_chinese_zodiac.py tests/test_kb_validation.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add engine/systems/chinese_zodiac.py kb/chinese_zodiac/ tests/test_chinese_zodiac.py
git commit -m "feat: Chinese zodiac with lunisolar new-year boundary"
```

---

### Task 9: Synthesis engine

**Files:**
- Create: `engine/synthesis.py`
- Test: `tests/test_synthesis.py`

**Interfaces:**
- Consumes: `engine.types.TraitTag`, `engine.kb.facets.{Taxonomy, load_taxonomy}`.
- Produces:
  - `engine.synthesis.synthesize(tags: list[TraitTag], confidences: dict[str, float],
    taxonomy: Taxonomy | None = None) -> dict` — the whole synthesis layer.
  - Output shape (matches spec §5.1):

```jsonc
{
  "dimensions": {
    "decision_making": {
      "label": "Decision-making style",
      "summary_tags": ["gut", "needs-recognition", "dislikes-pressure"],
      "facets": [
        {"facet": "decision_making.gut_vs_deliberation", "label": "Gut vs deliberation",
         "score": 0.8, "direction": "gut", "convergence": 0.75,
         "provenance": [{"system": "human_design", "element": "authority", "weight": 0.9}]}
      ],
      "tensions": [
        {"facet": "...", "high": {"direction": "gut", "systems": ["human_design"]},
         "low": {"direction": "deliberation", "systems": ["astrology"]},
         "text": "tension: human_design suggests gut; astrology suggests deliberation"}
      ]
    }
  }
}
```

**Mechanics (spec §4.2), pinned precisely:**
- Each tag's effective weight is `tag.weight * confidences[tag.system]`. A system
  excluded from synthesis contributes confidence `0.0` and therefore nothing.
- For facet `f`: `raw[d] = sum(effective weights with direction d)` for
  `d in (high, low)`; `total = raw.high + raw.low`. If `total == 0`, the facet is
  omitted entirely — never emitted with a fabricated neutral score.
- `score[d] = raw[d] / total`. Dominant direction is the larger; ties resolve to
  `high` (deterministic, documented).
- `facet.score = score[dominant]`, `facet.direction = facet.label_for(dominant)`.
- `convergence = (# distinct systems with ≥1 tag in the dominant direction) /
  (# distinct systems with ≥1 tag on this facet)`.
- **Tension** when `score.high >= threshold and score.low >= threshold`.
- Facets within a dimension sort by `(-score*convergence, facet_id)` — deterministic.
- `summary_tags` = the direction labels of the top 3 facets in that sort order.
- Provenance lists sort by `(system, element)`, weights are the *pre-confidence*
  KB weights so the record shows what the KB said.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_synthesis.py
from engine.kb.facets import load_taxonomy
from engine.synthesis import synthesize
from engine.types import TraitTag

FACET = "decision_making.gut_vs_deliberation"


def tag(system, direction, weight=0.8, facet=FACET, element="e"):
    return TraitTag(facet=facet, weight=weight, direction=direction,
                    system=system, element=element, text="t")


def only_facet(result, facet_id=FACET):
    dim = result["dimensions"]["decision_making"]
    return next(f for f in dim["facets"] if f["facet"] == facet_id)


def test_unanimous_agreement_scores_one_with_full_convergence():
    result = synthesize(
        [tag("astrology", "high"), tag("human_design", "high"), tag("numerology", "high")],
        {"astrology": 1.0, "human_design": 1.0, "numerology": 1.0},
    )
    facet = only_facet(result)
    assert facet["score"] == 1.0
    assert facet["convergence"] == 1.0
    assert facet["direction"] == "gut"  # the facet's high_label


def test_direction_label_comes_from_the_taxonomy_not_high_low():
    result = synthesize([tag("astrology", "low")], {"astrology": 1.0})
    assert only_facet(result)["direction"] == "deliberation"


def test_minority_dissent_lowers_convergence_but_keeps_direction():
    result = synthesize(
        [tag("astrology", "high"), tag("human_design", "high"), tag("numerology", "low", 0.2)],
        {"astrology": 1.0, "human_design": 1.0, "numerology": 1.0},
    )
    facet = only_facet(result)
    assert facet["direction"] == "gut"
    assert facet["convergence"] == round(2 / 3, 6)
    assert facet["score"] < 1.0


def test_opposing_systems_produce_an_explicit_tension():
    result = synthesize(
        [tag("astrology", "high", 0.8), tag("human_design", "low", 0.8)],
        {"astrology": 1.0, "human_design": 1.0},
    )
    dim = result["dimensions"]["decision_making"]
    assert len(dim["tensions"]) == 1
    tension = dim["tensions"][0]
    assert tension["facet"] == FACET
    assert tension["high"]["systems"] == ["astrology"]
    assert tension["low"]["systems"] == ["human_design"]
    assert "astrology" in tension["text"] and "human_design" in tension["text"]


def test_lopsided_split_below_threshold_is_not_a_tension():
    result = synthesize(
        [tag("astrology", "high", 0.9), tag("human_design", "low", 0.1)],
        {"astrology": 1.0, "human_design": 1.0},
    )
    assert result["dimensions"]["decision_making"]["tensions"] == []


def test_zero_confidence_system_contributes_nothing():
    result = synthesize(
        [tag("astrology", "high"), tag("human_design", "low")],
        {"astrology": 1.0, "human_design": 0.0},
    )
    facet = only_facet(result)
    assert facet["score"] == 1.0
    assert [p["system"] for p in facet["provenance"]] == ["astrology"]


def test_facet_with_no_surviving_weight_is_omitted_entirely():
    result = synthesize([tag("human_design", "high")], {"human_design": 0.0})
    assert result["dimensions"] == {}


def test_provenance_records_pre_confidence_kb_weights():
    result = synthesize([tag("astrology", "high", 0.9)], {"astrology": 0.5})
    assert only_facet(result)["provenance"] == [
        {"system": "astrology", "element": "e", "weight": 0.9}
    ]


def test_summary_tags_are_the_top_three_facet_directions():
    tags = [
        tag("astrology", "high", 0.9, FACET),
        tag("astrology", "high", 0.8, "decision_making.timing"),
        tag("astrology", "low", 0.7, "decision_making.pressure_response"),
        tag("astrology", "high", 0.1, "decision_making.risk_appetite"),
    ]
    dim = synthesize(tags, {"astrology": 1.0})["dimensions"]["decision_making"]
    assert dim["summary_tags"] == ["gut", "immediate", "dislikes-pressure"]


def test_output_is_deterministic_regardless_of_tag_order():
    tags = [tag("astrology", "high"), tag("human_design", "high"), tag("numerology", "low", 0.3)]
    conf = {"astrology": 1.0, "human_design": 1.0, "numerology": 1.0}
    assert synthesize(tags, conf) == synthesize(list(reversed(tags)), conf)


def test_threshold_is_read_from_the_taxonomy():
    assert load_taxonomy().tension_threshold == 0.4
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_synthesis.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.synthesis'`

- [ ] **Step 3: Implement `engine/synthesis.py`**

```python
"""The synthesis layer (spec §4.2).

Convergence and tension are the product differentiator: where systems agree we
say so and raise confidence; where they disagree we report the disagreement
instead of averaging it into mush.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from engine.kb.facets import Taxonomy, load_taxonomy
from engine.types import TraitTag

ROUND = 6
SUMMARY_TAG_COUNT = 3


@dataclass
class _FacetAccumulator:
    weights: dict[str, float] = field(default_factory=lambda: {"high": 0.0, "low": 0.0})
    systems: dict[str, set[str]] = field(default_factory=lambda: {"high": set(), "low": set()})
    provenance: list[dict] = field(default_factory=list)

    def add(self, tag: TraitTag, confidence: float) -> None:
        self.weights[tag.direction] += tag.weight * confidence
        self.systems[tag.direction].add(tag.system)
        self.provenance.append(
            {"system": tag.system, "element": tag.element, "weight": tag.weight}
        )


def synthesize(
    tags: list[TraitTag],
    confidences: dict[str, float],
    taxonomy: Taxonomy | None = None,
) -> dict:
    tax = taxonomy or load_taxonomy()
    threshold = tax.tension_threshold

    accumulators: dict[str, _FacetAccumulator] = defaultdict(_FacetAccumulator)
    for tag in tags:
        if not tax.has(tag.facet):
            continue  # KB validation already rejects these; belt and braces at runtime
        confidence = confidences.get(tag.system, 1.0)
        if confidence <= 0.0:
            continue
        accumulators[tag.facet].add(tag, confidence)

    by_dimension: dict[str, list[dict]] = defaultdict(list)
    tensions_by_dimension: dict[str, list[dict]] = defaultdict(list)

    for facet_id, acc in accumulators.items():
        total = acc.weights["high"] + acc.weights["low"]
        if total <= 0.0:
            continue
        score = {d: acc.weights[d] / total for d in ("high", "low")}
        dominant = "high" if score["high"] >= score["low"] else "low"

        contributing = acc.systems["high"] | acc.systems["low"]
        convergence = len(acc.systems[dominant]) / len(contributing)

        facet = tax.get(facet_id)
        by_dimension[facet.dimension].append(
            {
                "facet": facet_id,
                "label": facet.label,
                "score": round(score[dominant], ROUND),
                "direction": facet.label_for(dominant),
                "convergence": round(convergence, ROUND),
                "provenance": sorted(acc.provenance, key=lambda p: (p["system"], p["element"])),
            }
        )

        if score["high"] >= threshold and score["low"] >= threshold:
            high_systems = sorted(acc.systems["high"])
            low_systems = sorted(acc.systems["low"])
            tensions_by_dimension[facet.dimension].append(
                {
                    "facet": facet_id,
                    "high": {"direction": facet.high_label, "systems": high_systems},
                    "low": {"direction": facet.low_label, "systems": low_systems},
                    "text": (
                        f"tension: {', '.join(high_systems)} suggests {facet.high_label}; "
                        f"{', '.join(low_systems)} suggests {facet.low_label}"
                    ),
                }
            )

    dimensions: dict[str, dict] = {}
    for dim_id in sorted(by_dimension, key=lambda d: tax.dimensions[d].order):
        facets = sorted(
            by_dimension[dim_id],
            key=lambda f: (-(f["score"] * f["convergence"]), f["facet"]),
        )
        dimensions[dim_id] = {
            "label": tax.dimensions[dim_id].label,
            "summary_tags": [f["direction"] for f in facets[:SUMMARY_TAG_COUNT]],
            "facets": facets,
            "tensions": sorted(tensions_by_dimension[dim_id], key=lambda t: t["facet"]),
        }

    return {"dimensions": dimensions}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_synthesis.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add engine/synthesis.py tests/test_synthesis.py
git commit -m "feat: synthesis layer with convergence, provenance and explicit tension"
```

---

### Task 10: Orchestrator

**Files:**
- Create: `engine/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `engine.orchestrator.SYSTEM_REGISTRY: dict[str, SystemCalculator]` — the systems
    available in this build. Plan 2 extends this dict; nothing else changes.
  - `engine.orchestrator.build_profile(inp: BirthInput, systems: list[str] | None = None)
    -> dict` — the full profile body, *without* `person_id` (the API layer adds that).
  - `engine.orchestrator.profile_bytes(profile: dict) -> str` — `canonical_json` of
    the profile, the determinism-check surface.

**Profile body shape (spec §5.1), minus `person_id`:**

```jsonc
{
  "versions": {"engine": "1.0.0", "kb": "kb-2026.08"},
  "input_quality": {"birth_time": "exact"|"missing", "hebrew_name": "provided"|"derived"},
  "raw": {"<system>": {..., "confidence": float, "notes": [...]}},
  "synthesis": {"dimensions": {...}},
  "disclaimer": "Reflective and entertainment insight; not medical, psychological, or financial advice."
}
```

**Availability gating:** a calculator whose `required_inputs` are not all in
`inp.available_fields` is *still called* only if it can degrade; the registry entry
declares this. Simpler and stricter rule used here: if `required_inputs` are not
satisfied, the calculator is **skipped**, its raw slot records
`{"available": false, "confidence": 0.0, "notes": [...]}`, and it contributes no
tags. Calculators that merely degrade (astrology without a birth time) list only
what they truly need and handle the rest internally — that is Plan 2's concern.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py
import datetime as dt
import json

from engine import __version__
from engine.canonical import canonical_json
from engine.kb.version import kb_version
from engine.orchestrator import SYSTEM_REGISTRY, build_profile, profile_bytes
from engine.types import BirthInput

DISCLAIMER = (
    "Reflective and entertainment insight; not medical, psychological, or financial advice."
)


def make_input(**over):
    base = dict(full_name="Ada Lovelace", birth_date=dt.date(1815, 12, 10),
                birth_time=dt.time(13, 0), lat=51.5074, lon=-0.1278,
                tz="Europe/London", hebrew_name=None)
    base.update(over)
    return BirthInput(**base)


def test_profile_records_both_versions():
    profile = build_profile(make_input())
    assert profile["versions"] == {"engine": __version__, "kb": kb_version()}


def test_profile_has_a_raw_slot_for_every_registered_system():
    profile = build_profile(make_input())
    assert set(profile["raw"]) == set(SYSTEM_REGISTRY)


def test_profile_carries_the_exact_disclaimer():
    assert build_profile(make_input())["disclaimer"] == DISCLAIMER


def test_synthesis_layer_is_populated():
    profile = build_profile(make_input())
    assert profile["synthesis"]["dimensions"]


def test_input_quality_reports_provided_vs_derived():
    exact = build_profile(make_input())
    assert exact["input_quality"]["birth_time"] == "exact"
    assert exact["input_quality"]["hebrew_name"] == "derived"

    supplied = build_profile(make_input(hebrew_name="אדה"))
    assert supplied["input_quality"]["hebrew_name"] == "provided"

    no_time = build_profile(make_input(birth_time=None))
    assert no_time["input_quality"]["birth_time"] == "missing"


def test_systems_filter_restricts_computation():
    profile = build_profile(make_input(), systems=["numerology"])
    assert set(profile["raw"]) == {"numerology"}


def test_unknown_system_in_filter_is_ignored_not_fatal():
    profile = build_profile(make_input(), systems=["numerology", "not_a_system"])
    assert set(profile["raw"]) == {"numerology"}


def test_profile_is_byte_identical_across_recomputes():
    """Spec §12 acceptance criterion 2."""
    inp = make_input()
    assert profile_bytes(build_profile(inp)) == profile_bytes(build_profile(inp))


def test_profile_body_contains_no_timestamps():
    """Spec §8: no timestamps inside the profile body, or determinism breaks."""
    blob = profile_bytes(build_profile(make_input()))
    assert "computed_at" not in blob
    assert str(dt.date.today().year) not in json.loads(blob)["versions"]["engine"]


def test_profile_json_is_canonical():
    profile = build_profile(make_input())
    assert profile_bytes(profile) == canonical_json(profile)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.orchestrator'`

- [ ] **Step 3: Implement `engine/orchestrator.py`**

```python
"""Profile assembly.

A profile is a pure function of (birth input, engine version, KB version) — no
clock, no randomness, no network (spec §1, §8).
"""

from __future__ import annotations

from engine import __version__
from engine.canonical import canonical_json
from engine.kb.version import kb_version
from engine.names import NameQuality, normalize
from engine.synthesis import synthesize
from engine.systems.chinese_zodiac import ChineseZodiacCalculator
from engine.systems.numerology import NumerologyCalculator
from engine.types import BirthInput, SystemCalculator, SystemOutput, TraitTag

DISCLAIMER = (
    "Reflective and entertainment insight; not medical, psychological, or financial advice."
)

SYSTEM_REGISTRY: dict[str, SystemCalculator] = {
    calc.key: calc
    for calc in (
        NumerologyCalculator(),
        ChineseZodiacCalculator(),
    )
}


def _unavailable(calc: SystemCalculator, missing: set) -> SystemOutput:
    names = ", ".join(sorted(str(m) for m in missing))
    return SystemOutput(
        raw={"available": False},
        tags=[],
        confidence=0.0,
        notes=[f"{calc.key} excluded: required input missing ({names})"],
    )


def build_profile(inp: BirthInput, systems: list[str] | None = None) -> dict:
    selected = (
        list(SYSTEM_REGISTRY)
        if systems is None
        else [k for k in SYSTEM_REGISTRY if k in set(systems)]
    )

    raw: dict[str, dict] = {}
    confidences: dict[str, float] = {}
    all_tags: list[TraitTag] = []

    for key in sorted(selected):
        calc = SYSTEM_REGISTRY[key]
        missing = set(calc.required_inputs) - inp.available_fields
        output = _unavailable(calc, missing) if missing else calc.compute(inp)

        raw[key] = {
            **output.raw,
            "confidence": output.confidence,
            "notes": output.notes,
        }
        confidences[key] = output.confidence
        all_tags.extend(output.tags)

    name = normalize(inp.full_name, inp.hebrew_name)
    return {
        "versions": {"engine": __version__, "kb": kb_version()},
        "input_quality": {
            "birth_time": "exact" if inp.birth_time is not None else "missing",
            "hebrew_name": "provided"
            if name.hebrew_quality is NameQuality.PROVIDED
            else "derived",
            "full_name_script": "latin"
            if name.latin_quality is NameQuality.PROVIDED
            else "transliterated",
        },
        "raw": raw,
        "synthesis": synthesize(all_tags, confidences),
        "disclaimer": DISCLAIMER,
    }


def profile_bytes(profile: dict) -> str:
    """Canonical serialization — the determinism-check surface."""
    return canonical_json(profile)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_orchestrator.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add engine/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: profile orchestrator with availability gating and canonical output"
```

---

### Task 11: Golden fixtures and the determinism property test

**Files:**
- Create: `tests/fixtures/__init__.py`, `tests/fixtures/people.py`
- Create: `tests/golden/` (generated `.json` files)
- Create: `tests/test_golden.py`, `tests/test_determinism.py`
- Create: `kb_tools/regenerate_golden.py`

**Interfaces:**
- Consumes: `engine.orchestrator.build_profile`, `engine.orchestrator.profile_bytes`.
- Produces:
  - `tests.fixtures.people.FIXTURES: dict[str, BirthInput]` — the named edge cases
    from spec §10, reused by Plans 2 and 3.
  - `kb_tools/regenerate_golden.py` — regenerates `tests/golden/*.json`; run
    deliberately after an intentional engine or KB change, never in CI.

**Fixture set (spec §10 requires each of these):** standard full input; no birth
time; southern hemisphere; DST transition; master-number birth date; Chinese New
Year boundary. Pre-1948 Hebrew dates belong to Plan 2's Kabbalah module but the
fixture is defined here so Plan 2 inherits it.

- [ ] **Step 1: Write the fixture set**

```python
# tests/fixtures/people.py
"""Named birth inputs covering the spec §10 edge cases.

These are synthetic people, not real ones — no PII in the repo.
"""

import datetime as dt

from engine.types import BirthInput

FIXTURES: dict[str, BirthInput] = {
    "standard": BirthInput(
        full_name="Ada Lovelace",
        birth_date=dt.date(1815, 12, 10),
        birth_time=dt.time(13, 0),
        lat=51.5074, lon=-0.1278, tz="Europe/London",
        hebrew_name=None,
    ),
    "no_birth_time": BirthInput(
        full_name="Ada Lovelace",
        birth_date=dt.date(1815, 12, 10),
        birth_time=None,
        lat=51.5074, lon=-0.1278, tz="Europe/London",
        hebrew_name=None,
    ),
    "southern_hemisphere": BirthInput(
        full_name="Mira Santos",
        birth_date=dt.date(1988, 7, 4),
        birth_time=dt.time(6, 45),
        lat=-33.8688, lon=151.2093, tz="Australia/Sydney",
        hebrew_name=None,
    ),
    "dst_transition": BirthInput(
        # 2:30am on a US spring-forward date: the local clock never showed 2:30.
        full_name="Casey Rivera",
        birth_date=dt.date(1990, 4, 1),
        birth_time=dt.time(2, 30),
        lat=40.7128, lon=-74.0060, tz="America/New_York",
        hebrew_name=None,
    ),
    "master_numbers": BirthInput(
        full_name="Nina Kaye",
        birth_date=dt.date(1979, 11, 29),
        birth_time=dt.time(11, 11),
        lat=32.0853, lon=34.7818, tz="Asia/Jerusalem",
        hebrew_name=None,
    ),
    "chinese_new_year_boundary": BirthInput(
        full_name="Wei Chen",
        birth_date=dt.date(1984, 1, 15),
        birth_time=dt.time(9, 0),
        lat=39.9042, lon=116.4074, tz="Asia/Shanghai",
        hebrew_name=None,
    ),
    "hebrew_name_supplied": BirthInput(
        full_name="Avraham Cohen",
        birth_date=dt.date(1947, 5, 14),
        birth_time=dt.time(18, 30),
        lat=31.7683, lon=35.2137, tz="Asia/Jerusalem",
        hebrew_name="אברהם כהן",
    ),
}
```

- [ ] **Step 2: Write the golden-fixture test (it will fail: no golden files yet)**

```python
# tests/test_golden.py
"""Golden fixtures: frozen expected output per named person (spec §10).

Regenerate deliberately with `python kb_tools/regenerate_golden.py` after an
intentional engine or KB change, and review the diff — a surprise diff here is
the point of the test.
"""

import json
from pathlib import Path

import pytest

from engine.orchestrator import build_profile, profile_bytes
from tests.fixtures.people import FIXTURES

GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_profile_matches_golden(name):
    path = GOLDEN_DIR / f"{name}.json"
    assert path.exists(), f"missing golden file {path}; run kb_tools/regenerate_golden.py"
    expected = path.read_text(encoding="utf-8").strip()
    actual = profile_bytes(build_profile(FIXTURES[name]))
    assert actual == expected, f"{name}: profile drifted from golden"


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_golden_file_is_canonical_json(name):
    path = GOLDEN_DIR / f"{name}.json"
    blob = path.read_text(encoding="utf-8").strip()
    assert profile_bytes(json.loads(blob)) == blob


def test_no_birth_time_fixture_reports_missing_quality():
    profile = build_profile(FIXTURES["no_birth_time"])
    assert profile["input_quality"]["birth_time"] == "missing"


def test_chinese_new_year_boundary_fixture_uses_the_prior_year():
    profile = build_profile(FIXTURES["chinese_new_year_boundary"])
    assert profile["raw"]["chinese_zodiac"]["zodiac_year"] == 1983


def test_master_number_fixture_surfaces_masters():
    profile = build_profile(FIXTURES["master_numbers"])
    assert profile["raw"]["numerology"]["master_numbers"]
```

- [ ] **Step 3: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_golden.py -v`
Expected: FAIL — `missing golden file .../standard.json`

- [ ] **Step 4: Write and run the golden regenerator**

```python
# kb_tools/regenerate_golden.py
"""Regenerate tests/golden/*.json from the current engine + KB.

Run deliberately, review the diff, commit. Never run this in CI — the whole
value of golden files is that they only change when a human decides they should.
"""

from __future__ import annotations

from pathlib import Path

from engine.orchestrator import build_profile, profile_bytes
from tests.fixtures.people import FIXTURES

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "tests" / "golden"


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name in sorted(FIXTURES):
        blob = profile_bytes(build_profile(FIXTURES[name]))
        (GOLDEN_DIR / f"{name}.json").write_text(blob + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {name}.json ({len(blob)} bytes)")


if __name__ == "__main__":
    main()
```

Run: `.venv/bin/python kb_tools/regenerate_golden.py`

Then **read each generated file** and sanity-check it against the spec before
committing — this is the one-time cross-check step from §10. Confirm:
Ada Lovelace's Life Path is `1`; Wei Chen's `zodiac_year` is `1983`;
Nina Kaye's `master_numbers` is non-empty; the `no_birth_time` profile has
`"birth_time": "missing"`.

- [ ] **Step 5: Run the golden test to verify it passes**

Run: `.venv/bin/pytest tests/test_golden.py -v`
Expected: PASS

- [ ] **Step 6: Write the determinism property test**

```python
# tests/test_determinism.py
"""Spec §8 determinism guard and §12 acceptance criterion 2."""

import time

import pytest

from engine.orchestrator import build_profile, profile_bytes
from tests.fixtures.people import FIXTURES


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_recompute_is_byte_identical(name):
    inp = FIXTURES[name]
    first = profile_bytes(build_profile(inp))
    second = profile_bytes(build_profile(inp))
    assert first == second


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_recompute_across_fresh_caches_is_byte_identical(name):
    """Clearing the KB/taxonomy caches must not change a single byte."""
    from engine.kb.facets import load_taxonomy
    from engine.kb.loader import load_kb

    inp = FIXTURES[name]
    first = profile_bytes(build_profile(inp))
    load_kb.cache_clear()
    load_taxonomy.cache_clear()
    assert profile_bytes(build_profile(inp)) == first


def test_system_selection_order_does_not_affect_output():
    inp = FIXTURES["standard"]
    a = profile_bytes(build_profile(inp, systems=["numerology", "chinese_zodiac"]))
    b = profile_bytes(build_profile(inp, systems=["chinese_zodiac", "numerology"]))
    assert a == b


def test_cold_compute_is_within_the_latency_budget():
    """Spec §12 criterion 1: p95 < 2s cold compute. Generous headroom here."""
    from engine.kb.facets import load_taxonomy
    from engine.kb.loader import load_kb

    load_kb.cache_clear()
    load_taxonomy.cache_clear()
    start = time.perf_counter()
    build_profile(FIXTURES["standard"])
    assert time.perf_counter() - start < 2.0
```

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/pytest -v && .venv/bin/ruff check .`
Expected: all tests PASS, no lint findings. Record the total count in the commit
message so drift is visible.

- [ ] **Step 8: Commit**

```bash
git add tests/fixtures/ tests/golden/ tests/test_golden.py tests/test_determinism.py \
        kb_tools/regenerate_golden.py
git commit -m "test: golden fixtures and determinism property tests"
```

---

### Task 12: KB completeness manifest and the LLM-assisted authoring pipeline

**Files:**
- Create: `kb/manifest.yaml`
- Create: `engine/kb/manifest.py`
- Create: `kb_tools/draft_kb.py`, `kb_tools/style_guide.md`
- Test: `tests/test_kb_completeness.py`

**Interfaces:**
- Consumes: `engine.kb.loader.load_kb`.
- Produces:
  - `engine.kb.manifest.load_manifest(root: Path | None = None) -> dict[tuple[str, str], list[str]]`
    — cached; maps `(system, element)` to the exact list of entry keys that file
    must contain.
  - `kb_tools/draft_kb.py` — the offline **"B assist"** authoring script from spec
    §4.3. Calls the Claude API to draft entries from the manifest + style guide,
    writes them with `reviewed: false`, and **never** commits. A human reviews,
    edits, and flips the flag.

**Why this task exists:** spec §4.3 specifies the authoring pipeline explicitly
("an offline script (`kb_tools/`) calls the Claude API to draft entry files from a
template + style guide; the human reviews, edits, and commits"), and without a
manifest nothing catches a KB file that ships three of twelve sun signs — the
loader validates what is present, not what is missing.

**The two safety properties, both enforced by tests:**
1. `draft_kb.py` writes `reviewed: false`, so a draft can never reach a profile —
   `load_kb()` refuses it (Task 6).
2. `draft_kb.py` is the *only* file in the repo that may import an LLM client, and
   nothing under `engine/` or `api/` may import it.

- [ ] **Step 1: Write `kb/manifest.yaml`**

Declare only the systems this plan ships. Plan 2 appends its four systems as each
is implemented, so the suite stays green at every commit.

```yaml
# kb/manifest.yaml
# The exact entry keys each KB file must contain. The loader validates what is
# present; this catches what is absent.
schema: kb.manifest.v1
files:
  numerology/life_path:
    keys: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "11", "22", "33"]
  numerology/expression:
    keys: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "11", "22", "33"]
  numerology/soul_urge:
    keys: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "11", "22", "33"]
  chinese_zodiac/animals:
    keys: ["rat", "ox", "tiger", "rabbit", "dragon", "snake",
           "horse", "goat", "monkey", "rooster", "dog", "pig"]
  chinese_zodiac/elements:
    keys: ["wood", "fire", "earth", "metal", "water"]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_kb_completeness.py
"""Every KB file declared in the manifest must be complete (spec §4.3, §10)."""

import pytest

from engine.kb.loader import load_kb
from engine.kb.manifest import load_manifest


def test_manifest_loads():
    assert load_manifest()


@pytest.mark.parametrize("key", sorted(load_manifest()))
def test_declared_file_exists(key):
    system, element = key
    assert (system, element) in load_kb().files, f"{system}/{element} is declared but missing"


@pytest.mark.parametrize("key", sorted(load_manifest()))
def test_declared_file_has_every_required_key(key):
    system, element = key
    expected = set(load_manifest()[key])
    actual = set(load_kb().files[key].entries)
    assert expected - actual == set(), f"{system}/{element} is missing {sorted(expected - actual)}"


@pytest.mark.parametrize("key", sorted(load_manifest()))
def test_declared_file_has_no_unexpected_keys(key):
    system, element = key
    expected = set(load_manifest()[key])
    actual = set(load_kb().files[key].entries)
    assert actual - expected == set(), f"{system}/{element} has extra {sorted(actual - expected)}"


@pytest.mark.parametrize("key", sorted(load_manifest()))
def test_every_declared_entry_carries_at_least_one_tag(key):
    """An entry with no tags contributes nothing to synthesis — almost always a
    half-finished draft. The compatibility matrix is the deliberate exception."""
    if key[0] == "compatibility":
        pytest.skip("pair-harmony entries are scored numerically, not tagged")
    for entry in load_kb().files[key].entries.values():
        assert entry.tags, f"{key}/{entry.key} has no tags"


def test_no_shipped_kb_file_is_an_unreviewed_draft():
    """draft_kb.py writes reviewed: false; load_kb refuses those outright, so this
    passing means no draft leaked into the tree."""
    load_kb()


def test_draft_script_is_the_only_llm_client_in_the_repo():
    """Spec §1: no LLM sits in the runtime profile path."""
    import pathlib
    import re

    pattern = re.compile(r"^\s*(import|from)\s+(anthropic|openai)\b", re.M)
    offenders = [
        str(p)
        for root in ("engine", "api", "kb_tools")
        for p in pathlib.Path(root).rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8")) and p.name != "draft_kb.py"
    ]
    assert offenders == []
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_kb_completeness.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.kb.manifest'`

- [ ] **Step 4: Implement `engine/kb/manifest.py`**

```python
"""KB completeness manifest.

The loader (engine/kb/loader.py) validates what a file contains. This declares
what it must contain, so a half-authored file fails the build instead of quietly
producing a thinner profile.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

from engine.kb.version import KB_ROOT


@functools.lru_cache(maxsize=4)
def load_manifest(root: Path | None = None) -> dict[tuple[str, str], list[str]]:
    path = Path(root or KB_ROOT) / "manifest.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "kb.manifest.v1":
        raise ValueError(f"{path}: expected schema kb.manifest.v1, got {doc.get('schema')!r}")

    manifest: dict[tuple[str, str], list[str]] = {}
    for declared, spec in doc["files"].items():
        system, element = declared.split("/", 1)
        manifest[(system, element)] = [str(k) for k in spec["keys"]]
    return manifest
```

- [ ] **Step 5: Run the completeness test and finish the KB files it flags**

Run: `.venv/bin/pytest tests/test_kb_completeness.py -v`
Expected: FAIL, naming exactly which entries Tasks 7 and 8 left unwritten (the
plans there show three of twelve as the shape).

Write the missing entries until this passes. This is the point at which the
numerology and Chinese zodiac KB files become complete.

Run: `.venv/bin/pytest tests/test_kb_completeness.py -v`
Expected: PASS

- [ ] **Step 6: Write the authoring pipeline**

`kb_tools/style_guide.md` — the voice contract every entry must meet. Keep it
short and concrete; it is prompt input, not documentation:

```markdown
# KB entry style guide

Every `text` field is one or two sentences of plain, specific English.

- **Describe the person, not the system.** "Direct, pioneering energy; initiates
  rather than waits." — not "Aries is the first sign of the zodiac."
- **No esoteric jargon in `text`.** The reader may never have heard of a bodygraph.
- **No claims of scientific validity.** No "proven", "clinically", "guaranteed".
- **No flattery and no fortune-telling.** Describe a tendency, not a destiny.
  Never predict health, money, or death.
- **Name the tension.** Where a trait has a cost, say so in the same breath as
  the gift.
- **Tags carry the meaning.** 2–4 tags per entry, weights 0.5–0.9, only facets
  that appear in `kb/facets.yaml`. A tag at 0.9 means this element is one of the
  strongest signals for that facet in the whole system.
```

`kb_tools/draft_kb.py`:

```python
"""Offline LLM-assisted KB drafting — the "B assist" half of spec §4.3.

Drafts are written with `reviewed: false`, which load_kb() refuses. A human
reviews, edits, flips the flag, and commits. Nothing here runs at request time,
and nothing under engine/ or api/ may import this module.

    export ANTHROPIC_API_KEY=...
    python kb_tools/draft_kb.py astrology sun_signs

Writes kb/astrology/sun_signs.draft.yaml — rename it only after review.
"""

from __future__ import annotations

import sys
from pathlib import Path

import anthropic
import yaml

from engine.kb.facets import load_taxonomy
from engine.kb.manifest import load_manifest

ROOT = Path(__file__).resolve().parents[1]
MODEL = "claude-opus-5"

PROMPT = """\
You are drafting entries for a curated identity-mapping knowledge base.

Style guide:
{style_guide}

The facet taxonomy — you may ONLY use these facet ids:
{facets}

Draft one entry for each of these keys in the {system} system, element {element}:
{keys}

Return YAML only, no prose, in exactly this shape:

entries:
  <key>:
    label: "<short human label>"
    text: "<one or two sentences per the style guide>"
    tags:
      - {{facet: <facet id>, weight: <0.5-0.9>, direction: high|low}}
"""


def draft(system: str, element: str) -> Path:
    manifest = load_manifest()
    keys = manifest[(system, element)]
    taxonomy = load_taxonomy()
    style_guide = (ROOT / "kb_tools" / "style_guide.md").read_text(encoding="utf-8")

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        messages=[{
            "role": "user",
            "content": PROMPT.format(
                style_guide=style_guide,
                facets="\n".join(f"- {f.id}: {f.label} "
                                 f"(high={f.high_label}, low={f.low_label})"
                                 for f in sorted(taxonomy.facets.values(), key=lambda x: x.id)),
                system=system,
                element=element,
                keys="\n".join(f"- {k}" for k in keys),
            ),
        }],
    )

    body = yaml.safe_load(message.content[0].text)
    document = {
        "schema": "kb.mapping.v1",
        "system": system,
        "element": element,
        # Deliberately false: an unreviewed draft must never load.
        "reviewed": False,
        "source": f"DRAFT — generated by kb_tools/draft_kb.py using {MODEL}. "
                  "Replace this line with the tradition and interpretive choices "
                  "you are committing to before setting reviewed: true.",
        "entries": body["entries"],
    }

    out = ROOT / "kb" / system / f"{element}.draft.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    return out


if __name__ == "__main__":
    path = draft(sys.argv[1], sys.argv[2])
    print(f"drafted {path}\nReview it, write a real source header, set "
          f"reviewed: true, then rename off .draft.yaml")
```

Add `anthropic>=0.40` to the **dev** extra only, never to `dependencies` — the
runtime must not carry an LLM client:

```toml
dev = ["pytest>=8.0", "pytest-cov>=5.0", "ruff>=0.5", "anthropic>=0.40"]
```

Also extend `engine/kb/loader.py`'s `rglob` skip list so drafts are ignored rather
than fatal while a human is mid-review:

```python
    for path in sorted(kb_root.rglob("*.yaml")):
        if path.name == "facets.yaml" or path.name == "manifest.yaml":
            continue
        if path.name.endswith(".draft.yaml"):
            continue  # in-review draft; load_kb would reject reviewed: false anyway
```

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/pytest -v && .venv/bin/ruff check .`
Expected: all PASS. `test_draft_script_is_the_only_llm_client_in_the_repo` is the
guard that keeps spec §1's "no LLM in the runtime profile path" true as the repo
grows.

- [ ] **Step 8: Commit**

```bash
git add kb/manifest.yaml engine/kb/manifest.py engine/kb/loader.py \
        kb_tools/draft_kb.py kb_tools/style_guide.md \
        tests/test_kb_completeness.py kb/ pyproject.toml
git commit -m "feat: KB completeness manifest and offline LLM-assisted authoring pipeline"
```

---

## Plan 1 Done-When

- [ ] `pytest` passes with zero failures and `ruff check .` is clean.
- [ ] `build_profile()` returns a two-layer profile with `numerology` and
      `chinese_zodiac` raw slots plus a populated `synthesis.dimensions`.
- [ ] The same input produces byte-identical JSON across recomputes and across
      cleared caches.
- [ ] Every shipped KB file has `reviewed: true`, a `source` header, and only
      references facets defined in `kb/facets.yaml`.
- [ ] Every KB file declared in `kb/manifest.yaml` is complete — no missing keys,
      no extra keys, every entry carrying at least one tag.
- [ ] `kb_tools/draft_kb.py` is the only file in the repo importing an LLM client,
      and it writes `reviewed: false`.
- [ ] All seven golden fixtures exist, are canonical JSON, and are human-checked.
- [ ] No network call exists anywhere in `engine/`
      (`grep -rE "requests|httpx|urllib|socket" engine/` returns nothing).

Plan 2 picks up here by adding four calculators to `SYSTEM_REGISTRY` — no changes
to synthesis, KB loading, or orchestration are required.
