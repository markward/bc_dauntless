# Scaled `GetRadius()` — design

**Status:** draft for Mark's review, 2026-11-03. Nothing built. Line references re-checked against the branch base `0b55cda86` (merged main + phase 0 rows); the audit was taken at `2369cba41` (see its §10).
**Ruling (Mark, 2026-11-03):** `GetRadius()` becomes the scaled world radius everywhere, as BC's is.
**Audit:** `docs/reference/engine/native-motion/radius-scale-audit.md` (§ numbers below are the audit's unless marked "this doc").
**Branch:** `ws/scaled-getradius`, forked from `project/native-motion-and-proximity`. It merges back before that project's phase 1 size-rule task (Task 7 in their plan; the brief called it task 6) and phase 3a.

## 1. What BC does, and what we do

- **BC.** `GetRadius()` is the scene node's world-bound sphere radius, with world scale applied (`stbc_reference/spec/CameraModes.md` §3.1; `ObjectClass.md:447`). BC has **no** `ObjectClass.SetRadius` (`App.py` binds it only on ProximityCheck and two property classes). The SDK's DockWithStarbase shrink (`AI/Compound/DockWithStarbase.py:50`) only works under the scaled reading (audit §2.1).
- **Ours.** `ObjectClass.GetRadius()` returns the unscaled `_radius` (`objects.py:210-211`). Four helpers multiply by `GetScale()` themselves, so collisions, avoidance, zoom fit and sensor occlusion already see the drawn size. Everything else, including all 72 SDK reads, sees the base.

## 2. Goals and non-goals

**Goals**
- `GetRadius()` returns the scaled world radius for every `ObjectClass`.
- Code that needs the unscaled base reads a new `GetBaseRadius()`.
- No helper double-scales, and Python and the native kernels agree bit for bit.
- The behaviour change lands in one commit, with nothing else in it.

**Non-goals**
- **Changing the radius rule** from the AABB corner distance to BC's merged bounding sphere. That is decision D1 (§8), a separate behaviour change.
- `SetClass.IsLocationEmptyTG` (a stub returning 1; four SDK spacing calls stay inert).
- ProximityCheck's unused `SetIgnoreObjectSize`.
- Giving headless hardpoint rocks a non-zero `GetRadius()` (they have base 0 until the host realises them; `rock.py:61-65`).
- Any edit to files the proximity project owns (§7).

## 3. Semantics

| Surface | After |
|---|---|
| `ObjectClass.GetRadius()` | `_radius * _scale` when `_scale > 0.0` and finite, else `_radius` (D2). Same expression and guard as `collisions.world_radius` today and its native twin `beam_geometry.cc:173`, so all three agree bit for bit. |
| `ObjectClass.GetBaseRadius()` (new) | `_radius`. Dauntless-only engine surface, not SDK: its docstring says so. Model-space users read it: seeds, planet render scale, NIF body units, the rock hull fallback. |
| `ObjectClass.SetRadius(r)` | Unchanged: it writes the base. Docstring: "sets the unscaled base radius; `GetRadius()` returns base × scale. BC has no `ObjectClass.SetRadius`; this is engine surface." Every caller already writes a base (audit §6). |
| `GetScale` / `SetScale` | Unchanged. |
| Native mirror | Unchanged: it still pushes raw `_radius` and `_scale` (audit §7). Kernels that want the world radius call `world_radius(m, h)`. |
| `ProximityCheck` | Its `GetRadius` / `SetRadius` overrides (trigger radius) are unchanged. It gets **no** `GetBaseRadius` override: nothing reads the base accessor on a check. The inherited one returns its unused `_radius` (0.0), and the docstring says so. |
| `Torpedo` | Inherits. `_scale` is never set on one, so its value is unchanged. |
| `DebrisChunk`, `_GhostTarget` | Not `ObjectClass`. Their `GetRadius` is already a world size. `world_radius` keeps its special cases for them. |

## 4. Helper and call-site changes

All of these land in the refactor commit (plan Task 1), **before** the flip, with byte-identical behaviour. At that point `GetRadius()` still returns `_radius`, so `GetBaseRadius()` equals it everywhere.

| Site | Becomes | Why |
|---|---|---|
| `collisions.world_radius` (`collisions.py:117-143`) | For an `ObjectClass`, `GetBaseRadius()` × the guarded scale. DebrisChunk and other duck types keep today's path. | It would double-scale after the flip. Plan Task 3 then reduces the ObjectClass branch to `GetRadius()`. |
| `rocks.rock.effective_radius` (`rock.py:60-70`) | base = `GetBaseRadius()`, falling back to the hull radius; × `GetScale()` | Base-or-hull fallback needs the base. Native twin `sensor_detect.cc:433` already does exactly this. |
| Planet realise `natural_scale` (`host_loop.py:7126`, `:8442`) and their seed guards (`:7121`, `:8437`) | `GetBaseRadius()` | Render scale is base / NIF sphere radius, then × `GetScale()` at draw. |
| Seed guards: `_seed_ship_radius` (`host_loop.py:6519`), `_seed_quickbattle_ship_radius` (`:8269`), `felix_destroy.py:88`, `combat_stress.py:232`, `:255` | `GetBaseRadius()` | Each guard reads the quantity it writes. Under a zero scale the seed survives (audit Annex C conflict C6). |
| `ui/spv_decals_pane.py:320` | `GetBaseRadius()` | Divides by `BC_MODEL_SCALE` to get NIF body units. |
| `ui/phaser_overlay.py:186` | `GetBaseRadius()` | SPV mount frame is unscaled. |
| `systems/apply_map.py:195` (`_rescale_sun`) | `GetBaseRadius()` | Read-then-`SetRadius` ratio. |
| `native_combat.py` `_K2_OBJECT_NAMES` (`:4641`), `_STEP_SHIP_PATCHES` (`:5419`) | Add `"GetBaseRadius"` | A Python twin now calls it, so patching it must send the step to Python, like `GetRadius` / `GetScale` (audit Annex D §1, **inferred**). |

**Unchanged on purpose:**
- **The 32 DRAWN reads** (audit §4). They change value for scaled objects, which is the point.
- **The 11 NEUTRAL reads.** Planets, suns and stations are never scaled; they keep `GetRadius()`, so a mod-scaled planet gets the drawn size.
- **Every `GetScale()` use that scales a non-radius quantity** (audit §5.2).

## 5. Native

- **K4** (`native/src/combat/src/k4_eligibility.cc:86-89`, `:104`): replace the three bare `r->_radius` reads with `world_radius(m, handle)` (`beam_geometry.h`). The finite check moves onto that value. This lands **with** the flip (plan Task 2), because its twin `damage_eligibility._radius` reads `GetRadius()`, which changes in that same commit.
- **Tractor stand-off** (`native/src/combat/src/tractor_force.cc:74-78`, `Step::standoff`): `source.row->_radius + target.row->_radius + margin` becomes `world_radius(m_, source.h) + world_radius(m_, target.h) + margin`. Since the combat_threading merge the tractor force runs **only** in C++ (`engine/appc/tractor.py` is a driver), so there is no Python twin to flip; this is the native half of the old `tractor.py:60-61` DRAWN reads (audit §10). It lands with the flip, because it is the same behaviour change.
- **No other kernel changes.** `world_radius`, `bubble_bound_radius`, the K2 sphere tier, the K3 sphere test and back-off, and `effective_radius` already compute base × scale from the raw mirror.

## 6. Comments and docs that go stale

Rewrite in plan Task 3: every docstring or comment that says `GetRadius()` is unscaled, listed in audit Annex A §4, Annex B §B and Annex C C8. That includes `engine/cameras/__init__.py:113-118` (its "within 10% … 4.46" note is contradicted by the live 4.366, audit §2.3) and the stale C++ line references in `projectile_geometry.cc:132` and `sensor_detect.cc:432`.

## 7. Requests for the proximity project (not made here)

`engine/appc/planet.py` is owned by `project/native-motion-and-proximity`.
1. **`planet.aggregate_suns_for_renderer`** (`planet.py:147-207`) computes `radius * scale` and `corona * scale` from `GetRadius()`. After the flip that double-scales a scaled sun. **Latent**: no SDK or engine path scales a sun. Request: read `GetBaseRadius()` there, or drop the `* scale`. It can ride on any later commit of theirs.
2. **`GetLineIntersectObjects`** (`planet.py:470`) and `_is_proximity_participant` (`:246`) need **no edit**. The reach becomes the scaled value automatically, which is intended. The participation sign test is unchanged.
3. **The size-rule task (their Task 7)** can read `GetRadius()` as BC's bounding radius once this branch merges. The open question on whether "bounding radius" includes scale (`open-questions-by-reading.md` Q3(c); NMP spec §8 item 2) is answered **yes**, and the ruling is made. Request: record that in their docs, which are theirs.
4. D1 was ruled (a): the corner rule stays for now. If a later change adopts the sphere rule, the near rule's radius changes value again with no edit on their side.

5. **Notice, not a request:** phase 2 ("motion takes over the tractor force step") will move or wrap `tractor_force.cc`. This branch changes one function there, `Step::standoff`. Whichever lands second rebases a one-line change.

No change is needed in `proximity_cache.py`, `proximity_table.py`, `sets.py`, `transform_store.py`, `native/src/transforms/`, `ship_motion.py`, `drift.py`, `subsystems.py`, or `IsTypeOf`.

## 8. Decisions

**D1 — which bounding radius? Ruled (a) by Mark, 2026-11-03: keep the corner rule on this branch; the sphere rule is decided later as its own change.** Ours is the AABB corner distance from the origin. BC's is the merged world bound sphere.
- **Evidence** (derived, audit §2.3): merging the NIF's stored shape spheres gives the Galaxy 4.366, exactly BC's live value, and the Sovereign 3.866 against BC's 3.929.
- **Size of the difference:** across 39 stock models, merged ÷ ours runs from 0.61 (FedStarbase 296 → 181) to 1.35 (DryDock 9.0 → 12.2). Most hulls are 5-30% smaller under BC's rule.
- **Effect:** switching would change every hull's chase distance, splash radius, collision body, avoidance, line-query reach and Intercept stand-off. That is far wider than the scale change.

Options:
- **(a) Recommended: keep the corner rule on this branch.** Ship the scale change alone. Decide the sphere rule later as its own change, with the merged-sphere computation in the NIF loader, its own sweep, goldens and live check.
- (b) Add the sphere rule to this branch as a second behaviour commit after the scale flip.
- (c) Never: keep the corner rule as a deliberate departure.

Carried to the later decision (raised when Mark asked for the downside of (b)):
- **Tuning on top of the corner rule.** `collisions.COLLISION_RADIUS_SCALE` (0.8) exists to offset the corner rule's overestimate; under a tighter sphere it would over-correct. Hand-tuned values (tractor margin, the Tau Ceti shuttle detour around Starbase 12's radius) need a fresh look too.
- **Sphere centre.** BC's bound sphere has its own centre; every consumer of ours treats the radius as centred on the object's origin. A merged-sphere radius used about the origin need not enclose the hull. The centre offsets have not been measured: a read-only measurement across stock models is the cheap first step.
- **Headless blindness.** Headless runs never seed a radius from the mesh (golden scenes set theirs; headless ships report 0), so goldens and the sweep cannot see the change; it is live-verified only.

