# Open-Question Reconciliation — Design

**Date:** 2026-08-09
**Branch:** `fix/open-question-reconciliation`
**Status:** approved, pending implementation plan

## Why this exists

On 2026-08-09 the `stbc-reference` MCP server came online, giving us direct
clean-room query access to the original engine's behavioural specification. The
first substantive use of it produced a **false confirmed gap**:

`docs/engine/aieditor-ai-surface-and-gaps.md` asserts that
`GetCloakingSubsystem` is "stubbed `None`", disabling cloak doctrines. The MCP
confirmed the entry is real (`ShipClass_GetCloakingSubsystem` @ `0x0060a4b0`),
and that was reported as settling a design question and warranting
implementation. It did not: the method has been fully implemented at
`engine/appc/ships.py:992` for some time, returning the real subsystem. The
prose doc predated the cloaking work and was never updated.

The failure was not the reference. It was **treating a prose gap-doc as evidence
about our own implementation** instead of reading the code. Within the same
session the same class of error appeared repeatedly:

| Item | Doc claims | Reality |
|---|---|---|
| OQ-3.1 | Test BC NIFs through OpenMW's loader | We wrote our own NIF loader; OpenMW is not in the design |
| OQ-3.3 | Character body/head assembly unknown | Shipped — rigid skinning, heads welded by name |
| OQ-8.4 | Need an animation asset manifest | Animation shipped and running |
| OQ-8.3 | `MorphBody` scope unknown | Zero SDK call sites; SWIG binding only |
| heatmap #45/46 | `Planet.GetCloakingSubsystem`, 324 hits | Coverage `1/201`, last seen 2026-07-13; class-based fix documented at `engine/appc/sensor_detection.py:42-50` |
| `CLAUDE.md:38,64` | "21 open questions" | 26 OQ entries actually present in `gap_analysis.md` |
| `gap_analysis.md:723` | "Still open: … **(5)**" | Six items listed on that very line |

Stale documentation that asserts gaps is worse than absent documentation: it
manufactures confident, wrong work. This branch fixes the record, then builds
what genuinely remains.

## Scope decisions

Settled with Mark, 2026-08-09:

1. **Deliverable** — reconcile first, then build what survives. Not docs-only.
2. **Audit breadth** — all gap-analysis OQs and `open_questions.md`; the
   `docs/engine/*.md` files that assert gaps; heatmap rows selected by a
   mechanical triage rule. *Not* a hand-audit of all open heatmap rows.
3. **Build gate** — build **every** survivor in this branch. Sprawl risk was
   raised and accepted; mitigated by an aggressive audit and one commit per
   survivor.

## Approach

**Evidence-first sweep.** Establish current truth from our own code and tests
before consulting anything else. Three sources, each used only for what it is
authoritative about:

| Source | Authoritative for | Cost |
|---|---|---|
| Our code + tests | "Did we build it?" | Cheap — always first |
| `stbc-reference` MCP | "What should it do?" | Expensive — only when behaviour is in question |
| SDK scripts (1,228 files) | "Is anything actually calling this?" | Cheap — decides dead surface vs. real gap |

Rejected alternatives:

- **MCP-first** — front-loads expensive calls onto items already shipped (most
  of them), and fails on OQs the reference does not cover (renderer is out of
  scope by design; audio is likely thin).
- **Build-first** — fastest to visible output, but nothing forces the
  corrections to land. This is how the docs got stale in the first place.

## Phase 1 — Establish truth

For each item, determine current reality from code. Inventory:

