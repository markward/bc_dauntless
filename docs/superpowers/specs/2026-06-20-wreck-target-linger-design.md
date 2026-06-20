# Selectable Wreck Linger — Design

**Date:** 2026-06-20
**Status:** Approved, pending implementation plan
**Area:** Phase 2 — ship death / HUD targeting

## Summary

A destroyed ship currently drops off the player's HUD target list the **instant**
its death sequence begins (`target_list_view._snapshot` filters out anything
`IsDying()`/`IsDead()`), then coasts as a wreck for 5 s — visible in space but
**not selectable** — before `ship_death._finish` removes it. So a warp-core
breach (or any death effect) plays while the ship is already un-selectable, and
the player cannot lock onto the wreck to watch it.

This change keeps a destroyed ship **selectable in the target list as a wreck for
10 seconds total** — through the 5 s death throes (so the breach is catchable)
plus a 5 s post-death linger — then removes it. The death sequence, explosion
VFX, coast physics, and the `ET_OBJECT_DESTROYED` / `ship_lifecycle` timing are
all unchanged; only set-removal and target-lock clearing move from 5 s to 10 s.

## Motivation

Reported: "I can't catch it, the target gets removed a bit too quick." Root cause
(confirmed in code) is not the removal timing — it is that the ship leaves the
target list at the *start* of death, not after 5 s, so the breach is never
catchable. The fix makes the wreck remain a valid, selectable target through the
breach and for a short window afterward.

## Behavior

