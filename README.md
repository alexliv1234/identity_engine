# Identity Engine

Turns birth data into layered identity profiles.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"    # Windows: .venv\Scripts\pip
.venv/bin/python kb_tools/fetch_ephemeris.py   # Windows: .venv\Scripts\python; one-time, ~300 MB
.venv/bin/pytest                      # Windows: .venv\Scripts\pytest
```

Spec §6: Postgres in production, SQLite for dev and tests. `pip install .[postgres]`
(or `.[dev]`, which already includes it) is required whenever `IDENTITY_DATABASE_URL`
points at Postgres — a base install alone has no Postgres driver.

## Quickstart: run the API and the playground

With the venv set up and the ephemeris kernel fetched (above), provision a
per-app API key and start the server:

```bash
.venv/bin/python kb_tools/create_app_key.py "Local Dev"   # Windows: .venv\Scripts\python
.venv/bin/uvicorn api.main:app --reload                    # Windows: .venv\Scripts\uvicorn
```

`create_app_key.py` prints the key once, in plaintext — only its SHA-256 hash
is stored (`api/models.py::App.api_key_hash`), so save it now. Then open
<http://127.0.0.1:8000/playground/> and paste the key in: it drives the same
`/v1/*` routes below, entirely client-side, with no bundler or external asset
(`tests/test_playground.py` enforces the no-external-asset property).

## API endpoints

Every route below requires `Authorization: Bearer <api_key>`, except
`/playground/`, which serves static HTML with no auth. Persons are scoped to
the app that created them: another app's person id resolves to `404`, never
`403` — existence of another tenant's person is not disclosed either way
(`api/service.py::load_person`).

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/persons` | Create a person; computes and stores the six-system profile |
| GET | `/v1/persons/{id}/profile` | Cached profile. `?layers=raw,synthesis` and `?systems=astrology,...` narrow the response |
| GET | `/v1/persons/{id}/context` | Token-budgeted LLM bundle. `?format=text\|json`, `?vocabulary=plain\|esoteric` |
| GET | `/v1/persons/{id}/timing` | Numerology personal year/month. `?year=&month=` default to the current UTC date |
| GET | `/v1/compatibility?a={id}&b={id}` | Pairwise report: overall score, three dimension scores, reasons |
| DELETE | `/v1/persons/{id}` | Full erasure, cascades to every derived profile row |
| GET | `/v1/meta/versions` | Engine version, KB version, registered system list |

See `docs/superpowers/specs/2026-08-19-identity-engine-design.md` §5 for
response shapes, and `tests/test_acceptance.py` for one passing test per
v1 acceptance criterion (spec §12).

## Positioning & ethics

Every `/profile`, `/context`, and `/timing` response carries a `disclaimer`
field, verbatim, regardless of which `?layers=` filter was requested:

> Reflective and entertainment insight; not medical, psychological, or
> financial advice.

The API makes no claim of scientific validity for any of the six systems it
layers together (Western astrology, Human Design, Gene Keys, Pythagorean
numerology, Jewish numerology/Kabbalah, the Chinese zodiac). Honesty about
*convergence* — how many applicable systems agree on a facet — and
*tension* — where they disagree — is part of the product, not a caveat
bolted on afterward; see `engine/synthesis.py` and spec §4.2. Birth data and
names are PII: `DELETE /v1/persons/{id}` is a full, cascading erasure (spec
§6), and only the minimum PII needed to recompute a profile is stored
(`api/models.py`).

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

## Declared gaps

Things v1 deliberately does not do, recorded here so nothing is narrowed
silently. Each is named again at the code or knowledge-base site that would
implement it, with the path to closing it.

- **Chiron** is not placed. The vendored DE406 kernel carries only the Sun,
  Moon and the eight planet barycenters; Chiron needs a separate small-body
  SPK from JPL Horizons — a second data dependency and a second failure
  mode. See `engine/ephemeris/base.py` (`Body`) and "Coverage" below.
- **Lunar node** is the *mean* node from the Meeus polynomial, not the true
  (osculating) node read from a kernel. Conventional in Western tropical
  astrology; see "Coverage" below.
- **Day-of-week significance** (spec §3.5) is not implemented. Kabbalah
  emits `raw.hebrew_date.day_of_week` as a bare integer on pyluach's
  convention (**1 = Sunday … 7 = Saturday/Shabbat** — not Python's
  `date.weekday()`, which is 0 = Monday) and nothing interprets it: no
  knowledge-base file, no tags, no contribution to synthesis. Closing it
  means adding `kb/kabbalah/weekdays.yaml` with keys `"1"`–`"7"` and one
  `tags_for` lookup; see `engine/systems/kabbalah.py`'s docstring and
  `kb/kabbalah/hebrew_months.yaml`'s source header.
- **`cities.csv` ships as a curated seed**, not the full GeoNames extract —
  see "Offline place lookup" above.

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

**Scope of that resolution.** The ephemeris blocker is genuinely resolved,
but "licensing is settled" is not true unqualified, and the difference
matters. Two runtime dependencies on the request path are copyleft:

| Dependency  | Licence           | Used for                                    |
|-------------|-------------------|---------------------------------------------|
| `Unidecode` | GPL-2.0-or-later  | Latin transliteration of non-Latin names    |
| `lunardate` | GPL-3.0-or-later  | Chinese New Year year boundary              |

(Both verified from installed package metadata, 2026-08-21.)

For a **hosted API** — the v1 shape — this carries no obligation at all: the
GPL's conditions attach to *distribution*, and running software on your own
server to answer HTTP requests is not distribution. (The AGPL is the licence
that closes that gap, which is exactly why the Swiss Ephemeris question was a
real blocker and these are not.) So spec §9's flagged item is closed for the
launch as designed.

It is **not** closed for any build that ships the engine to someone else: an
on-prem or customer-hosted deployment, an embedded SDK, a desktop or mobile
app, or a container image handed to a third party. Each of those is
distribution, and each would require either releasing the distributed work
under a compatible copyleft licence or replacing both dependencies first.
Neither is hard to replace — `Unidecode` is one fixed lookup table (see
`engine/names.py`, which already owns its own Latin→Hebrew table) and
`lunardate` supplies one lunisolar boundary date per year (see
`engine/systems/chinese_zodiac.py`) — but it is work that has not been done,
and no such build should be shipped on the assumption that it has.

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

**Kernel integrity.** `kb_tools/fetch_ephemeris.py` pins both the kernel's
size and its SHA-256
(`99399a830f8a1c7eeb0c4e6975f3879f7b0086a093f84d95a84f4b5a55b0e36a`) and
refuses to proceed on a mismatch. Size alone cannot tell a substituted or
re-issued kernel from the right one, and since every planetary position comes
from this file, two deployments holding different kernels would produce
different profiles for identical input with nothing detecting it — which is
what the determinism guarantee above is a claim about.

**Houses.** Skyfield has no house-system support, so Placidus cusps are
implemented by hand in `skyfield_adapter.py` from closed-form ASC/MC angles
plus an iterative semi-diurnal-arc solve for the four intermediate cusps.
Placidus is mathematically undefined above the polar circle (circumpolar
ecliptic degrees never rise or set); `houses()` raises `HousesUnavailable`
above 66° latitude rather than fabricate a result, consistent with this
project's rule that the engine never fakes precision.
