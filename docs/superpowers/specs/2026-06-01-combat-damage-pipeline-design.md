# Combat Damage Pipeline — Roadmap

**Status:** roadmap drafted, awaiting user review
**Date:** 2026-06-01
**Author:** Mark Ward (with Claude)
**Prior art:**
- [`2026-05-14-phaser-combat-design.md`](./2026-05-14-phaser-combat-design.md) — phaser firing pipeline.
- [`2026-05-14-torpedo-combat-design.md`](./2026-05-14-torpedo-combat-design.md) — torpedo runtime + collision.
- [`2026-05-14-weapon-firing-pipeline-design.md`](./2026-05-14-weapon-firing-pipeline-design.md) — per-ship power budget + StartFiring path.
- [`2026-05-28-ship-display-panel-design.md`](./2026-05-28-ship-display-panel-design.md) — UI consumer of the damage state this pipeline produces.

## 1. Goal

Close the loop from weapon impact → damage applied to the receiving ship → ShipDisplay panel and damage VFX. Faithful to stock Bridge Commander semantics: hits land on the hull in 3D space, propagate to whichever subsystem is nearest, and bubble up through the SDK's existing parent/child subsystem tree.

This document is a **roadmap**, not a single-shot spec. The work is staged into five independently-shippable projects, each with its own design session, plan, and implementation cycle.

## 2. Diagnosis — what's already in place, what's actually broken

The visible symptom motivating this work was: *"fire a phaser at a target and shields / hull stay at 100 %; the damage list never populates."* Inspecting the current code:

- `engine.appc.combat.apply_hit` already routes `shields → picked subsystem → hull` and broadcasts `WeaponHitEvent`. ✓
- `host_loop._advance_combat` already calls `apply_hit` every tick for both torpedoes and continuous phaser ticks. ✓
- `ShieldSubsystem.ApplyDamage`, `DamageableObject.DamageSystem`, condition-derived `IsDamaged / IsDisabled / IsDestroyed` all exist and pass their unit tests. ✓
- Damage values are property-driven from SDK hardpoint scripts (`SetMaxDamage`, `SetMaxShields`, `SetShieldChargePerSecond`, `SetMaxCondition`, `SetDisabledPercentage`); the engine reads them via `SetProperty` mirroring at ship construction. Fidelity confirmed. ✓

What is genuinely missing or wrong:

