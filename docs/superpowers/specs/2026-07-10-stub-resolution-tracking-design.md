# Stub Resolution Tracking + Regression Detection — Design

**Date:** 2026-07-10
**Status:** Approved (brainstorm), pending implementation plan
**Depends on:** Step 0 stub-observability (028c2b56) + Track B Piece 1 accumulation/heatmap (7028b6c5, default-on-under-developer 6a890529)
**Part of:** the stub-hardening effort (see `project_stub_hardening_ratchet` memory)

## Goal

Track which stubs have been **resolved** (implemented) and automatically flag any
that **regress** — i.e. get hit again *after* being marked resolved. Do it inside
the existing `docs/stub_heatmap.md` with two per-stub timestamp slots and one
comparison: **`lastSeenOn > markedResolvedOn` ⇒ regression**. This is a
tool-only change — nothing in the engine changes.

## Context

This supersedes the originally-scoped heavy "Piece 2" (a `stubs_known.txt` ledger
that raises/warns on unledgered stubs, needing a saturated baseline and CI
enforcement). That design rested on an unreachable "saturation" target and a lot
of machinery. Through brainstorming we landed on a lighter, better-targeted idea:
instead of baselining *everything still stubbed* and warning on new stubs, track
*what we've solved* and flag when a solved thing comes back. The regression net
then grows exactly as fast as implementation progress, starts empty (zero upfront
baseline), and reuses the heatmap we already have.

Two mechanisms make it work with **no game-side change**:
- **`lastSeenOn`** is free: every accumulated sidecar run carries a timestamp `t`,
  and we know which stubs each run hit, so `lastSeenOn(owner, attr)` = the newest
  `t` among runs that touched it. Pure tool math over existing `stub_hits.jsonl`.
- **`markedResolvedOn`** is the single human input: a date you write next to a
  stub when you implement it.

The heavy warn-don't-crash + CI ledger is **deferred** (see Out of Scope) — it may
still be worth it later as automated enforcement, but this delivers the
regression signal manually-but-automatically-computed at far lower cost.

## Global Constraints

- **Tool-only.** No change to the engine, the game, or the persistence layer.
  Only `tools/stub_heatmap.py` and the `docs/stub_heatmap.md` format change.
- **Deterministic committed output.** Given the same `stub_hits.jsonl` + the same
  `markedResolvedOn` annotations, regeneration produces a byte-identical file. No
  `now()`; every value derives from the sidecar or the preserved annotations.
- **Preserve human annotations across regeneration.** The generator overwrites the
  file, so it MUST read the existing file first and carry every `markedResolvedOn`
  forward, keyed by the exact `(owner, attr)`. A regeneration must never silently
  drop a resolution.
- **Stdlib only** (`json`, `argparse`, `time`/`datetime`, `collections`).
- **Exact key recovery.** Tables render `owner` and `attr` as **separate columns**
  (not a joined `owner.attr`), so the tool recovers the exact key on re-parse
  even when `attr` contains dots (e.g. `GetWarpCore.GetMaxPower`).

## Data Model

Per unimplemented-attribute stub `(owner, attr)`:
- `total_hits`, `runs_seen`, `M` — as today (Piece 1).
- **`lastSeenOn`** — newest sidecar `t` among runs that hit it, formatted UTC.
  `None` if it appears in no run (e.g. after a sidecar reset).
- **`markedResolvedOn`** — human-authored date (or empty). Persisted in the file.
- **`status`** — derived:
  - **open** — no `markedResolvedOn`. Appears in the roadmap.
  - **resolved** — `markedResolvedOn` set and (`lastSeenOn` is `None` or
    `lastSeenOn <= markedResolvedOn`). Quiet; archived out of the roadmap.
  - **⚠️ regressed** — `markedResolvedOn` set and `lastSeenOn > markedResolvedOn`.
    Flagged prominently.

### Timestamp comparison semantics
- `lastSeenOn` is a datetime (from `t`).
- `markedResolvedOn` accepts `YYYY-MM-DD` (interpreted as **end of that day UTC**,
  23:59:59) or a full `YYYY-MM-DD HH:MM` (UTC). End-of-day for a bare date avoids
  a false positive when a run *earlier the same day* (before you fixed it) hit the
  stub — only hits on a later day count as regressions.
- Regressed iff `lastSeenOn > markedResolvedOn` (both normalized to UTC datetimes).

