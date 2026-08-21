# Plan 2 — carried-forward items

Recorded at the close of Plan 2 (chart systems). Everything here was found by
review, judged non-blocking, and deliberately not fixed. Each names the point at
which it stops being deferrable.

Plan 2 shipped: 17 commits, 485 tests, ruff clean, whole-branch review
merge-ready. All six systems from spec §3 are registered.

See also `2026-08-20-plan-01-followups.md` — its status is updated at the bottom
of this file.

---

## 1. `tzdata` is not pinned, and Plan 2 raised the stakes

**Fix in:** Plan 3's opening task. Cheap.

`skyfield` carries a documented version range and a comment explaining that the
bundled ΔT/leap-second tables feed sidereal time and therefore every house cusp.
`tzdata>=2024.1` has no equivalent comment and no lockfile pins the resolved
version.

Before this plan, timezone-database drift only nudged a continuous value — a cusp
by fractions of a degree — which nobody would notice without diffing decimals.
Now it can flip a **categorical** field: `input_quality.birth_time` is derived
from the installed tzdb, so a rule revision can change `exact` to `ambiguous` for
identical input at identical engine and knowledge-base versions.

The golden suite is detection, not prevention, and only catches this if someone
reruns it in the affected environment right after an upgrade. Nothing forces
that.

Do what was done for skyfield: an explicit range with a comment naming the
mechanism, and ideally an exact pin or a lockfile. The ephemeris kernel is
already SHA-256 pinned; the timezone database is the remaining unpinned input to
a guarantee that claims byte-identical output.

## 2. A near-tie facet's direction can flip, and nothing pins that tension covers it

**Fix in:** whenever `engine/synthesis.py` is next touched. Low priority.

In the `dst_transition` fixture, `core_essence.visibility` scores 0.52 against
0.48. The confidence reduction from Plan 2's DST fix was enough to tip it, so
`direction` flipped from `inward` to `outward`. That is correct arithmetic, not a
bug.

The reassuring part is that the tension mechanism already covers it: the same
dimension emits a tension naming the disagreement, so a consumer reading only
`direction` is not the whole story. But **that coexistence is incidental, not
guaranteed** — no test pins that a near-tie facet also produces a tension entry.

A cheap regression test would make the guarantee real: construct a facet at a
near-even split across two systems and assert both the reported direction *and*
the presence of a tension.

## 3. Spec §3.5's "day-of-week significance" is a declared gap

**Fix in:** whenever the Kabbalah knowledge base is next expanded.

`hebrew_date.day_of_week` ships as an integer (1 = Sunday, 7 = Saturday,
documented) with no knowledge-base file, no tags and no interpretation. The spec
lists it. It is now declared in the module, the KB source header and the README
alongside the Chiron gap, rather than left silent — but it is still absent.

Adding it is a new KB file plus tag emission; it will churn goldens.

## 4. Chiron remains deferred

**Fix in:** post-v1, or whenever a second ephemeris data file is acceptable.

Spec §3.1 lists Chiron among the astrology bodies. The DE406 kernel carries no
minor bodies, so it would need a separate small-body file from JPL Horizons — a
second data dependency and a second failure mode.

Declared in the `Body` enum's docstring, the adapter and the README, with the
path recorded. Adding it later changes the profile shape and forces a golden
regeneration plus an engine version bump.

## 5. Smaller items still open

| Area | Item |
|---|---|
| `skyfield_adapter.py` | `mode: str` cusp-solver parameter is untyped; `Literal["11","12","2","3"]` costs nothing |
| `hebrew_months.yaml` | the `"12"` entry text doesn't note Purim falls in Adar II during a leap year — needs a curator, not a coder |
| `test_six_systems.py` | three `lru_cache`s on the request path aren't cleared before the "cold" latency measurement, making it ~90 ms optimistic against a 5× margin |
| `test_six_systems.py` | the socket test can't structurally distinguish correct local-file loading from an accidental network-capable call whose kernel happened to be cached — defence in depth, honestly labelled |
| `test_six_systems.py` | `test_kabbalah_confidence_is_unaffected_by_missing_birth_time` is a unit test living in an integration file |
| `position()` | evaluates the ephemeris three times per body (value plus two speed samples); 33 evaluations per activation set, twice per profile. Fine at the current margin |
| test files | the AST import-guard helper is duplicated across three test files by convention |

---

## Status of Plan 1's carried-forward items

| Item | Status |
|---|---|
| 1. `summary_tags` ranking degenerate | **Resolved** — Plan 2 Task 0. Informative dimensions went 7/33 → 30/33; the §5.1 response shape was left untouched |
| 2. `INVALID_INPUT` outside spec §5.4 | **Resolved** — spec amended 2026-08-21, dated and marked |
| 3. Spec §5.1's stale `0.75` convergence example | **Resolved** — corrected to `0.166667`, with the denominator explained |
| 4. `from_validation_error` leaked an unknown code prefix | **Resolved** — unconditional strip, tested |
| 5. Orchestrator collision guards used `assert` | **Resolved** — both now `raise ValueError`, verified under real `python -O` |

Plan 1's eleven-item table is **unchanged** — none were closed, none block. Two
are worth doing inside Plan 3 because Plan 3 needs them: `places.search()` prefix
matching for the playground typeahead, and `_unavailable(missing: set)` →
`set[InputField]`.

**One carried question is now closed.** Plan 1 asked whether `TraitTag.text` — the
knowledge base's interpretive prose — should reach the profile body, deferring the
decision to Plan 2. Plan 2 did not decide it, but Plan 3's `/context` design
consumes only the synthesis layer and the taxonomy labels, never the KB text. So
the answer is settled by construction: `text` stays a review and authoring
artefact, the frozen profile shape is safe, and no version bump looms.

---

## Notes for Plan 3

- **Construct the ephemeris at application startup.** `get_ephemeris()` is lazy —
  `skyfield` isn't even imported when `engine.orchestrator` loads. A container
  built without running `kb_tools/fetch_ephemeris.py` will boot healthy, pass a
  health check, and throw `EphemerisDataMissing` on the *first customer chart
  request*. Fail at boot instead. This only exists once there is a server, so no
  task-scoped review would have raised it.
- **`engine.errors.from_validation_error` is the seam** for spec §5.4's structured
  codes. Use it; do not parse pydantic messages in the router.
- **Decide `?systems=` with an unknown name.** Spec §5.4 suggests 422; Plan 3's
  draft test asserts 200-and-ignore. Pick one in the brief. Note the engine-level
  `systems=` parameter was deleted in Plan 2 — filtering is now purely a post-hoc
  projection over a stored full profile, which is the correct model.
- **The profile shape is stable enough to publish.** `build_profile` returns
  exactly `{versions, input_quality, raw, synthesis, disclaimer}`; every facet
  carries exactly `{facet, label, score, direction, convergence, provenance}`, and
  no system registration added a key.
- **`input_quality.birth_time` now has four values**, not two: `exact`, `missing`,
  `ambiguous`, `nonexistent`. API documentation and any client-side enum must
  cover all four.
