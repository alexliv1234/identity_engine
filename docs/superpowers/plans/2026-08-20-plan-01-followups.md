# Plan 1 — carried-forward items

Recorded at the close of Plan 1 (core engine). Everything here was found by
review, judged non-blocking for Plan 1, and deliberately not fixed in it. Each
item names the point at which it stops being deferrable.

Plan 1 shipped: 22 commits, 217 tests, ruff clean, whole-branch review
merge-ready.

---

## 1. `summary_tags` ranking is still partly degenerate

**Fix before:** Plan 3's `/context` endpoint. Not before merge.

Only 7 of 33 dimensions rank informatively; the other 26 tie and fall through to
alphabetical `facet_id`.

The cause is not the convergence denominator (that was fixed). It is that
`score = weights[dominant] / (weights.high + weights.low)` is exactly `1.0` for
any facet whose tags all point one way — the knowledge-base weight cancels out.
So `score` measures the *purity* of the evidence, never its *mass*. Across the
eight golden fixtures the score distribution is `{1.0: 98, 0.765: 2, 0.545: 1}`.

Within one profile every single-source facet therefore shares an identical sort
key (`1.0 × 1/|applicable|`). **Adding systems in Plan 2 shrinks the ties in
count but not in kind — this does not resolve itself.**

Minimal repair, sort key only, leaving the §5.1 response shape untouched:

```python
key = (-(f["score"] * f["convergence"]), -dominant_weight, f["facet"])
```

where `dominant_weight` is `acc.weights[dominant]` — the confidence-scaled
accumulated weight the engine already computes and that `score` normalises away.
Deterministic, needs no spec decision. Expect one more golden regeneration
(facet order and `summary_tags` order); do it as its own commit.

Why it must precede `/context`: spec §5.2 builds that bundle entirely from the
synthesis layer. A prompt block whose headline traits are chosen alphabetically
is a product defect, not a cosmetic one.

## 2. `ErrorCode.INVALID_INPUT` is not in spec §5.4

**Decision needed — the code currently exceeds the spec.**

`engine.errors.from_validation_error` needs a last-resort code for a validation
failure no rule named. Spec §5.4 enumerates seven codes and has no such case.
Emitting a wrong specific code (e.g. `INVALID_BIRTH_DATE` for a timezone fault)
would defeat the purpose of a machine-readable code, so an eighth was added.

It is unreachable for `BirthInput` today — the field-fallback table covers every
field it declares — so it is a defensive floor, not a code clients will routinely
see. Either amend §5.4 to record it, or decide the fallback must stay inside the
seven. Carry the outcome into Plan 3's brief so its HTTP status is defined
rather than incidental.

## 3. Spec §5.1's example shows a stale convergence value

The example response shows `"convergence": 0.75` on a facet with a single
provenance entry. Under §4.2 as now implemented — share of *applicable* systems
— a single-source facet with six live systems reads ≈0.17. §4.2 is the authority
and the code follows it, but the illustrative example now contradicts it.

Reconcile before Plan 3 publishes the response shape, or integrators will
calibrate against a number the engine never produces.

## 4. `from_validation_error` leaks an unrecognised code prefix

Known codes are stripped from the message correctly. An *unknown* code-shaped
prefix is not: a validator raising `"WEIRD_CODE: something odd"` yields
`code=INVALID_BIRTH_DATE` (correct fallback) but `message="WEIRD_CODE: something
odd"` — the code leaks into prose that is meant to be human-facing. Either strip
any code-shaped prefix unconditionally, or document that only known codes are
stripped.

## 5. Orchestrator collision guard uses `assert`

`engine/orchestrator.py` guards against a calculator naming a raw key that
collides with the engine-owned `confidence` / `notes` keys. `python -O` strips
asserts, turning a loud failure back into silent data loss. It guards a developer
contract rather than user input, so `assert` is defensible — but `raise
ValueError` costs the same and is strictly safer.

---

## Deferred minors still open (11)

Real, none blocking. Triaged during the whole-branch review.

| Area | Item |
|---|---|
| `types.py` | No test for `TraitTag` frozen enforcement |
| `types.py` | `ErrorCode.INVALID_BIRTH_TIME` defined but never raised — Plan 3 owns time parsing |
| `places/lookup.py` | `search()` is exact-match only; Plan 3's typeahead needs prefix matching |
| `names.py` | No direct coverage for digit / punctuation-only / emoji / combining-diacritic inputs |
| `kb/loader.py` | No regression test that an explicit `weight: 0.0` still loads |
| `kb/loader.py` | `match="system"` can't distinguish missing `system` from missing `element` |
| `numerology` | The `personality` number is computed but has no KB file, so it emits no tags |
| `chinese_zodiac` | Test asserts `confidence < 1.0` rather than pinning `0.0` |
| `chinese_zodiac` | `test_sixty_year_cycle_repeats`' 2044 branch is vacuous (future-dated) |
| `orchestrator.py` | `_unavailable(calc, missing: set)` should be `set[InputField]` |
| `kb_tools` | `regenerate_golden.py` manipulates `sys.path`; `python -m` invocation is cleaner |

## Notes for Plan 2

- The seam is clean: a new system is `SYSTEM_REGISTRY` plus KB files plus a
  `kb/manifest.yaml` entry. No core change needed — verified by review.
- `BirthInput.utc_datetime` is the ephemeris entry point and its historical-offset
  behaviour is now pinned to the second.
- The gated path (`confidence=0.0`, `tags=[]`, notes still surfaced in `raw`) is
  proven end to end by the Chinese zodiac's pre-1900 case — that is exactly the
  shape Human Design needs without a birth time.
- `convertdate` was removed from `pyproject.toml` in Plan 1 because nothing
  imported it (the Chinese zodiac uses `lunardate` — see below). Plan 2's
  Kabbalah module will need to re-add it for the Hebrew calendar. This is not an
  oversight.
- **`convertdate` has no `chinese` module.** Plan 2's text still references
  `convertdate.chinese.newyear()` in places; it does not exist in any released
  version. Plan 1 uses `lunardate`, whose table covers `[1900, 2100)`, with dates
  outside the Jan 21 – Feb 20 New Year window resolved analytically so no table
  is needed for ~91.5% of inputs.
- `TraitTag.text` — the knowledge base's interpretive prose (spec §4.2) — is
  validated non-empty, carried through the whole pipeline, and never surfaces in
  a profile. It is the raw material for `/context`. Decide in Plan 2 whether it
  reaches the profile body; retrofitting it into a frozen shape later means a
  version bump.

## Notes for Plan 3

- `engine.errors.from_validation_error` is the tested seam for spec §5.4's
  structured codes. Use it instead of parsing pydantic messages in the API layer,
  as the drafted plan does.
- `?systems=` currently drops unknown names silently; §5.4 suggests it should 422.
- One coverage gap in the determinism suite: every test recomputes in the same
  process, so a process-global state leak would go undetected. One
  subprocess-based recompute test closes the last gap in the product's central
  promise.
