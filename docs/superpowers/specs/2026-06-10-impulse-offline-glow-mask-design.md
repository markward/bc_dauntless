# Impulse-engine offline glow mask — design

**Date:** 2026-06-10
**Status:** Approved (design); ready for implementation plan.

## Goal

When a ship's impulse engine subsystem goes offline, visually "turn off" the
ship's glow (the emissive glow-map term) within the radius of the engine
hardpoint, so a player can read engine status from the hull itself — the aft
impulse glow goes dark when the engine is disabled or destroyed.

## Decisions (locked)

- **Scope:** all ships (player and NPC), not just the player.
- **Visual treatment:** hard cutoff — glow is fully zeroed inside the sphere,
  hard edge, no temporal fade.
- **Trigger:** `engine.appc.subsystems._is_offline()` — the project's single
  source of truth (subsystem `IsDisabled()` OR `IsDestroyed()`). Consistent
  with the existing impulse flight-degradation gating.

## Background — how glow renders today

The whole ship's glow is a single texture stage (`StageSlot::Glow`) sampled
per-fragment in `native/src/renderer/shaders/opaque.frag`. The final color adds
`glow.rgb * glow.a * gf`, where `gf` (`glow_flicker`) is a body-space multiplier
already driven by the damage-decal system (the "solid dark" path zeroes glow
inside a sphere — direct precedent). There is no per-engine geometry to toggle;
the mask must be a shader-space region test.

Subsystem mount points come from
`engine.appc.subsystems.subsystem_world_position(sub, ship)`, which returns the
**world-space** mount (`ship_loc + R · local`, column-vector R, no scale). This
is already validated — the Ship Property Viewer pins land on the correct
subsystems using it. `sub.GetRadius()` returns the hardpoint radius in the same
world (GU) units (Galaxy impulse: pos `(0, -0.98, -0.45)`, radius `0.25` GU ≈
44 m).

Working in **world space** (testing against `v_position_ws`) avoids any
dependence on `u_ship_world_inv` or the per-ship render scale `s` — we feed the
shader exactly what `subsystem_world_position` + `GetRadius()` produce.

## Architecture

A dedicated, per-instance, world-space "glow-kill sphere" set, parallel to (not
folded into) the damage-decal ring.

### 1. Offline-mount collection (Python)

New pure helper next to the existing impulse logic in
`engine/appc/subsystems.py`:

```
offline_impulse_mounts(ies, ship) -> list[(center_world, radius)]
```

- `ies` is the master `ImpulseEngineSubsystem` (or `None`).
- `ies is None` → `[]`.
- master `_is_offline()` → one sphere:
  `(subsystem_world_position(ies, ship), ies.GetRadius())`.
- else, for each child pod `c` with `_is_offline(c)` → one sphere
  `(subsystem_world_position(c, ship), c.GetRadius())`.
- all online / no offline pods → `[]`.

Current hardpoints define a single master impulse subsystem (no child pods), so
this normally yields 0 or 1 sphere; the child-pod branch is future-proofing that
costs nothing.

The helper is headless and unit-testable with no renderer.

### 2. Data path (host loop → renderer)

- `engine/host_loop.py` calls `offline_impulse_mounts(...)` per ship instance
  each frame (cheap: usually 0–1 spheres) and pushes the result via a new
  renderer binding.
- `engine/renderer.py` wrapper: `set_engine_glow_kills(iid, spheres)` where
  `spheres` is a list of `(x, y, z, radius)` world-space tuples. Guarded with
  `hasattr(_h, "set_engine_glow_kills")` so it silently no-ops headless / without
  the native host (matches the existing `r.*` convention).
- Host stores the per-instance sphere set with the same lifetime as the decal
  ring.

### 3. Shader

- `native/src/renderer/frame.cc` sets two new uniforms per draw:
  `u_glow_kill_count` (int) and `u_glow_kill[N]` (vec4 = `center_ws.xyz, radius`),
  with `N` small (4). `count == 0` adds zero per-fragment cost — mirrors the
  existing `u_decal_count == 0` early-out.
- `native/src/renderer/shaders/opaque.frag`: before adding the glow term, loop
  the kill spheres in world space. If `length(v_position_ws - center) < radius`
  for any sphere, force the glow contribution to 0 (hard cutoff). All other
  terms — `lit`, `u_emissive_color`, specular, rim, and damage decals — are
  untouched; only the glow-map term dies.

## Stock-BC parity

With no offline impulse engines, `u_glow_kill_count == 0` and the fragment path
is byte-identical to today. The feature is purely additive. It is **always-on**
(not dev-gated): it is a gameplay-state visual like the persistent damage
decals, not a developer tool.

## Edge cases

- `ies is None` or ship has no resolvable world location → no spheres (helper
  returns `[]`; `subsystem_world_position` already guards the no-mount case).
- Radius `<= 0` mount → skip (cannot define a region), consistent with the
  decal-radius and planet-influence guards elsewhere.
- The kill sphere also dims any non-impulse glow (e.g. nearby windows) that
  falls inside the hardpoint radius. This is accepted: the radius is the
  engine's own authored extent and the effect reads as "the engine bay went
  dark."
- Multiple offline pods → multiple spheres, capped at `N`; overflow beyond `N`
  is dropped (no ship has that many impulse mounts).

## Testing

**Headless pytest** on `offline_impulse_mounts`:
- master offline → exactly one sphere at the master mount with the master
  radius.
- master online with child pods of mixed state → spheres only for the offline
  children, at their mounts/radii.
- all online → `[]`.
- `ies is None` → `[]`.
- zero/negative radius mount → excluded.

**In-app verification:** run `./build/dauntless`, disable the player's impulse
engine (dev combat cheats / apply damage past the disabled threshold), confirm
the aft impulse glow goes dark within the hardpoint radius and restores on
repair; confirm an undamaged ship's glow is unchanged.

## Out of scope (YAGNI)

- Temporal fade / soft radial edge (explicitly chose hard cutoff).
- Dev-mode gating or a config toggle.
- Any change to gameplay flight degradation (already shipped).
- Warp-engine or other-subsystem glow masking (impulse only for now).
