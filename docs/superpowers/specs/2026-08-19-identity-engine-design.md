# Identity Engine — v1 Design

**Date:** 2026-08-19
**Status:** Approved (brainstorming session with alexliv@gmail.com)
**Repo:** alexliv1234/identity_engine

## 1. Summary

A standalone API platform that takes minimal input about a person — full name, birth
date, birth time (optional), birth place, optional Hebrew name — and produces a
**layered identity profile** built from esoteric systems. Consuming applications
(AI assistants, dating/matching, coaching/wellness, content & commerce) call the API
with per-app keys and use the profile to personalize their product. A small web
playground demonstrates the engine end to end.

The profile has two layers:

- **Raw layer** — each system's native output (natal chart, Human Design bodygraph,
  numerology numbers, gematria values, …) for apps that speak that language.
- **Synthesis layer** — a unified, system-agnostic identity model (traits, drives,
  decision style, …) for apps that don't.

Architecture decision ("A now, B assist"): the engine is **fully deterministic** —
in-house calculators plus a curated, versioned trait-mapping knowledge base (KB).
An LLM is used **offline only**, to draft KB files that a human reviews and freezes
as data. No LLM sits in the runtime profile path. A profile is a pure function of
`(birth input, engine version, KB version)`.

### Decisions log

| Question | Decision |
|---|---|
| Delivery form | API platform (B2B) + demo playground |
| First consumers | AI assistants, dating/matching, coaching/wellness, content & commerce |
| Profile exposure | Layered: raw system outputs + synthesized unified model |
| Systems v1 | Western astrology, Human Design, Numerology, Gene Keys, Chinese zodiac, Jewish numerology/Kabbalah |
| Architecture | Deterministic calculators + curated KB; LLM assists KB authoring offline; LLM narrative is post-v1 |
| Stack | Python 3.12, FastAPI, Pydantic v2, Postgres (SQLite in dev), pytest |

### Non-goals for v1

- Questionnaire-based systems (Enneagram, MBTI) — they break the birth-data-only input model.
- Astrological transits / forecasting (only numerology personal year/month ships in v1).
- LLM-generated narrative prose per profile (first post-v1 stretch; must be cached and versioned).
- Cross-app shared identity / end-user accounts (v1 persons are scoped to the creating app).
- Billing, rate-limit tiers, admin UI.
- Vedic astrology (later: a sidereal configuration of the astrology module).

## 2. Inputs

```
full_name       required   Latin script (numerology); other scripts accepted but flagged
birth_date      required   ISO date; supported range 1800-01-01 .. today
birth_time      optional   local time HH:MM; absence degrades astrology/HD (see §8)
birth_place     required   lat/lon + IANA timezone; a bundled offline city-lookup helper
                           (bundled GeoNames cities dataset) resolves
                           "city, country" → lat/lon/tz with no external calls
hebrew_name     optional   Hebrew script, for gematria; if absent, auto-transliteration
                           of full_name is used and marked lower-confidence
```

No external network calls in the request path (no geocoding APIs, no LLM APIs).

## 3. System modules

Each system is a module implementing one interface:

```python
class SystemCalculator(Protocol):
    key: str                            # "astrology", "human_design", ...
    required_inputs: set[InputField]    # declares needs; engine checks availability
    def compute(self, inp: BirthInput) -> SystemOutput: ...

@dataclass
class SystemOutput:
    raw: dict            # system-native output, JSON-serializable
    tags: list[TraitTag] # contributions to the synthesis layer (see §4)
    confidence: float    # 0..1, degraded when inputs are missing/derived
    notes: list[str]     # human-readable caveats ("birth time missing: no houses")
```

Adding a system post-v1 = new module + KB files. No core changes.

### 3.1 Western astrology

- Ephemeris-based natal chart: Sun–Pluto, Chiron, North Node; Ascendant/MC and
  Placidus houses (only when birth time is present); aspects: conjunction,
  opposition, trine, square, sextile with configurable orbs.
- Raw output: placements (planet → sign, degree, house), aspect list, chart angles.

