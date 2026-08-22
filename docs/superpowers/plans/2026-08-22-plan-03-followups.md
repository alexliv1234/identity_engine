# Plan 3 follow-ups

Items carried forward from Plan 3 execution, each with the point at which it stops
being deferrable.

## BLOCKING before the first public deployment

### Human review of all 78 Life Path pair cells

`kb/compatibility/life_path_pairs.yaml` ships 78 pair entries. Four are pinned from the
plan; the other 74 were template-generated during Task 6 from a tempo/warmth heuristic
keyed off each Life Path's one-line essence in `kb/numerology/life_path.yaml`.

They are deterministic, structurally valid, and pass the completeness manifest. They are
not curated numerology, and the file originally claimed to be.

**Why this blocks launch rather than waiting:** the product's entire pitch is convergence
across six genuine traditions, reported honestly, with tension surfaced rather than
averaged away. Auto-generated prose presented as curated tradition is the single failure
that most directly contradicts that pitch — more than any bug, because a bug is a mistake
and this would read as a misrepresentation. It is also the cheapest thing on this list to
fix: one domain-literate pass over 78 short cells.

**Context the reviewer surfaced, which the human reader needs up front:** the four pinned
anchors sit *outside* the range the heuristic ever produces. `1-5`=9 and `2-6`=9 are the two
highest values in the whole table, while no derived entry exceeds 8, and most `5-x` derived
pairs score 2-4. So the four "curated" examples do not represent the model that generated the
other 74 — the anchors and the derivation disagree about how generous the scale is. Decide which
is right before reading the rest, or every cell will be judged against the wrong yardstick.

The derivation itself is not incoherent: symmetry holds (one sorted-pair key per unordered pair)
and the labels bucket monotonically into four text tiers. But labels 6 and 7 share identical
boilerplate prose, so the text is coarser than the number it accompanies.

**Stops being deferrable:** before the first paying customer or public deployment.

**What "done" looks like:** a human who knows numerology reads all 78 cells, adjusts the
scores and prose, and the file's curation marker changes from derived to reviewed.

## Deployment

### Ephemeris must be fetched at build time, with a checksum

`de406.bsp` is 287MB, git-ignored and untracked; the repo itself is 2.1MB. It will NOT
arrive with the source on Railway. The Dockerfile needs an explicit fetch into
`engine/ephemeris/data/` with a checksum assertion.

**Why the checksum matters:** without one this fails late and quietly — the app imports
fine, starts fine, passes a health check, and the first profile request is what breaks.

**Stops being deferrable:** at the first Railway deploy.

### Neither CLI is installed

`railway` and `vercel` are both absent, and no `Dockerfile`, `railway.json` or
`vercel.json` exists yet. Both CLIs need interactive browser auth that only the account
owner can perform.

**Stops being deferrable:** at the first deploy.

## Carried from task reviews

### A real file-based KB version bump is untested (from Task 4)

The suite only ever monkeypatches `kb_version`. File-based cache invalidation across a
process restart — editing `kb/VERSION` and restarting — is untested and probably
untestable in CI.

**Stops being deferrable:** before the first production KB bump. Worth one manual check.

### Partial coordinate triples have no dedicated test (from Task 3)

`lat`+`lon` without `tz` correctly falls to `UNKNOWN_PLACE`, but nothing pins that.

**Stops being deferrable:** whenever place handling is next touched.

## Carried from the whole-branch review

### `communication`'s placeholder detection infers state from prose

`engine/compatibility.py` decides whether `communication` is a placeholder with
`if numerology_notes:` — truthiness on a list of note strings.

This is correct **today**, and correct only by coincidence: `numerology_harmony` appends
notes on exactly its two fallback paths, so a non-empty list happens to mean "numerology
fell back". Add one informational numerology note that is not about a fallback, and
`communication` is wrongly marked a placeholder and silently dropped from the headline
`score`.

**Fix:** have `numerology_harmony` return an explicit fallback flag rather than having the
caller infer it from whether prose was emitted. Structured state should never be recovered
from a message list.

**Stops being deferrable:** the next time anyone adds a note to the numerology path.

### `growth` and `score` — verify the class is actually closed

The absent-evidence-as-negative-evidence defect was fixed three times on this branch, each
time one level up from the last: R72 (one compatibility path), R81 (the rescale ranges),
R89 (`growth`'s floor and the headline `score`). Each fix was correct and each left the
same error alive one level up.

**Worth doing once, deliberately:** walk every number the API emits and ask of each one
"could this value mean *nothing was measured* as well as *this was measured*?" That sweep
has never been done as a whole; three separate reviewers each found one instance.

**Stops being deferrable:** before the API is described publicly as reporting convergence
and tension honestly, since that is the claim this defect contradicts.

### `score_partial` and `effect: "unmeasured"` are v1-additive

Both were added late. Neither breaks an existing consumer — one is a new field, the other a
new enum value — but a consumer switching exhaustively on `effect` gains a third case, and
there is no version marker on the response contract.

**Fix:** document both in the README endpoint table (the `effect` enum now is), and decide
whether the v1 response needs an explicit version field before external customers integrate.

**Stops being deferrable:** before the first external integration.
