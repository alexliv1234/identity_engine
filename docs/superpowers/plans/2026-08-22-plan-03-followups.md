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
