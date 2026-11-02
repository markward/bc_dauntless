# Collisions into the sim tick — map (roadmap decision 10)

Worktree read: `.claude/worktrees/native-combat-k3` (branch `ws/combat-launch-cache`, HEAD `5163932f4`).
HL = `engine/host_loop.py`, COL = `engine/appc/collisions.py`, LP = `engine/core/loop.py`.
Line numbers are this worktree's. The event inventory's `HL:12825-12828` is now HL:12843-12847.
Anything not read directly in code is marked **inferred**.

---

## 1. The collision pipeline today

### 1.1 Where it runs in the frame

Frame order inside `run()`, all under `if not pause.sim_frozen:` (HL:12512):

| # | Step | Cadence | dt | Lines |
|---|---|---|---|---|
| 1 | `step_accumulator` → `_sim_ticks_this_frame` | per frame | wall `_frame_dt`, clamped to `MAX_FRAME_DT` 0.25 | HL:12344-12346; `engine/core/timestep.py:11-34`; TICK_DT/MAX_FRAME_DT HL:11731-11732 |
| 2 | `advance_ticks(... _tick_gameloop ...)` → `GameLoop.tick` **N times** (AI, `gl.warp_states`, `gl.motion`, `gl.rock_motion`, `gl.rock_death`, `gl.subsystems`) | per tick | `TICK_DELTA` | HL:12372-12373, HL:11752-11754; LP:30-118 |
| 3 | `_apply_input` → `_PlayerControl.apply`: the **manually flown player** is rotated and translated here | **once per frame** | `_player_dt` (wall) | HL:12572-12573; HL:3291, HL:3484-3496 |
| 4 | `manual_aim.update` | per frame | — | HL:~12604 |
| 5 | `for _tick_i in range(N)`: `_combat_effect_scope()` { `sim.weapons`, `sim.combat` (incl. `cb.tractors`) } | per tick, **after all N GameLoop ticks** | `TICK_DT` | HL:12634-12657 |
| 6 | sensor contacts, crew prompts | per frame | game time | HL:12659-12679 |
| 7 | `for _tick_i`: nebula tracker + radiation | per tick | `TICK_DT` | HL:12698-12705 |
| 8 | `_warp_state.sync_flythrough` (leak guard) | per frame | — | HL:12828-12830 |
| 9 | `debris_chunk.tick(_player_dt)`, `hull_breakup.drain`, `hull_wear.drain` | per frame | wall | HL:12832-12841 |
| 10 | **`collisions.tick_collisions(_player_dt, ship_instances=...)`** in scope `sim.collisions` | **once per frame** | **`_player_dt` (wall)** | HL:12843-12847 |
| 11 | `rock_vfx.pump`, `_pump_minor_contact`, `_pump_scenery_contact` (`sim.rock_breakup`), `_pump_rock_promotion` | per frame | — | HL:12853-12860 |
| 12 | `dash.tick(player, _player_dt)`, `handoff.tick` | per frame | wall | HL:12866-12880 |
| 13 | `_reconcile_scene`, then `_sync_instance_transforms` / render xforms | per frame | — | HL:12900+ |

The comment above the call states the intent: "Runs once per render frame after motion + player input … dt = _player_dt … the collision-velocity overlay is real-time motion, so it advances/decays on real elapsed time, not the fixed sim TICK_DT" (HL:12808-12827).

### 1.2 dt source, pause and time scale

- `_player_dt = 0.0 if pause.sim_frozen else min(max(_frame_dt, 0), MAX_FRAME_DT)` (HL:12356). Wall clock, same clamp as the accumulator.
- Game time for the frame is `_frame_game_dt = N × TICK_DT` (HL:12363). Both are clamped at 0.25 s, so **over many frames ∑`_player_dt` ≈ ∑ game time** (they differ per frame by the accumulator remainder, under one tick). The difference is per-frame distribution, not drift. (**Derived** from timestep.py:25-34 and HL:12356.)
- **0-tick frames** (refresh rate above 60 Hz): today collisions still run with `_player_dt > 0` (the player also moves on those frames).
- **Pause / DevTools freeze:** the whole block is skipped (HL:12512) and `_player_dt = 0` (HL:12356). No collisions under pause, today or per tick.
- **Time scale:** not implemented. `UtopiaModule.SetTimeRate/SetTimeScale` exist in the SDK (`sdk/.../App.py:3211-3212`; one SDK caller, `CinematicInterfaceHandlers.py`), but nothing in `engine/` or root `App.py` defines them (grep, no hits), and `TGTimerManager.tick` adds the raw delta (`engine/appc/timers.py:86-87`). Game time is always ticks × TICK_DT. Collision behaviour under time scale is therefore moot today.