## Heatmap Format (`docs/stub_heatmap.md`)

Sections, in order:

1. **Header** — runs, date range (from sidecar `t`), distinct/open/resolved counts,
   skipped-malformed count. (As Piece 1, plus resolution counts.)
2. **⚠️ Regressed** (only if non-empty; at the top so it's unmissable):
   `| owner | attr | markedResolvedOn | lastSeenOn | hits |`
3. **Roadmap (open stubs)** — the current "what's left" list:
   `| rank | owner | attr | total hits | coverage | lastSeenOn |`
   Sorted `(-total_hits, owner, attr)`.
4. **Resolved** (archive — kept in the file so annotations persist and future
   regressions are still detectable; decluttered out of the roadmap):
   `| owner | attr | markedResolvedOn | lastSeenOn |`
   Sorted `(markedResolvedOn, owner, attr)`.
5. **Boolean-test call sites** — unchanged from Piece 1. Resolution tracking does
   NOT apply to bool-sites (they are call locations, not methods you implement).

Resolved stubs **remain in the file** (in the Resolved section) rather than
disappearing, precisely so their `markedResolvedOn` survives the next
regeneration and a later regression is still caught.

## How You Use It

1. Play in `--developer` (telemetry auto-accumulates, as today).
2. Regenerate: `uv run python tools/stub_heatmap.py`.
3. Implement a stub from the roadmap. In `docs/stub_heatmap.md`, fill that row's
   `markedResolvedOn` with today's date and commit. (The row moves to Resolved on
   the next regeneration.)
4. Keep playing/regenerating. If a resolved stub gets hit again in a newer run,
   it surfaces in the **⚠️ Regressed** section — your red flag.

## Regeneration Behavior (preserve-on-regen)

On each run, `main`:
1. If `docs/stub_heatmap.md` (or `--out`) exists, parse it and build
   `resolved_map: (owner, attr) -> markedResolvedOn` from every row (across all
   sections) whose `markedResolvedOn` cell is filled. Uses the separate
   owner/attr columns for an exact key. Malformed rows / unparseable dates are
   skipped and counted (reported in the header), never abort the run.
2. Recompute `total_hits`, `runs_seen`, `lastSeenOn` from the sidecar.
3. Compute `status` per stub from `resolved_map` + `lastSeenOn`.
4. Render all sections and write the file.

## Error Handling

- Missing sidecar → "no runs accumulated yet", writes nothing (as Piece 1).
- Missing existing heatmap → `resolved_map` empty; everything is open (first run).
- Malformed table row or unparseable `markedResolvedOn` date → skipped, counted,
  surfaced in the header. A single bad hand-edit cannot silently drop *all*
  annotations or crash the tool.

## Testing

- **`lastSeenOn` math (unit):** synthetic multi-run sidecar → `lastSeenOn` is the
  max `t` among runs hitting each key; `None` when unseen.
- **status classification (unit):** open (no resolved date), resolved
  (`lastSeenOn <= markedResolvedOn` and the `None` case), regressed
  (`lastSeenOn > markedResolvedOn`); same-day-before-fix does NOT regress
  (end-of-day semantics).
- **preserve-on-regen (unit):** given an existing heatmap with `markedResolvedOn`
  cells, regeneration carries them forward by exact `(owner, attr)` key, including
  an `attr` containing dots; a resolved stub stays resolved across regen.
- **exact-key recovery (unit):** two keys that would collide under a dotted join
  (`("A.B","C")` vs `("A","B.C")`) are preserved distinctly via separate columns.
- **malformed tolerance (unit):** a garbled row / bad date is skipped and counted;
  other annotations still preserved.
- **determinism (unit):** same sidecar + same annotations → byte-identical output.
- **regression surfacing (unit):** a resolved stub hit in a run newer than its
  resolved date appears in the ⚠️ Regressed section.
- No game run needed; the full `check_tests.sh` gate stays green.

## Out of Scope (deferred)

- The heavy warn-loud-don't-crash `Unimplemented`/`Inert` ledger + CI enforcement.
  This design gives the regression signal via the heatmap; automated CI
  enforcement is a separable future layer, worth it only if manual regen-and-read
  proves to miss regressions.
- Resolution tracking for bool-sites.
- Any game/engine change (this is entirely offline tooling).
- `markedResolvedOn` auto-stamping (you type the date by hand when you resolve).