- **26 OQs** in `docs/gap_analysis.md` (the doc's own summary says 21).
  6 carry no status marker — OQ-3.1, 3.2, 3.3, 6.1, 8.3, 8.4.
  2 are partial — OQ-2.2 (warp physics), OQ-2.3 (tractor beam physics).
- **4 questions** in `docs/open_questions.md` — all four already closed;
  verify the closures still hold and that the file agrees with `gap_analysis.md`.
- **6 gap-claim docs** in `docs/engine/`: `aieditor-ai-surface-and-gaps.md`,
  `bcs-save-format.md`, `characterclass-reference.md`,
  `damagetool-and-hull-damage-gaps.md`, `nibinaryvoxeldata-format-v3.1.md`,
  `nif-voxel-format.md`. Only their **gap assertions** are in scope — the
  format/RE reference content is not being re-derived.
- **Heatmap candidates** selected by the Phase 1 triage rule below.

### Evidence standard

**No item changes status without a code citation (`file.py:line`) or a passing
test.** Prose docs are never evidence about our own implementation. This is the
specific rule that would have prevented the `GetCloakingSubsystem` error.

Permitted status outcomes:

- **Resolved** — implemented; cite the code or test.
- **Genuinely open** — not implemented; cite the absence and what calls it.
- **Superseded** — the question no longer applies. OQ-3.1 is the archetype: it
  asks whether BC NIFs load under OpenMW's loader, which our own loader made
  moot. Recorded as superseded, *not* silently ticked as answered.
- **Dead surface** — exists in the SWIG binding with zero game-script call
  sites. `CloakingSubsystem_{Get,Set}CloakTime` and
  `CloakingSubsystem_{Get,Set}ShieldDelay` are the template: present in
  `App.py`, called by nothing in 1,228 SDK files. Not gaps; not built.

### Heatmap triage rule

Mechanical selection, then per-row verification:

> **Candidate** = `lastSeenOn` is **at least 14 days before the newest run
> recorded in the heatmap header** (currently 2026-08-06). That is: runs have
> continued, and this stub has stopped being hit.

Run-coverage (`x/201`) is *secondary* evidence — it says how widespread the
stub was, not whether it is still live — so it informs the write-up but never
selects a row on its own. The `Planet.GetCloakingSubsystem` row qualifies on the
primary rule: last seen 2026-07-13, 24 days before the newest run.

The 14-day threshold is a starting heuristic for selecting rows to *read*, not a
resolution criterion — nothing is marked without the code check below. If it
proves to select too much or too little in practice, tune it and note the change
here rather than silently widening the sweep.

Candidates are verified in code before any status change. Verified rows get a
date in `markedResolvedOn`; rows that fail verification stay open with a note
saying why. **No bulk marking** — `markedResolvedOn` arms a regression check,
and a wrongly-dated row silently disarms that detector for that stub.

## Phase 2 — Triage and correct

One commit per gap area, not one commit for the whole phase — a reviewer can
reject the renderer audit while accepting the audio one, and a bad conclusion can
be reverted without unwinding the rest. Corrects `docs/gap_analysis.md`,
`docs/open_questions.md`, the gap assertions in `docs/engine/*.md`, and
`docs/stub_heatmap.md` markers. Reconciles the self-reported counts against
actual contents: `CLAUDE.md`'s "21 open questions" (26 present) and
`gap_analysis.md:723`'s "(5)" (six listed).

**The heatmap header is correct** — 229 open roadmap rows, header says
`Open: 229`, verified by row count. An earlier draft of this spec claimed it was
drifting; that came from counting rows across all four tables instead of the
open roadmap alone. Recorded here because it is the same error class the branch
exists to fix: a confident gap claim made without running the check.

Also records the dead-surface findings with their MCP addresses, so a later
session does not rediscover them as gaps. Includes the cloak accessors and the
fact — from the MCP layout answer — that `g_cloakTime` (`0x8e4e1c`) and
`g_shieldDelay` (`0x8e4e20`) are **class-static globals**, i.e. a single shared
cloak cadence across all ships, not per-instance fields.

`scripts/check_tests.sh` runs on this commit too, to prove no code moved with it.

## Phase 3 — Build survivors

One commit per survivor, ordered most-isolated first, so any single item can be
dropped without unwinding the branch.

**Predicted survivor set** (a prediction, not a plan — Phase 2 decides):

- **OQ-6.1 DynamicMusic transition model** — expected to survive outright.
- **OQ-3.2 damage geometry tagging** — maybe; voxel hull damage may cover it.
- **OQ-2.2 warp-exit velocity** — maybe; currently ⚠️ partial.
- OQ-3.1, 3.3, 8.3, 8.4, 2.3 — expected to close as shipped or superseded.

Each item is implemented test-first (RED → GREEN → REFACTOR).

**Escalation rule:** if a survivor proves subsystem-sized — DynamicMusic
plausibly is, being 13 KB of transition logic plus a crossfade engine we do not
have — stop and report an estimate to Mark rather than deciding alone or letting
it silently swallow the branch. The scope call is his.

## Verification

- Gate is `scripts/check_tests.sh` (builds C++, runs pytest **and** ctest, diffs
  against `tests/known_failures.txt`). Not `run_tests.sh`, which is pytest-only
  and cannot see C++ regressions.
- Baseline is read from `tests/known_failures.txt` at the time of the run, never
  from remembered counts.

**Explicitly not verifiable headlessly:** OQ-6.1 is audio and OQ-3.2 is
renderer-adjacent. Passing tests will not demonstrate that music crossfades or
that damage geometry resolves against real assets. These require Mark to run the
game, and will be reported as needing live verification — never as done.

## Risks

| Risk | Mitigation |
|---|---|
| Shared checkout; concurrent sessions edit the same docs | Branch off `main`; explicit pathspecs only; never `git add -A`; none of the banned restore commands. `.gitignore` and `.claude/` are pre-existing changes from another session and stay untouched |
| Heatmap ratchet disarmed by a wrong date | Per-row code verification; no bulk marking |
| MCP refusals mistaken for corpus silence | Refusals recorded as real outcomes; never rephrased to extract a guess |
| MCP retrieval misfire reads like silence | If an answer does not name the specific class/offset/constant asked about, re-ask naming the spec document before concluding anything is undocumented |
| Branch sprawl from an unbounded survivor set | Aggressive Phase 1 closure; one commit per survivor; escalation rule above |

## Out of scope

- Re-deriving the format/RE content of the `docs/engine/` reference docs — only
  their gap assertions are audited.
- Hand-auditing all open heatmap rows (only triage-rule candidates).
- Implementing dead surface with zero SDK call sites.
- Renderer questions the MCP declines by design.