### 1.3 What one call does (`tick_collisions`, COL:1225-1241)

1. `iter_collidables()` (COL:1205-1222): every `ShipClass` (rocks included) and `Planet` (moons, suns) with `GetRadius() > 0` in **every** set in `g_kSetManager._sets`, plus live `DebrisChunk`s.
2. `_apply_overlay_all(objects, dt)` (COL:1037-1054): each object's `_collision_velocity` overlay displaces it by `overlay × dt` (`SetTranslateXYZ`) and decays by `exp(-dt / 0.5)` (`COLLISION_DECAY_TAU`, COL:26). Runs even when the dev "Disable Collisions" toggle is on.
3. Dev toggle `disable_collisions_active()` → return (COL:1237-1239).
4. Filter `_collisions_enabled` (COL:238-259): the SDK `SetCollisionsOn` flag **and** `not is_ship_warping(obj)` (warp suppression).
5. `resolve_collisions` (COL:1132-1202):
   - bulk position fetch from the transform store (COL:1162-1164): **sim poses** (live transforms), not render-interpolated ones. The player's pose is its live per-frame-integrated pose (HL:3484-3496).
   - `_resolve_body` for **every** object (COL:1165, def COL:281-328): mass, `GetVelocity()` + overlay, world angular velocity from body-frame `_current_angular_velocity` rotated by `GetWorldRotation()`.
   - shield-bubble radius widening when a rock is present (COL:1177-1183).
   - spatial-hash broadphase per set + all cross-set pairs (COL:1057-1129).
   - per pair: `frames.offset_between` (cached per set pair), `EnableCollisionsWith` mask, then `_respond_pair` (COL:1184-1201).
6. `_respond_pair` (COL:722-907):
   - narrowphase: shield bubble vs rock (`_shield_contact`, COL:685) else hull pieces (`_hull_contact`, COL:618; `_deepest_piece_overlap`, COL:342).
   - `v_rel` from **centre-of-mass** velocities only (COL:774-785).
   - `v_rel >= 0` (receding/resting) → **grind** `_grind_contact` (COL:788-808; def COL:527-615): damage = `2.5 × μ × slip × dt` (COL:575), skipped when `damage/dt < kGrindMinDamageRate` (1.0 hull pts/s, COL:39, COL:576). Two `apply_hit`s with `weapon_type="collision"`, `decal_dent=0.0` (scrape scuff). **No collision event**; `apply_hit` still posts `ET_WEAPON_HIT` (event-inventory §7 F8).
   - approaching → impulse into the overlay (COL:810-821), positional de-penetration by inverse mass (`SetTranslateXYZ`, COL:823-835), then **events before damage**: `_emit_planet_collision` (COL:849; def COL:955-984), `_emit_cloaked_collision` + `_emit_object_collision` unless a `DebrisChunk` is a party (COL:860-869; defs COL:987-1034, COL:910-952), then KE damage `_ke_damage` (COL:331-340) through `apply_hit` per movable side with `single_impact=True`, `decal_dent=1.0` (COL:880-906).
7. Events are posted synchronously through `App.g_kEventManager.AddEvent` (COL:947, COL:982, COL:1031).

### 1.4 Contacts that are NOT in `tick_collisions`

- **Minor rocks** (`engine/rocks/minor_contact.py:100-128`) and **large field rocks** (`engine/rocks/scenery_contact.py:63-163`) are swept **natively inside `frame()`** (`native/src/host/host_bindings.cc:1519-1564`: `step_minor_field`, `step_near_field`) against the player's **drawn instance** (`player_box_of`, `inst->world`), and drained by Python the next frame (HL:12856-12857). They are player-only, render-side, and use game time only for throttles. Scenery contact writes the player's overlay + translate and calls `apply_hit` (scenery_contact.py:110-143); no collision events (scenery_contact.py:16-18).
- **Collision avoidance** (AI preprocessor inside `gl.ai`, LP:57-58 and LP:77-86) reads the overlay through `collision_avoidance.py:195-198` and its obstacle snapshot is invalidated each tick (LP:31-35).

---

## 2. Everything else per frame that interacts with collisions