### 3.2 Human Design

- Built on the same ephemeris core. Two calculations: natal ("personality") and
  design (Sun 88° of solar arc, ~88 days, before birth), mapped to the 64-gate
  I-Ching wheel.
- Raw output: type (Generator / Manifesting Generator / Projector / Manifestor /
  Reflector), strategy, authority, profile (e.g. 3/5), defined/open centers,
  gates and channels, definition type.
- Requires birth time; without it the module returns `confidence ≈ 0` and is
  excluded from synthesis (see §8).

### 3.3 Gene Keys

- Reuses the HD gate math; adds the Activation Sequence: Life's Work, Evolution,
  Radiance, Purpose (natal/design Sun and Earth gates), each with
  shadow/gift/siddhi keywords from the KB.

### 3.4 Numerology (Pythagorean)

- From birth date and Latin name: Life Path, Expression/Destiny, Soul Urge,
  Personality, Birthday number; master numbers 11/22/33 preserved (not reduced).
- Temporal: Personal Year and Personal Month (pure arithmetic — powers the
  `/timing` endpoint).

### 3.5 Jewish numerology / Kabbalah

- Gematria of the Hebrew name (mispar hechrechi / standard values), full and
  reduced; a small curated table of notable equivalences.
- Hebrew birth date via deterministic Jewish-calendar conversion (`pyluach` or
  `convertdate`): Hebrew day/month/year, month meaning, day-of-week significance.