**D2 — my call, flagged:** `GetRadius()` keeps `world_radius`'s guard, so a non-positive or non-finite scale returns the base. One rule in Python and C++, and K4 can call `world_radius`. BC's answer at scale 0 is unknown; presumably 0 (**inferred**: bound × 0). No stock path sets a scale ≤ 0.

**D3 — my call, flagged:** damage eligibility (`damage_eligibility._radius` + K4) follows the scaled `GetRadius()` rather than pinning the base. That fits the ruling "scaled everywhere", and it is our own heuristic rather than a BC one. A scaled rock or the docking player now ranks by drawn size.

## 9. Behaviour change and test strategy

Commits, in order (plan tasks):
1. **Refactor, no behaviour change.** Add `GetBaseRadius()` and move §4's sites onto it.
   - Falsifier: every focused test named in the plan passes **unmodified**, except new tests for `GetBaseRadius`.
2. **The flip.** `GetRadius()` scaled; K4 and the tractor stand-off use `world_radius`.
   - Tests: new `GetRadius` scale cases with the guard; K4 scale cases in Python and C++; a C++ tractor stand-off scale case; the guard test `test_get_radius_stays_unscaled_and_effective_radius_scales_once` rewritten to pin the new contract.
   - **Golden fights must be byte-identical.** No golden scene calls `SetScale`, and `r * 1.0 == r`. If any moves, stop and find out why. Do not re-record without asking Mark.
   - The headless 26-mission campaign sweep runs here. It is expected to pass unchanged, because headless rocks have base 0.
   - This commit carries the change and nothing else.
