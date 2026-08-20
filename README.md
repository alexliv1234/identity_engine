# Identity Engine

Turns birth data into layered identity profiles.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"    # Windows: .venv\Scripts\pip
.venv/bin/python kb_tools/fetch_ephemeris.py   # Windows: .venv\Scripts\python; one-time, ~300 MB
.venv/bin/pytest                      # Windows: .venv\Scripts\pytest
```

## Determinism guarantee

Identical input plus identical engine/system versions produce byte-identical
profile JSON. See `engine/canonical.py` for the canonical serialization used
to enforce this (stable key ordering, quantized floats, no timestamps in
serialized bodies).

## Offline place lookup

`engine/places/lookup.py` resolves city names to lat/lon/timezone with no
network call, ever. City data © GeoNames (https://www.geonames.org), CC BY 4.0.

Known limitation: `engine/places/data/cities.csv` currently ships as a
curated seed (~94 hand-verified cities) rather than the full GeoNames
`cities15000` extract, since building the full set requires a manual
download (see `kb_tools/build_cities.py`). Running
`python kb_tools/build_cities.py <cities15000.txt> <countryInfo.txt> engine/places/data/cities.csv`
against a real GeoNames extract replaces the seed with the full dataset.

## Ephemeris

`engine/ephemeris/` supplies planetary longitudes and house cusps to every
chart-based system (astrology, Human Design, Gene Keys) behind one adapter
interface (`engine/ephemeris/base.py`), so the underlying library is a
swappable implementation detail — confined to exactly one file
(`skyfield_adapter.py`) and enforced by a test.

**Library and licensing.** The engine uses [Skyfield](https://rhodesmill.org/skyfield/)
(MIT license) over JPL's DE406 ephemeris (public domain, NASA/JPL). This
resolves the licensing question the design spec flagged as open: the
originally-planned `pyswisseph` (Swiss Ephemeris) is AGPL and would have
needed a commercial license before any closed-source launch; Skyfield carries
no such constraint. `pyswisseph` was also impractical to install here — it
ships no binary wheels and needs a C compiler this environment doesn't have —
which is what surfaced the licensing question early rather than later.

**Ephemeris data.** The DE406 kernel (`de406.bsp`, ~300 MB) is vendored
locally but never committed — see `.gitignore`. Fetch it once with:

```bash
.venv/bin/python kb_tools/fetch_ephemeris.py   # Windows: .venv\Scripts\python
```

This is a deliberate, human-run setup step. The adapter loads only from the
local `engine/ephemeris/data/` path and never downloads on cache miss —
consistent with the design spec's "no external network calls in the request
path" rule — so a missing kernel fails loudly at construction time with the
command above, rather than silently reaching the network mid-request.

**Coverage.** DE406 carries the Sun, Moon, and the eight planets (Mercury
through Pluto; Jupiter through Pluto via their barycenters, whose offset from
the planet itself is far below astrological precision) across 3000 BCE-3000
CE. It does **not** include Chiron, which needs a separate small-body SPK
from JPL Horizons — deferred from v1 as a second data dependency and a
second failure mode. It also carries no lunar node model at all: the
`NORTH_NODE` position is computed from the standard Meeus mean-node
polynomial rather than read from a kernel — the *mean* node, not the *true*
(osculating) node, which is the conventional choice in Western tropical
astrology.

**Houses.** Skyfield has no house-system support, so Placidus cusps are
implemented by hand in `skyfield_adapter.py` from closed-form ASC/MC angles
plus an iterative semi-diurnal-arc solve for the four intermediate cusps.
Placidus is mathematically undefined above the polar circle (circumpolar
ecliptic degrees never rise or set); `houses()` raises `HousesUnavailable`
above 66° latitude rather than fabricate a result, consistent with this
project's rule that the engine never fakes precision.