- Sefirot / Tree of Life correspondences via KB mappings.
- Curation note: this module has the least standardized source material of the six;
  its KB files get the most careful human review, and interpretive choices
  (which tradition's correspondences) are recorded in the KB file headers.

### 3.6 Chinese zodiac

- Animal + element from birth year, with the year boundary at Chinese New Year
  (computed via `convertdate`/lunisolar tables, not naive Jan 1).

## 4. Unified Identity Model (synthesis layer)

### 4.1 Dimensions

A fixed facet taxonomy (`kb/facets.yaml`) defines nine dimensions, each with named
facets:

1. **Core essence** — self-image, archetype
2. **Drive & motivation** — what energizes, what depletes
3. **Decision-making style** — e.g. gut-response vs. deliberation; HD authority feeds this heavily
4. **Communication style** — directness, pace, register
5. **Emotional landscape** — processing style, sensitivities
6. **Relational style** — bonding, conflict, needs
7. **Work & energy style** — sustainable rhythm, role shape
8. **Growth edges** — recurring challenges, shadow themes
9. **Life themes & purpose** — long-arc narratives

### 4.2 Mechanics

- Each KB entry maps a system element (e.g. "Sun in Aries", "HD emotional
  authority", "Life Path 7") to weighted **trait tags**:
  `{facet, weight 0..1, direction: high|low}` plus a short interpretive text.
- Facet score = normalized weighted sum of contributing tags, per direction.
- **Provenance**: every facet lists which systems contributed what.
- **Convergence score** per facet = share of applicable systems agreeing in
  direction. High convergence ⇒ high confidence, surfaced to apps.
- **Tension**: when opposing directions on one facet both score ≥ 0.4
  (default; a KB-config tunable), the profile reports it explicitly ("tension: astrology suggests X; Human Design
  suggests Y") instead of averaging it away. Convergence/tension is the engine's
  differentiator — a single-system app cannot produce it.

### 4.3 Knowledge base

- Versioned YAML files under `kb/`, e.g. `kb/astrology/sun_signs.yaml`,
  `kb/human_design/types.yaml`, `kb/kabbalah/sefirot.yaml`.

```yaml
schema: kb.mapping.v1
system: astrology
element: sun_sign
entries:
  aries:
    label: "Sun in Aries"
    text: "Direct, pioneering energy; initiates rather than waits."
    tags:
      - {facet: drive.initiative, weight: 0.9, direction: high}
      - {facet: communication.directness, weight: 0.7, direction: high}
```

- **Authoring pipeline ("B assist")**: an offline script (`kb_tools/`) calls the
  Claude API to draft entry files from a template + style guide; the human reviews,
  edits, and commits. Drafts never ship unreviewed: a `reviewed: true` header field
  is required by KB validation for the build to pass.
- KB versions are date-based (`kb-2026.08`). Engine code is semver. A profile
  records both versions that produced it; bumping the KB triggers lazy recompute
  on next read.

## 5. API surface

Auth: `Authorization: Bearer <api_key>` per app; persons are scoped to the app
that created them.

```
POST   /v1/persons                       create person → computes & stores profile
GET    /v1/persons/{id}/profile          ?layers=raw,synthesis  &systems=astrology,...
GET    /v1/persons/{id}/context          LLM-ready identity context (?format=text|json)
GET    /v1/compatibility?a={id}&b={id}   pairwise compatibility report
GET    /v1/persons/{id}/timing           numerology personal year/month guidance
DELETE /v1/persons/{id}                  full erasure, cascades to profiles
GET    /v1/meta/versions                 engine version, KB version, systems list
```

### 5.1 Profile response (shape sketch)

```jsonc
{
  "person_id": "prs_...",
  "versions": {"engine": "1.0.0", "kb": "kb-2026.08"},
  "input_quality": {"birth_time": "exact", "hebrew_name": "provided"},
  "raw": {
    "astrology": {"placements": [...], "aspects": [...], "confidence": 1.0},
    "human_design": {"type": "Projector", "authority": "Splenic", ...},
    "gene_keys": {...}, "numerology": {...}, "kabbalah": {...}, "chinese_zodiac": {...}
  },
  "synthesis": {
    "dimensions": {
      "decision_making": {
        "summary_tags": ["intuitive", "needs-recognition", "dislikes-pressure"],
        "facets": [
          {"facet": "decision_making.gut_vs_deliberation", "score": 0.8,
           "direction": "gut", "convergence": 0.75,
           "provenance": [{"system": "human_design", "element": "splenic_authority", "weight": 0.9}]}
        ],
        "tensions": []
      }
    }
  },
  "disclaimer": "Reflective and entertainment insight; not medical, psychological, or financial advice."
}
```

### 5.2 `/context` — the AI-assistant bundle

A compact (≤ ~350 tokens) prompt-injectable block, sections: identity snapshot,
communication preferences, decision style, motivation levers, cautions. Text format
for direct prompt injection; JSON format for structured use. Built entirely from
the synthesis layer — no esoteric terminology unless `?vocabulary=esoteric`.

### 5.3 Compatibility v1 (deliberately modest)

- Astrology: inter-chart aspects between Sun, Moon, Venus, Mars, ASC, scored by aspect type.
- Human Design: connection channels (one person's gate completing the other's),
  defined/open center dynamics.
- Numerology: curated Life Path pair-harmony matrix (1–9 + masters).
- Output: overall score 0–100, three dimension scores (connection, communication,
  growth), and a reasons list with per-system provenance. Deeper synastry is post-v1.

### 5.4 Errors

Structured `422/404/401` responses with stable codes: `INVALID_BIRTH_DATE`,
`INVALID_BIRTH_TIME`, `UNKNOWN_TIMEZONE`, `UNKNOWN_PLACE`, `NAME_UNMAPPABLE`,
`PERSON_NOT_FOUND`, `UNAUTHORIZED`.

## 6. Data & persistence

```
apps      id, name, api_key_hash, created_at
persons   id, app_id (FK), full_name, hebrew_name, birth_date, birth_time,
          lat, lon, tz, created_at
profiles  person_id (FK), engine_version, kb_version, profile_json, computed_at
          UNIQUE (person_id, engine_version, kb_version)
```

- Postgres in production, SQLite for dev/tests (SQLAlchemy).
- Privacy: birth data + name is PII. Minimal storage, no third-party sharing;
  `DELETE /persons/{id}` erases person and all derived profiles. Profiles are
  recomputable, so deletion is clean.

## 7. Repository layout

```
identity_engine/
  api/               FastAPI app, routers, auth, error handlers
  engine/            orchestrator + synthesis
  engine/systems/    astrology.py, human_design.py, gene_keys.py,
                     numerology.py, kabbalah.py, chinese_zodiac.py
  engine/ephemeris/  adapter interface + pyswisseph implementation
  kb/                versioned YAML knowledge base + facets.yaml + schema
  kb_tools/          offline LLM-assisted KB authoring scripts
  playground/        static single-page demo (served by FastAPI)
  tests/             golden fixtures, property tests, KB validation
```

## 8. Error handling & degradation rules

- **Missing birth time**: astrology omits houses/angles, moon sign reported as a
  range when it changes sign that day; Human Design (and its Gene Keys derivation)
  excluded from synthesis with an explicit note; per-system `confidence` drives
  synthesis weighting. The engine never fakes precision.
- **Name scripts**: numerology requires Latin (deterministic transliteration via
  a fixed table, e.g. `unidecode`, flagged); gematria requires Hebrew
  (deterministic Latin→Hebrew transliteration table, flagged). `input_quality`
  reports provided vs. derived for each.
- **Dates**: range-checked; historical timezone handling via IANA tzdb.
- **Determinism guard**: identical input + versions ⇒ byte-identical profile JSON
  (stable key ordering, no timestamps inside the profile body).

## 9. Tech stack & licensing decision

- **Python 3.12, FastAPI, Pydantic v2, SQLAlchemy, pytest.** Python chosen for the
  strongest ephemeris ecosystem; astrology, HD, and Gene Keys share one ephemeris core.
- **Ephemeris licensing (flagged, designed around):** `pyswisseph` (Swiss Ephemeris)
  is AGPL — fine for development and the demo. Before any commercial closed-source
  launch: either purchase the Swiss Ephemeris professional license or swap the
  adapter to MIT-licensed Skyfield + JPL ephemeris files. The ephemeris sits behind
  `engine/ephemeris/` adapter interface precisely so this is a swappable
  implementation detail. v1 builds on pyswisseph.
- LLM usage is offline-only (KB authoring via the Claude API in `kb_tools/`);
  model choice happens at implementation time and is not load-bearing for the design.

## 10. Testing

- **Golden fixtures**: known birth data → expected outputs per system, cross-checked
  once against established public calculators (astrology chart services, HD chart
  services, numerology references) and then frozen. Includes edge fixtures:
  no birth time, southern hemisphere, DST transition, pre-1948 Hebrew dates,
  Chinese New Year boundary birthdays, master-number birth dates.
- **Property tests**: determinism (recompute ⇒ identical JSON); every KB tag
  references a facet defined in `facets.yaml`; every KB file passes schema
  validation and has `reviewed: true`.
- **API tests**: auth scoping (app A cannot read app B's persons), erasure
  cascade, degradation paths.

## 11. Positioning & ethics

- Every profile response carries a `disclaimer` field: reflective/entertainment
  insight, not medical, psychological, or financial advice. Consuming apps inherit it.
- No claims of scientific validity in API copy; the product's honesty about
  convergence, tension, and confidence is part of its brand.
- PII handling per §6.

## 12. v1 acceptance criteria

1. `POST /v1/persons` with full input returns a complete six-system layered profile,
   p95 < 2s cold compute, no network calls in the path; cached reads < 100ms.
2. Profiles are byte-identical across recomputes at fixed versions.
3. Golden and property test suites pass.
4. Missing-birth-time degradation behaves per §8.
5. `/compatibility` returns scored report with reasons for any two persons.
6. `/context` returns a ≤350-token text block and JSON variant.
7. Playground page: enter birth data → rendered layered profile; compare two
   people; copy LLM context block.
8. KB v`kb-2026.08` reviewed and frozen; validation enforces review flags.

## 13. Post-v1 roadmap (recorded, not committed)

Astro transits + daily guidance; cached LLM narrative endpoint; webhooks on KB
version bumps; cross-app person identity with end-user consent; Vedic astrology
(sidereal configuration); questionnaire systems; an MCP server exposing
`get_identity_context` so AI agents can consume the engine natively.