Timeline (T = time since the ship's death sequence began):

| T | Today | After this change |
|---|---|---|
| 0 | Death begins; **dropped from target list**; explosion/breach VFX start | Death begins; **stays in target list as a selectable wreck**; VFX start (unchanged) |
| 0–5 | Coasts, not selectable | Coasts, **selectable**, player lock retained |
| 5 | `_finish`: `SetDead`, clear locks, broadcast `ET_OBJECT_DESTROYED`, remove from set → vanishes | Death-marker: `SetDead`, broadcast `ET_OBJECT_DESTROYED` (`ship_lifecycle.publish_destroyed` fires). **Stays in set + list; locks retained.** |
| 5–10 | — (already gone) | Lingers as a selectable wreck |
| 10 | — | Final removal: clear target locks, remove from set → vanishes |

`ET_OBJECT_DESTROYED` and `ship_lifecycle.publish_destroyed` still fire at the
**5 s** mark, so mission logic and live-ship tracking are unaffected. Only
`_clear_target_locks` and `RemoveObjectFromSet` move to 10 s.

This applies to **every** ship death, not only warp-core breaches — any destroyed
ship now lingers selectable for 10 s. This is intended.

## Components

### 1. `engine/appc/ship_death.py` — two-phase death

Add a constant and a phase field; split the single `_finish` into a death-marker
step and a final-removal step.

- `WRECK_LINGER_DURATION = 5.0` — seconds the dead hull lingers, selectable,
  after the throes complete, before actual removal.
- `_active` entries gain a `phase` key: `"throes"` then `"linger"`.
- `begin(ship)` — unchanged external behavior; registers
  `{"ship": ship, "phase": "throes", "time_left": THROES_DURATION}` and spawns
  the explosion.
- `advance(dt)`:
  - **throes → linger:** when a `"throes"` entry's timer reaches 0, run the
    *death-marker* (`ship.SetDead()`, `_broadcast_destroyed(ship)`) — but **not**
    `_clear_target_locks` and **not** `RemoveObjectFromSet`. Re-arm the same entry
    as `{"phase": "linger", "time_left": WRECK_LINGER_DURATION}`.
  - **linger → removed:** when a `"linger"` entry's timer reaches 0, run the
    *final removal* (`_clear_target_locks(ship)`, then `RemoveObjectFromSet`) and
    prune the entry.
- New predicate `is_targetable_wreck(ship) -> bool` — `True` while `ship` is in
  the `_active` registry (either phase), `False` otherwise. hasattr-free; pure
  registry membership by identity.
- `reset()` — unchanged (clears `_active`).

The current `_finish` (which does all four steps at once) is replaced by the two
steps above. Ordering constraint preserved: `_clear_target_locks` still runs
immediately before `RemoveObjectFromSet` (both now at 10 s), so every firing ship
releases its lock while the handle is still in the set.

### 2. `engine/ui/target_list_view.py` — keep wrecks listed

In `_snapshot` (the filter at lines 200–201), change the include condition from:

```python
if ship is not None and ship is not player \
        and not _out_of_action(ship):
```

to:

```python
if ship is not None and ship is not player \
        and (not _out_of_action(ship) or is_targetable_wreck(ship)):
```

importing `is_targetable_wreck` alongside `_out_of_action` from
`engine.appc.ship_death`. A wreck row still builds normally; when the cascade has
zeroed every subsystem the `subsystems` tuple is simply empty (the ship row is
appended regardless of subsystem rows), so the wreck appears as a selectable
ship-level entry.

No change to `_reconcile_subsystem_lock` — subsystem lock handoff already
reconciles each tick and is independent of ship-level listing.

## Data flow / interactions

- **Renderer:** the ship stays in the set for 10 s, so the existing render loop
  keeps drawing it as a dark (emissive 0) tumbling wreck for the full window. No
  renderer change.
- **Re-trigger safety:** `begin` is idempotent (a ship already dying/dead is
  ignored), the warp-core breach is single-fire, and the cascade fires once — so
  re-damaging a lingering wreck cannot restart death, re-breach, or re-cascade.
- **Lock retention:** because `_clear_target_locks` moves to 10 s, the player's
  lock (and tracking camera/reticle, which follow `GetTarget`) stay on the wreck
  through the whole window; they release at final removal.
- **`ship_lifecycle`:** `publish_destroyed` still fires at 5 s (via `SetDead`), so
  UI panels tracking live ships drop the wreck at 5 s — independent of the target
  list, which is driven by set membership + the new filter.

## Testing

### `tests/unit/test_ship_death.py` (extend)
- After `THROES_DURATION`: `IsDead() == 1`, `ET_OBJECT_DESTROYED` was broadcast,
  the ship is **still in the set** (not removed), and `is_targetable_wreck(ship)`
  is `True`.
- After `THROES_DURATION + WRECK_LINGER_DURATION`: the ship **is removed** from
  the set, target locks are cleared, and `is_targetable_wreck(ship)` is `False`.
- The throes→linger transition does not clear locks early (a lock held on the
  ship at the 5 s mark is still present until 10 s).
- `is_targetable_wreck` is `False` for a ship never passed to `begin`.
- Idempotent `begin` and `reset` behavior preserved (existing tests still pass).

### `tests/unit/` for the target-list filter
- A ship in the `ship_death` wreck window (dead, in `_active`) is **included** in
  the snapshot rows; a ship that has passed final removal is **excluded**. (Use a
  focused test that drives the `_out_of_action`/`is_targetable_wreck` predicate
  combination, mirroring whatever fixture style the existing
  `target_list_view` tests use; if none exists, test the predicate-level filter
  directly.)

## Non-goals

- No "(destroyed)" / "wreck" label on the target-list row (offered, deferred).
- No change to death VFX, coast physics, or the 5 s throes duration.
- No change to `ET_OBJECT_DESTROYED` / `ship_lifecycle` timing (stays at 5 s).
- No per-ship-class variation of the linger duration (fixed 5 s; tunable
  constant).

## Affected files

| File | Change |
|---|---|
| `engine/appc/ship_death.py` | Two-phase death; `WRECK_LINGER_DURATION`; `is_targetable_wreck`; split death-marker / final-removal |
| `engine/ui/target_list_view.py` | Filter keeps `is_targetable_wreck` ships listed |
| `tests/unit/test_ship_death.py` | Phase/linger/predicate tests |
| `tests/unit/test_target_list_wreck.py` (or existing target-list test) | Wreck stays listed until final removal |