| Mover | Cadence / dt | What it writes | Interaction with collisions |
|---|---|---|---|
| `tick_all_ship_motion` (LP:105-106; `ship_motion.py:154-300`) | per tick, `TICK_DELTA` | translate (`GetTranslate`+v·dt) and `SetVelocity` (ship_motion.py:265-298) | Collision response **never writes `GetVelocity`**, only the overlay and translates. Motion integrates from the current translate, so de-penetration and overlay displacement carry into the next tick's position; the impulse does **not** feed back into motion's velocity (grep: only COL and collision_avoidance read `_collision_velocity`). |
| `rocks.motion.tick_all` (LP:108-110; `engine/rocks/motion.py:18-21` → `drift.step`) | per tick | translate | same as above |
| `rock_death.advance` (LP:112-114) | per tick | rock retirement | a collision kill's rock begins death inside `apply_hit`; retirement follows in a later GameLoop tick (inventory R4) |
| `_PlayerControl.apply` (manual player) | **per frame, `_player_dt`**, after all GameLoop ticks, before combat (HL:12572) | rotation, `SetVelocity`, translate (HL:3484-3496); publishes body-frame angular velocity for the collision model (HL:3168-3179) | today collisions run after it, so the drawn player is always de-penetrated |
| `cb.tractors` (`engine/appc/tractor.py:83-109`) | per tick, inside combat | **direct translate** of target/source; dock mode zeroes velocity | tractor displacement does not change `GetVelocity`, so a tractor push into a hull reads `v_rel >= 0` → grind, not impulse (**inferred** from COL:774-808) |
| `warp_state.tick_warp_states` (LP:96-98) | per tick | warp state | a dewarp completing this frame is collidable this frame (warp_state.py:107-113; guarded by `tests/host/test_warp_state_host_wiring.py:34-47`) |
| `warp_state.sync_flythrough` (HL:12830) | per frame | clears flythrough warping | must precede collisions (leak guard) |
| `debris_chunk.tick(_player_dt)` (HL:12835; `debris_chunk.py:202-225`) | per frame, **wall** | chunk `_loc` + render push | chunks are collidables; today they move, then collide |
| `dash.tick(player, _player_dt)` (HL:12869) | per frame | dash engage/drop-out; flight itself is `warp_flight.step` inside `ship_motion` per tick (ship_motion.py:203-205) | dash sets `WES_WARPING` (dash.py:531) → non-collidable via `is_ship_warping` |
| Physics engine | — | **none**: PyBullet is not used here; collisions are a kinematic overlay (COL:1-11) | — |

Render side: non-player ships draw `lerp(prev, cur, alpha)`; `advance_ticks` re-seats prev before the last tick (`engine/core/transform_buffer.py:65-87`), and cur is captured after collisions (HL:12880+). Collision writes therefore land in the drawn pose today.

---

## 3. What changes if collisions run once per sim tick

### 3.1 Frequency and cost

- Measured `sim.collisions`, 65-ship `combat_stress` fight, Debug, 1280×720: **0.53-0.65 ms per call**, once per frame, at 2.0-3.5 average ticks a frame (`~/Documents/dauntless-perf/ws-f2-brawl-on-run1-cs64-bridge-20261102-0456.log`, lines 85, 235, 388, 541, 692, 843, 996, 1148, 1302, 1453, 1605, 1757, 1908; tick counts lines 16-1838). The posed-parts map divides it per tick: 0.165 ms "per tick" = once per frame ÷ 3.4 (`docs/reference/engine/native-combat/posed-parts-map.md:340`, method at :345-347).
- Other captures: B3 `sim.collisions` 0.7 ms per frame (perf-register SIG-078, line 515); belt session 2.2 ms per frame (SIG-075, line 518, weak evidence).
- Per tick, the call count becomes N. **Derived:** in the 64-ship fight, ~0.55 × 3.2 ≈ 1.8 ms a frame, **+~1.2 ms a frame** (+~0.37 ms per tick). In the belt (SIG-075) roughly 2× of 2.2 ms. At 1 tick a frame, no change. At >60 fps, cost **drops** (0-tick frames run nothing).
- **Catch-up frames:** up to 15 ticks (0.25 s cap / TICK_DT; the profiler prints "capped at 15", log line 16). 15 × 0.55 ≈ 8 ms added to a frame that is already a hitch (**derived**).
- **Inferred**, not measured: most of a call is per-call fixed work, not per-pair. `_resolve_body` runs for every collidable before the broadphase (COL:1165), with `GetVelocity`, a matrix multiply and `world_radius` each; with few contacts, pairs are rare. So the cost scales with body count × ticks. Needs a sub-scope split before deciding.
- `sim.collisions` must join `PER_TICK_ROOTS` (`engine/core/frame_profiler.py:124-125`), or reports will read it as once per frame (`docs/reference/engine/frame-profiler.md:160-172`).

