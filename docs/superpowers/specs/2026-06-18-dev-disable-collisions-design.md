# Developer toggle: Disable Collisions

**Date:** 2026-06-18
**Status:** Approved, pending implementation plan

## Goal

Add a developer-only "Disable Collisions" toggle to the **Combat** tab of the
Developer Options pause-menu panel. When On, it suppresses **all** collision
effects — impulse/knockback, positional de-penetration, and collision damage —
for **every** object (player and NPC). Off by default, not persisted across
launches, dev-mode-gated.

This mirrors the existing three Combat-tab toggles (God Mode, 2× Player
Weapons, Disable NPC Shields) in every respect.

## Background

Collisions in Phase 2 are pure Python. The per-frame entry point is
`engine.appc.collisions.tick_collisions(dt, host, ship_instances)`
(`collisions.py:244`), called once per render frame from
`engine/host_loop.py:3385`. It:

1. `_apply_overlay_all(objects, dt)` — advances and **decays** each body's
   `_collision_velocity` knockback overlay.
2. `resolve_collisions(objects, …)` — O(n²) broadphase + narrowphase; every
   collision effect (impulse, de-penetration, `combat.apply_hit` damage) is
   committed inside `_respond_pair` (`collisions.py:97`).

The existing Combat-tab flags live in `engine/dev_combat_cheats.py`, a seam
module that neither the panel nor the combat path import transitively: the
panel writes via setters, `combat.apply_hit` reads via `*_active()` getters,
and each getter ANDs the stored flag with `dev_mode.is_enabled()` as
defense-in-depth.

## Design

### 1. Flag — `engine/dev_combat_cheats.py`

Add a fourth flag alongside the existing three, following the identical shape:

- `_disable_collisions: bool = False` module global.
- `set_disable_collisions(on: bool) -> None`.
- `disable_collisions_active() -> bool` — returns
  `_disable_collisions and dev_mode.is_enabled()`.
- `reset()` also clears `_disable_collisions`.

The module docstring broadens from "the three Developer Options → Combat
toggles" to "the Developer Options → Combat-tab flags" (collisions disabling is
a combat-adjacent debug aid: fly through enemies). No new module is introduced;
the panel already imports this one.

### 2. Gate — `engine/appc/collisions.py`

In `tick_collisions`, after `_apply_overlay_all` but **before**
`resolve_collisions`:

```python
def tick_collisions(dt, host=None, ship_instances=None):
    objects = list(iter_collidables())
    _apply_overlay_all(objects, dt)
    from engine.dev_combat_cheats import disable_collisions_active
    if disable_collisions_active():
        return []
    return resolve_collisions(objects, host=host, ship_instances=ship_instances)
```

Rationale for this seam:

- It is the **single** point that suppresses impulse, de-penetration, and
  damage at once (all three live downstream in `_respond_pair`).
- Existing knockback overlays still **decay** via `_apply_overlay_all`, so any
  bounce already in flight settles naturally instead of freezing.
- When the flag is Off, `disable_collisions_active()` is `False` and the path
  is byte-identical to today. The import is local to the function to avoid any
  import-cycle risk and to keep the hot path's module-load cost out of import
  time.
- Return value matches `resolve_collisions` (a list of collision tuples used by
  tests/debug); `[]` correctly reports "no collisions this frame."

### 3. Panel — `engine/ui/developer_options_panel.py`

Mirror the handling of the existing three controls:

- `__init__` and `open`: add `self._disable_collisions =
  cheats.disable_collisions_active()`.
- `render_payload`: add `_disable_collisions` to the snapshot tuple and
  `"disable_collisions": self._disable_collisions` to the `settings` dict.
- `dispatch_event`: add a `toggle:disable_collisions` case
  (setter-before-local-write, like the others).
- `_focusables`: append `("ctrl", "disable_collisions")` to the combat list.

### 4. JS — `native/assets/ui-cef/js/developer_options.js`

- `_doFocusableList`: push `{kind: 'ctrl', target: 'disable_collisions'}` in the
  `combat` branch.
- `_doRenderCombatBody`: add
  `_doToggleRow('Disable Collisions', 'disable_collisions',
  s.disable_collisions, isFoc('disable_collisions'))`.

## Testing

- **Flag** (`dev_combat_cheats`): set/get round-trip; `disable_collisions_active`
  is `False` when dev mode is off even if the flag is set; `reset` clears it.
- **Gate** (`collisions.tick_collisions`): with the flag active (dev mode on),
  two approaching overlapping bodies produce **no** impulse overlay, **no**
  position change from de-penetration, **no** `apply_hit` call, and
  `tick_collisions` returns `[]`; with the flag inactive the existing behaviour
  is unchanged. Verify a pre-existing overlay still decays when the flag is
  active (overlay path runs before the gate).
- **Panel**: `dispatch_event("toggle:disable_collisions")` flips the flag and
  the local mirror; `render_payload` includes `disable_collisions` in
  `settings`; the new control appears in `_focusables`.

## Non-goals

- No persistence across launches (matches the other dev toggles).
- No separate player-only vs. global distinction — the toggle is global.
- No wiring of the SDK `ProximityManager_SetPlayerCollisionsEnabled` /
  `ShipClass.DisableCollisionDamage` Appc surface; those remain unimplemented.
- No new "Debugging" tab — the toggle lives on the existing Combat tab.

## Files touched

| File | Change |
|---|---|
| `engine/dev_combat_cheats.py` | Add `_disable_collisions` flag, setter, getter, reset clause |
| `engine/appc/collisions.py` | Gate `tick_collisions` on `disable_collisions_active()` |
| `engine/ui/developer_options_panel.py` | Mirror + dispatch + focusable + payload for the new toggle |
| `native/assets/ui-cef/js/developer_options.js` | Focusable + toggle row for the new control |
| tests | Flag, gate, and panel coverage |