1. **`pick_target_subsystem` is effectively a no-op on real ships.** It calls `ship.GetNumChildSubsystems()` guarded by `hasattr`, but `ShipClass` (→ `DamageableObject` → `PhysicsObjectClass` → `ObjectClass`) doesn't define that method — it's only on `ShipSubsystem`. So the loop never runs and the function always returns `ship.GetHull()`. Damage routes shields → hull, never touching any subsystem unless the player has explicitly aimed at one. ([engine/appc/combat.py:20-60](../../../engine/appc/combat.py#L20-L60))
2. **Hit point is approximate.** Torpedoes report `torpedo._position` at the moment of bounding-sphere intersection; phasers report `target.GetWorldLocation()` (ship center) when no subsystem is aimed. Neither is a real point on the hull surface. This is unfit for damage VFX and biased for subsystem-proximity picking.
3. **Shield face mapping ignores ship rotation.** `_shield_face_from_hit_point` reads world-axis dominance of `hit_point - ship_pos`. Any target with non-identity rotation gets the wrong face debited. Comment in the file already flags this as future polish. ([engine/appc/combat.py:63-81](../../../engine/appc/combat.py#L63-L81))
4. **The ShipDisplay damage list walks four named parent subsystems** — Engines, Weapons, Sensors, Shield Generator — none of which currently take damage even when `apply_hit` does run cleanly. The fix is structural: hardpoint children damage their parent virtually via aggregation.
5. **Damage VFX is a stub.** `hit_vfx.spawn(point)` already exists but renders at the approximate hit point; no surface normal, no severity tiering, no audio binding for camera shake / hull rumble.

## 3. Design decisions (locked in this session)

- **Impact location is mesh-accurate.** Ray-vs-triangle trace against the loaded NIF geometry. Approximate bounding-sphere intersection is not retained even as a v0 — both subsystem-proximity damage and damage VFX need the real surface point, so a half-step would be thrown away.
- **Parent subsystems aggregate their children's state.** `IsDamaged = self._damaged or any(c.IsDamaged() or c.IsDestroyed())`, `IsDisabled = all(child.IsDisabled())`, `IsDestroyed = self._destroyed or all(child.IsDestroyed())`. Leaf top-level subsystems (Sensors, Engines, Shield Generator) take direct hits as today. (The `or c.IsDestroyed()` term and the `_damaged`/`_destroyed` explicit-flag escape hatches were refined during Project 2's TDD pass — see `docs/superpowers/specs/2026-06-01-subsystem-damage-propagation-design.md` §3.4.)
- **Targeting a subsystem biases aim, not damage allocation.** When the player targets a subsystem the firing math aims the beam / projectile at that subsystem's world position. Subsystem damage is *always* by proximity to the mesh-accurate impact point — targeting just makes the impact land closer.
- **Beam-vs-mesh: one impact point per tick.** Phasers report the first triangle hit; no along-beam sample sweep in v1.
- **Acceleration structure: brute-force triangles to start.** No BVH until profiling shows we need one. CPU-side mesh data is already retained on every loaded model (`keep_cpu_data = true`), so the data path is there.
- **Bridge-view feedback: audio + camera shake only.** Bound off `WeaponHitEvent` when the player is the recipient. No interior smoke, sparks, or panel-blow effects.

## 4. The five projects

Each project is a separate session: brainstorm → spec → plan → implement. The roadmap below is the table of contents; per-project specs live alongside this one as they're written.

### Project 1 — Mesh-accurate hit resolution (initial)

Foundation. New C++ binding that ray-traces a ship instance's loaded mesh and returns `(hit_world, normal_world, t)` or `None`. Used by both projectile (per-tick velocity ray) and phaser (emitter → target line) paths. Replaces the current approximate hit-point computation in `apply_hit`'s callers.

Touches: `native/src/host/host_bindings.cc`, `native/src/renderer/` (new ray-trace helper alongside `aabb.cc` which already walks `cpu_data()`), `engine/appc/projectiles.py`, `engine/host_loop.py:_advance_combat`. Existing tests in `tests/integration/test_phaser_damage_applied_through_apply_hit.py` should pass with updated hit-point assertions; new `tests/integration/test_mesh_ray_trace.py` covers the C++ binding.

Risk: ray-trace cost at 60 Hz × dozens of beams. Mitigation: brute-force triangle scan against ship's bounding sphere as a coarse reject before the inner loop. BVH parked.

### Project 2 — Subsystem damage propagation

Built on Project 1. Replace `pick_target_subsystem` with a body-frame proximity walk over `ship.GetSubsystems()` plus the `_children` list of each weapon system (PhaserBank under `_phaser_system`, TorpedoTube under `_torpedo_system`, etc.). World→body transform uses `GetWorldRotation()` columns per CLAUDE.md's column-vector convention. Closest subsystem within ~2× radius takes the damage.

Parent-aggregator predicates: `WeaponSystem.IsDamaged/IsDisabled/IsDestroyed` derived from children rather than from a separate condition pool. ShipDisplay damage list populates without any panel-side change.

Touches: `engine/appc/combat.py`, `engine/appc/subsystems.py` (WeaponSystem predicates), unit tests for both. Smoke: fire at a Warbird in E1M1, confirm the damage list flips rows as expected.

### Project 3 — Rotation-correct shield face mapping

Small, isolated. Replace `_shield_face_from_hit_point`'s world-axis dominance check with a body-frame transform of `(hit_point - ship_pos)` via `GetWorldRotation()` columns. Same trick as Project 2's body-frame transform, factored to a shared helper.

Touches: `engine/appc/combat.py`, new unit tests covering rotated ships hit from various world directions.

### Project 4 — Damage VFX + bridge-view feedback

Spawn sparks / debris / hit-flash at the mesh-accurate impact point, oriented by the surface normal. Severity tiering off the per-hit damage amount and the recipient subsystem (shield-only hit vs. hull penetration vs. subsystem critical hit each get different visuals). Bridge-view: audio cue + camera shake bound off `WeaponHitEvent` when the player is `evt.GetTarget()`.

Touches: `engine/appc/hit_vfx.py`, new renderer particle / billboard pass (or extension of existing `hit_vfx` pass), audio binding via `LoadTacticalSounds`, camera-shake hook in `engine/host_loop.py` camera math.

### Project 5 — Subsystem-failure gameplay consequences

Disabled engines clamp impulse to zero; disabled weapons gate `StartFiring`; disabled sensors blank target list + IFF colour; disabled shield generator zeros `_charge_per_second` for all faces. Pure Python; touches `engine/appc/ship_motion.py`, `engine/appc/subsystems.py` (firing gate), `engine/ui/sensors_panel.py`, `engine/ui/target_list_view.py`. Closes the gameplay loop — until this lands, "destroyed engines" is a UI label only.

## 5. Non-goals across the arc

- Per-class hardcoded vulnerability tables. BC didn't have them; the SDK's parent/child subsystem tree plus proximity picking handles fidelity.
- Procedural hull-breach geometry, cinematic destruction sequences, debris physics. Project 4 covers sparks + flash + camera; cinematic destruction is its own future arc.
- Multi-hit dynamics (flank stripping, armour layering). Stock BC doesn't model these.
- Mod-script hooks for custom damage models. No real consumer; speculative.
- Save / load of in-flight damage state. Damage state lives on the same subsystem `_condition` fields the existing save path already serialises.

## 6. Parking lot

- **BVH or brute-force ray-vs-triangle.** Project 1 starts brute-force with a bounding-sphere coarse reject. Revisit if profiling shows a hot loop. Galaxy ≈ 20k triangles; brute-force at 60 Hz × ~10 simultaneous beams is on the edge of acceptable.
- **Along-beam damage sampling.** v1 takes a single impact point per tick. Multi-point sampling (model phaser sweeping across hull as ship rotates relative to emitter) is a polish item.
- **Bridge interior reactions beyond audio + shake.** Console sparks, crew animation reactions, panel blowouts — out of scope for the arc; revisit only if specific missions demand it.
- **Damage repair interaction.** Project 5 enables disabled-subsystem consequences but doesn't redesign repair; current `RepairSubsystem` semantics keep working.

## 7. Workflow

Each project gets its own session. The user requests a handoff prompt for the next project when ready; that prompt seeds a fresh session that runs the full brainstorm → spec → plan → implement cycle for one project only.

The five projects are ordered as listed: Project 1 is the only one with no upstream dependency; Projects 2-4 all depend on Project 1's hit-point output; Project 5 is independent of 1-4 and could parallelise after the project list is approved.