### 3.2 Behaviour

- **dt:** `TICK_DT` on game time. Grind damage is already a rate (COL:575-576) and frame-rate independent (`tests/unit/test_collision_sustained_contact.py:124-140`, `:247`). Totals are unchanged; per-call grind count becomes 60/s instead of fps, so `ET_WEAPON_HIT` grind posts (F8) and `ConditionAttacked` accumulation stop depending on frame rate. Overlay decay composes exactly (`exp(-a)·exp(-b) = exp(-(a+b))`); displacement integrates in smaller steps (**derived**).
- **Pause:** unchanged (0 ticks, block skipped).
- **Time scale:** nothing to change (not implemented, §1.2).
- **Determinism:** AI-vs-AI, rock and planet contacts become a function of the tick sequence, not frame timing. **Inferred:** fewer frame-timing-dependent `apply_hit` calls also stabilise the shared random-number streams (hit-feedback rolls), until decision 12 separates cosmetic rolls. The manually flown player stays frame-rate dependent (its motion is per frame on `_player_dt`).
- **0-tick frames:** the player moves (HL:12572), but no collision runs until the next ticking frame. **Derived:** at 6.3 GU/s and 144 Hz, at most ~0.04-0.1 GU of drawn interpenetration for a frame.

### 3.3 The frame structure catch

All N GameLoop ticks (AI, motion) run **before** any combat tick (inventory §0.2, R10). So there are two "per tick" placements, and neither is a true interleaved tick:

- **(A) inside `GameLoop.tick` after `gl.rock_motion`** (LP:108-110). AI and rock poses are true per tick. But: the manually flown player moves after all GameLoop ticks (HL:12572), so its contacts resolve **one frame late** and it is drawn penetrating while pushing in. Collisions would also run before each tick's combat (opposite of today and of the oracle). The headless harness (`tests/helpers/headless_mission.py:71-79`, `tools/gameloop_harness.py:122`) would start running collisions in every mission test (the 26-mission sweep included). And every test that calls `loop.tick()` and then `tick_collisions` would double-resolve.
- **(B) in the host's per-tick combat loop, after the effect scope closes** (HL:12634-12657). The player's frame motion is already applied, so tick 1 resolves it. Collision events land at a defined per-tick point after that tick's weapon effects (R10). Matches the ordering the oracle harness already uses (`tests/oracle/conftest.py:74-86`: loop, weapons, combat, collisions per tick). Catch: AI and rock poses are the frame-end poses for all N collision ticks. Tick 1 de-penetrates and impulses; ticks 2..N mostly grind and apply the overlay. The real per-tick gain is interplay with combat (tractor moves, collision kills seen by the next combat tick) and the event boundary, not finer geometry.

---

## 4. Tests that pin collision behaviour

Tests that drive `tick_collisions` **already step it per tick with 1/60 dt**, interleaved with `GameLoop.tick()`, so none assumes wall-clock dt:

- `tests/integration/test_e1m2_rocks.py:80-110` (Haven, R1; mutation-proven, inventory line 240), `:113-156` (Facility), `:159-218` (no cascade), `:221-292` (breakup grind, with `debris_chunk.tick(dt)`): `loop.tick(); collisions.tick_collisions(1.0 / 60.0)`.
- `tests/unit/test_shuttle_service.py:349-380`: `loop.tick(); tick_collisions(DT)`.
- `tests/oracle/conftest.py:74-86`: loop, `_advance_weapons`, `_advance_combat`, `tick_collisions(TICK_DELTA)` per tick.
- Unit tests (`test_collisions.py:272-355`, `test_collision_sustained_contact.py` (`FRAME = 1/60`, :31, :62-66), `test_collision_event.py`, `test_planet_collision_event.py`, `test_collision_scuff.py`, `test_collision_hull_wear.py`, `test_collision_radius_scale.py`, `test_collision_broadphase.py`, `test_rock_shield_collision.py`, `test_cross_set_interaction_gate.py`, `test_debris_chunk.py:148-173`, `test_scenery_contact.py`, `test_part_detach_render.py` (docstring about order, :10-14)) call `tick_collisions` / `resolve_collisions` / `_respond_pair` with an explicit dt. They are placement-agnostic.
- `tests/integration/test_e1m1_dock_immobility.py:40-118`: `resolve_collisions` with dt 0, placement-agnostic.
- `tests/integration/test_frame_tripwire.py:111-164`: `resolve_collisions` only.