3. **Cleanup, no behaviour change.**
   - `world_radius`'s ObjectClass branch becomes `GetRadius()`.
   - Test-side `GetRadius() * GetScale()` in `tests/host/test_native_k3_differential.py:196`, `:221` becomes `GetRadius()`.
   - Stale docs (§6).
4. **Live check by Mark** before the merge:
   - the E1M2 intercept tutorial on a scaled fragment (stand-off distance);
   - the reticle box and range readout on E1M2 rocks;
   - a warp or course through the Vesuvi rocks (obstacles);
   - a DockWithStarbase docking (shrink + camera).

**Perf:** `GetRadius()` gains one compare plus `math.isfinite` per call, and the proximity line query calls it per candidate. That is not measured, because the machine is shared and benchmarks need Mark's go-ahead. Phase 0's re-measure on the project branch covers it.

## 10. Risks

- **A twin missed.** Mitigation: K4 gets scale cases on both sides, and the existing scale-fuzzing tests on `world_radius`, `bubble_bound_radius`, the beam trace and `effective_radius` stay green unmodified through Task 1 and Task 2.
- **A test fake that subclasses `ObjectClass` and overrides `GetRadius`** would see `world_radius` change in Task 3. The focused files named in Task 3 cover the known fakes.
- **Merge friction with phase 3.** `host_loop.py` edits are six one-token swaps.
- **Merge friction with phase 2** on `tractor_force.cc` (§7 item 5): one function.