**Host source-order guards** that a move must update or keep:

- `tests/host/test_warp_state_host_wiring.py:34-47`: `_tick_gameloop, _interp_live_poses)` before `collisions.tick_collisions(`, and `warp_state.sync_flythrough(` present. Still holds under (B).
- `tests/host/test_scene_reconcile_ordering.py:40-52` (`collisions.tick_collisions(` before the reconcile) and `:165-172` (collisions < `dash.tick(` < `handoff.tick(`). Still holds under (B) (text order).
- `tests/host/test_frame_rate_independence.py:99-150`: `TICK_DT` may only be passed inside `for … in range(_sim_ticks_this_frame)`. (B) satisfies it. The fake-clock test (:78-97) checks consumers receive the game time the loop advanced.

**Headless:** `headless_mission._sim_tick` runs only `loop.tick()` + `dash.tick` (headless_mission.py:71-79). No collisions (inventory §0.2 line 38). `tools/gameloop_harness.py:122` is the same. Under (B) that stays true; under (A) it changes.

---

## 5. Risks

1. **Cost** (§3.1): ~+1.2 ms a frame in the 64-ship fight, up to ~8 ms on a 15-tick catch-up frame (derived).
2. **Grind rates:** safe. Damage is `rate × dt` with a rate floor (COL:575-576). Per-call side effects scale with call count: `ET_WEAPON_HIT` per grind (F8), the per-call shield flash seed (COL:871-876 comment), and scuff `apply_hit` calls go from fps to 60/s.
3. **Wall-clock throttles:** the hit-sound edge trigger uses `time.monotonic()` with a 0.15 s gap (`engine/appc/hit_feedback.py:172`, `:186-198`). N ticks in one frame land microseconds apart, so the first plays and the rest stay silent, as with consecutive frames today. On a catch-up frame, a fresh contact later in the frame is muted where game time says it shouldn't be (decision 12 bug, independent). Hull smoke is game-time and skips collisions (`engine/appc/hull_hit_smoke.py:42-92`, torpedo/phaser only). The decal/carve throttles are game-time (hull_hit_smoke.py:46). Minor-contact throttles are game-time (minor_contact.py:113-114).
4. **Player under pause:** none either way (HL:12512, HL:12356).
5. **Player manual motion is per frame:** under (B), correct for tick 1. Under (A), one frame late. Either way, 0-tick frames move the player unresolved (§3.2).
6. **Warp:** `is_ship_warping` suppression is per object and read per call (COL:238-259). `sync_flythrough` is per frame (HL:12830) and must run **before the first collision tick**, i.e. move it above the combat loop. `tick_warp_states` is in GameLoop (all ticks before the combat loop), so a dewarp completed this frame is still collidable this frame.
7. **Dash / in-system warp:** the flight sets `WES_WARPING` (dash.py:531) → excluded. Engage/drop-out happen in per-frame `dash.tick` after collisions (HL:12869), unchanged latency. Minor/scenery contacts are muted while dashing (minor_contact.py:42-48).
8. **Docking (E1M1/E6M2):** relies on `IsImmobile` anchors (COL:315-322), `SetCollisionsOn` and `EnableCollisionsWith` (COL:1188-1191). All per-object flags, dt-independent (dock tests use dt 0). **Inferred** safe. Not live-checked.
9. **Tractors:** displace positions inside each combat tick (`tractor.py:83-101`). Under (B), collisions after each combat tick de-penetrate tractor-driven overlap per tick instead of after three ticks of accumulation. Tow behaviour against a hull may change feel (**inferred**, needs a live tow).
10. **Debris chunks:** they move per frame on wall dt (HL:12835) **before** today's collision call. Under (B), collisions run before `debris_chunk.tick`, so chunks collide at last frame's pose and are drawn after moving unresolved. Also `test_part_detach_render.py:10-14` documents an ordering assumption around chunk spawn vs `debris_chunk.tick`. Either move chunk integration onto the tick too, or accept the one-frame lag.
11. **Minor / field-rock contacts** stay per frame. They are produced by native `frame()` against the drawn player box (host_bindings.cc:1519-1564), so they cannot simply move into the tick. Leave them per frame.
12. **Radiation order:** collisions would now precede the frame's radiation ticks (HL:12698). No known mission rule depends on that (**inferred**).
13. **Effect queue:** collisions must stay **outside** `_combat_effect_scope` (HL:958-969). Inside it, any queued producer a collision handler triggers (e.g. a `StopFiring` → `LOOP_STOP`) would deliver after the synchronous collision events, and the tick's queued weapon events would deliver after the collision events. That inverts emission order.
14. **Stale comments/docs:** HL:12808-12827 ("dt = _player_dt … real-time motion"), the COL:1-11 and COL:1225-1235 docstrings ("once per render frame"), COL:39-49 (`kGrindMinDamageRate` comment), `warp_state.py:107-113`, `frame-profiler.md:166-167`, and event-inventory §0.2 / R10 / F4.

---

## 6. Recommended design

**Placement (B):** in `run()`, inside `for _tick_i in range(_sim_ticks_this_frame):` (HL:12634), **after** the `with _combat_effect_scope():` block closes:

```
with frame_profiler.scope("sim.collisions"):
    collisions.tick_collisions(TICK_DT, ship_instances=...)
```

- Move `_warp_state.sync_flythrough(...)` (HL:12828-12830) above the combat loop. Remove the per-frame call at HL:12843-12847.
- dt = `TICK_DT`, game time. Add `"sim.collisions"` to `PER_TICK_ROOTS`.
- Optionally move debris-chunk integration onto the tick (integrate per tick with `TICK_DT`, push transforms once per frame), so chunks and collisions share poses (risk 10).
- Keep minor/scenery contact pumps per frame (risk 11).
- Rationale: it is the order the oracle and the E1M2/shuttle tests already model (loop → weapons → combat → collisions per tick). It resolves the manually flown player in the same frame. It gives collision events a defined per-tick boundary after that tick's weapon effects (R10). It needs no headless-harness change. All host source-order guards still pass (§4).
- Known limit: until GameLoop ticks interleave with combat ticks (roadmap J/K, not decided), AI/rock poses inside the combat loop are frame-end poses. True per-tick geometry for AI ships comes only with that restructure.

**Cost mitigation, in order** (measure first: add sub-scopes for `iter_collidables` / bulk fetch / `_resolve_body` / broadphase / respond):

1. Broadphase on the bulk positions + `world_radius` **before** `_resolve_body`, and build `_Body`s only for objects in a candidate pair. Same results, since `_resolve_body` is a pure snapshot (COL:281-328) and positions already come from the bulk fetch (**inferred** saving: most of the call).
2. Build the collidable list once per frame. Refresh it after a tick that killed, spawned or moved an object between sets (the combat loop already rebuilds the ship list per tick, HL:12636-12639).
3. If the cost is still too high: keep the per-tick loop but cap collision passes on catch-up frames, e.g. run the last pass with the remaining game dt summed. Or, as an interim, one call per frame with `dt = _frame_game_dt`, skipped when N = 0. That gives game time at today's cost, but not a per-tick event boundary. It falls short of decision 10 and needs Mark's ruling.
4. Long term: the broadphase and narrowphase in C++, with the event + damage queued as one entry (decision 10).

**E1M2 rule preservation:** nothing inside `tick_collisions` changes. `_respond_pair` still posts `ET_PLANET_COLLISION` → `ET_CLOAKED_COLLISION` → `ET_OBJECT_COLLISION` (A, B) synchronously before the impact `apply_hit`s (COL:849-906). Keeping the call outside the effect scope keeps it synchronous. `test_moving_asteroid_hitting_haven_counts` (test_e1m2_rocks.py:80-110), the Facility test (:113-156) and `test_collision_event_precedes_the_impact_damage` (`tests/unit/test_collision_event.py:205-250`) keep pinning it unchanged. Gaps the inventory notes (line 255) and this move does not close: no test pins `FiringPlayerID` attribution through the collision path, and no host-level test runs collisions inside the real `run()` loop.

E3M1 (`docs/reference/engine/campaign-bug-decisions-2026-11-02.md:9`, `:21-35`, main checkout): "collisions unchanged" (events, then damage, no veto). The move does not touch it.
