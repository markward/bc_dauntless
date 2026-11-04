# Golden fights for the motion and whole-tick phases

**Status:** reading notes, 2026-11-03, for phases 2 and 4 of `docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md` (NMP). Nothing was built, run or measured. Facts carry file:line; anything else is marked **inferred**.

**Sources and their state**

- **WT** = the fire-control worktree `.claude/worktrees/native-combat-k3` (branch `ws/native-default`). It is work in progress: `tests/helpers/golden_fight.py`, `tests/integration/test_golden_fights.py`, `test_native_k1_differential.py`, `posed_fight.py`, `k3_fight.py` and two fixtures are modified and uncommitted. WT line numbers are for the working tree as read. **Re-read after that project merges.**
- **CT** = branch `project/combat_threading` (`2369cba41`). `engine/host_loop.py`, `engine/core/loop.py` and `engine/appc/ship_motion.py` are identical on CT and `ws/native-default`, and WT has no uncommitted edits to them (`git diff --stat` is empty). So the CT line numbers hold for WT too. WT's `engine/appc/subsystems.py` is modified: `impulse_fractions` is CT `:3705` and WT `:3717`.
- Fire-control spec **FS** = WT `docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md`. Plan = WT `docs/superpowers/plans/2026-11-03-fire-control-native-only.md`. Map **KRM** = WT `docs/reference/engine/native-combat/k1-retirement-map.md` §5.5 and §7 R9-R10.

---

## 1. How the harness works

### 1.1 Files

| File | Role |
|---|---|
| WT `tests/helpers/golden_fight.py` (885 lines) | Scene table, run, canonical rows, file encoding, record, check |
| WT `tests/integration/test_golden_fights.py` (187 lines) | One test per scene (`:59-84`), plus three tests of the recorder (`:89-187`) |
| WT `tests/fixtures/golden_fights/<scene>.<sys.platform>.json.gz` | One file per scene. Only `darwin` files exist |
| WT `tests/integration/test_native_k1_differential.py` (imported as `k1d`) | `_Scene` (`:136`), `record` (`:462`), `run` (`:535`), `OPS` (`:593`), `handler_arm` (`:810`), `_deterministic_loop` (`:1052`), `_loop_arm` (`:1072`), `_seed_every_rng` (`:121`) |
| WT `tests/helpers/posed_fight.py` | `PosedFight` (`:216`), `run` (`:794`) |
| WT `tests/helpers/k3_fight.py` | `Recorder`, `spy_presentation` (`:340`), `split_calls` (`:422`) |
| WT `tests/helpers/effect_split.py`, `fight_audio.py`, `headless_mission.py` | Queued-event split, audio isolation (`fight_audio.py:29`), mission load and `clear_in_flight` (`headless_mission.py:27, 42`) |

The scenes are the differentials' own fights, imported rather than copied (`golden_fight.py:7-21`; plan Task 1: "Import or move them; don't copy them").

### 1.2 What a scene is

- `Scene(name, arm, seed, ships, ticks, tpf, run)` (`golden_fight.py:131-138`).
- `run(mp, env, spec)` returns a `_Take(state, events, queued, calls, notes)` (`:141-148`).
- `arm` is `"python"` (`k1d.OFF`, `DAUNTLESS_NATIVE_COMBAT=0`) or `"native"` (`k1d.ON`) (`:90`). Scene code tells the arms apart by identity (`env is ON`), for example `_posed` maps it to `posed_fight`'s own constants (`:300`).
- `run_scene(name, arm)` (`:679-690`) does four things in order:
  1. `gc.collect()`;
  2. opens a `pytest.MonkeyPatch.context()`;
  3. `_patch_records(mp)`, which makes `k1d._Scene.record` and `k3_fight.Recorder.record` append pose, tractor and tube rows after their own record (`:220-235`);
  4. `random.seed(spec.seed)`, then the scene's `run`.
  It returns `_canonical(take)`.
- `_canonical` (`:652-676`) builds one tuple per tick, tick 0 first: `(tick, state, events, queued, calls, presented, notes)`.
  - Tick 0's state is `[]`.
  - Events and queued rows are bucketed by their field 3 (the tick); calls and notes by field 1 (`_by_tick`, `:643-649`).
  - `presented` is a per-tick sorted multiset from `k3_fight.split_calls`.
  - Dynamic event types (1200 to 0xFFFF) are renamed `dyn#N` by first sight (`:634`, `:661-668`).
  - The whole thing is JSON-normalised (`:639-640`).

### 1.3 What is recorded per tick

**State rows** are `[kind, label, fields...]`. `FIELDS` (`:97-126`) names the fields.

- From `k1d._Scene.record` (`k1d:462-532`):
  - `system`: IsFiring, `_fire_held`, `_force_update`, `_last_weapon_idx`, `_last_group_fired`, `_group_fire_mode`, `_held_target`, `_target_list`, and whether the list object is new;
  - `weapon`: IsFiring, `_target`, `_fire_timer`, `_depleted`, `_charge_level`, `_cooldown_remaining`, `_num_ready`, `_target_offset`, the offset-object identity classes, `_beam_on_countdown`, asleep-not-at-rest;
  - `ship`: IsDead, hull condition, six shield faces;
  - `torpedo`: `torp_row`.
- Added for every scene (`golden_fight.py:153-217`):
  - `pose`: `GetWorldLocation`, `GetWorldRotation().as_tuple()` (9), `GetVelocityTG()`;
  - `tractor`: `_mode`, `_engage_state`, `_was_firing`, `_next_emitter_index`, IsEngaged;
  - `tube`: `_reload_timers`, `_last_fire_time`.
- The posed fight uses `k3_fight.Recorder`'s row plus `psystem`, `pweapon` and `posed` rows (`:298-319`). The kinds `record` and `posed` have no `FIELDS` entry, so a failure in them names the field `?` (`:818-820`).

**Encoding rules**

- Floats are `float.hex()`, wrapped by type as `("float", hex)` in `k1d._t` (`k1d:99-103`) or as plain hex lists in `_hexes`.
- Objects are named by ship name, `ship/subsystem`, or first sight (`Torpedo@N`, `<Type>#N`). Never `id()` or a handle (`k1d:275-295`).

**Other components**

- `events`: every `AddEvent` except the queued kinds, as `(type, source, destination, tick, payload)` (`k1d:205-219`; `EVENT_FIELDS`, `golden_fight.py:128`).
- `queued`: effect-queue kinds and bank sounds, in delivery order (`effect_split.Queued`).
- `calls`: `apply_hit` (target, damage, point) and the presentation spies (`k1d:224-232`).
- `notes`: the scene's own listeners (only `tractor_modes` uses them).

**Motion state is recorded only through `pose`.** Position, rotation and `_velocity` are recorded. The recorder never reads `_current_speed`, `_current_angular_velocity`, `_drift_velocity`, the setpoints, the scripted `_angular_velocity` or `_angular_space`, `_insystem_warp_transit`, `_warp_consumed`, the warp state, or the impulse fractions.

### 1.4 File, check, re-record

**File**

- Each tick's state is stored as its changes since the tick before (`:709-755`): unchanged rows are left out, and a row whose `(kind, label)` was in the previous tick stores only its differing fields.
- The file also holds one SHA-256 per tick (`_digest`, `:699-701`) and a header (`:772-776`): scene, arm, seed, ships, ticks, tpf, `schema`, platform, reason.
- It is written gzip with `mtime=0` (`:781-784`), so a re-record of identical rows gives identical bytes.

**Check** (`:851-885`)

- No file for `sys.platform` → skip, naming the missing file (R9).
- The schema must equal `SCHEMA` (3, `:87`) or have a reader in `_UPGRADES` (2 → 3 drops torpedo `_baked_offset`, `:833-848`).
- The rows are compared, not only the digests. The first difference is named as tick, component, row kind and label, and field name (`_describe`, `:803-830`). The stored digest must still match its stored row.

**Re-record** (`test_golden_fights.py:12-19`; `record`, `golden_fight.py:762-786`)

- Command: `UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON="<why>" uv run pytest tests/integration/test_golden_fights.py::<test>`.
- With no reason it fails; with one it writes the file and skips.
- `COMBAT_GOLDEN_ARM=python|native` overrides a scene's arm (`test_golden_fights.py:53`).
- **The gate is a rule, not code:** "A golden is re-recorded only in a commit whose message names the behaviour change and the scenes it touched. An unposed scene that moves is a bug, not a re-record" (plan, Global Constraints). `SCHEMA`'s comment says "bump it on any change to it or to the rows" (`:87`).
- The test module skips unless `_dauntless_host` has `combat_k1_next` (`test_golden_fights.py:34-36`), and needs BC assets (`:41`).

### 1.5 Determinism (R9, R10)

- **R9 (FS §3):** goldens are per platform. KRM R9 gives the reason: libm `atan2`/`asin`/`sqrt` and CPython's `math.dist` port may round differently (**inferred**, untested).
- **R10 (FS §3, KRM R10):** a scene seeds every RNG, runs `clear_in_flight`, runs `gc.collect()` at load and isolates fight audio. Concretely:
  - **Seeding:** `k1d._seed_every_rng` (`:121-133`) seeds module `random`, `App.g_kSystemWrapper.SetRandomSeed`, the avoidance RNG, the random-unit-vector RNG and `presentation_rng`. `_Scene.__init__` calls it with 0 before the load and resets `App.g_kTimerManager._time = 0.0` (`k1d:154-155`). `_loop_arm` calls it again with `SEED` before the loop (`:1113`). `run_scene` also seeds `random` with `spec.seed`.
  - **In flight:** `headless_mission.clear_in_flight()` (`headless_mission.py:42-56`) clears `IN_FLIGHT`, explosion lights and the effect queue.
  - **Audio:** `isolate_fight_audio` (`fight_audio.py:29-39`) clears recent tactical sounds and the hit-audio throttle, puts crew speech on game time, and resets crew timestamps.
  - **GC:** `gc.collect()` in `run_scene` (`:684`) and between the GameLoop scenes' warm-up and real arms (`:281`, `:586`).
  - **Process-wide ids:** `_deterministic_loop` (`k1d:1052-1069`) keys the avoidance preprocessor's phase on the ship name, not `GetObjID()`.
  - **Warm-up arm:** the GameLoop scenes first run a discarded arm of `LOOP_TICKS`=1500 ticks, because "the first combat_stress fight in a process diverged from every later one" (`golden_fight.py:272-285`; `k1d:1139-1146`). That doubles their cost.
  - **Environment:** `DAUNTLESS_MODS_DIR` points at an empty folder; `OPEN_STBC_HOST_HEADLESS` is unset so radii come from models (`k1d:152`).

### 1.6 Fixture sizes

| Scene | Ticks | tpf | Header arm | Schema | Size committed (HEAD of WT) | Working tree |
|---|---|---|---|---|---|---|
| `k1_gameloop_ai` | 1500 | 1 | python | 2 | 1,952,371 | same |
| `k1_midwalk_handler` | 300 | 1 | python | 2 | 617,236 | same |
| `k1_ops_tpf1` | 600 | 1 | native | 3 | 1,770,272 | 1,768,541 (D5 re-record, uncommitted) |
| `k1_ops_tpf6` | 600 | 6 | python | 2 | 1,075,347 | same |
| `posed_fight` | 660 | 1 | native | 3 | 1,451,759 | 1,451,718 (D5, uncommitted) |
| `sdk_dumb_fire` | 900 | 1 | python | 2 | 1,255,786 | same |
| `tractor_modes` | 870 | 1 | python | 2 | 60,562 | same |

The total is about 8.2 MB. Each file holds roughly 1 KB per tick for 9 ships with about 230 rows per tick.

---

## 2. Per scene: is motion exercised, and in what order are ticks run

**The driver question.** No scene goes through `host_loop.run()`. Scenes call `engine.core.loop.GameLoop.tick` or `game_loop._update_ship_subsystems`, then `host_loop._advance_weapons`, `host_loop._advance_combat` and `host_loop._combat_tick_boundary`, all directly. Only two scenes call `GameLoop.tick`, so only they run `gl.motion` (`loop.py:105-106`, `tick_all_ship_motion`).

### 2.1 Batched, like today's host frame: `k1_ops_tpf1`, `k1_ops_tpf6`, `k1_midwalk_handler`

`k1d._Scene.run` (`k1d:558-583`):

```python
while self.tick < ticks:
    ...
    for _ in range(rng.randint(0, 2)):
        op()
    for _ in range(ticks_per_frame):
        App.g_kTimerManager._time += TICK_DELTA
        game_loop._update_ship_subsystems()
    for _ in range(rng.randint(0, 2)):
        op()
    for _ in range(ticks_per_frame):
        self.tick += 1
        ships = list(iter_ships())
        with tick_scope():
            host_loop._advance_weapons(ships, TICK_DELTA)
            host_loop._advance_combat(ships, TICK_DELTA,
                                      player=self.player,
                                      push_render_data=False)
        host_loop._combat_tick_boundary()   # as the host does (native damage)
        self.record()
        if rng.random() < 0.3:
            op()
    sensor_contacts.tick(self.player, App.g_kUtopiaModule.GetGameTime())
```

- This is all subsystem ticks, then all combat ticks, the host's batched shape. The `tpf1` scene runs it with one tick per frame, `tpf6` with six; `k1_midwalk_handler` uses tpf 1 and opens `effect_queue.scope()` around each tick and each op in both arms (`scope="both"`).
- **No `GameLoop.tick`:**
  - the timer is bumped by hand, so no timers fire;
  - there is no AI, no proximity, no warp states;
  - **no motion**: `tick_all_ship_motion` never runs.
- Poses change only by the ops `move` (teleport plus `SetVelocity`), `turn` and `face` (`k1d:430-449`). The velocity is stored and never integrated.
- Decoding the files read-only bears this out:
  - `k1_ops_tpf1`: positions change on 1-6 ticks per ship, velocity is non-zero on up to 575 ticks;
  - `k1_midwalk_handler`: no position change at all.

### 2.2 Batched, posed: `posed_fight`

`PosedFight.run` (`posed_fight.py:800-826`) has the same shape: `sync_render()` once per frame (a no-op headless), then `_update_ship_subsystems` × tpf, then per tick the beats, weapons and combat, the boundary and the record. There is no motion. The ops only teleport: velocity stays zero for the whole file.

### 2.3 Host-style ticks, no GameLoop: `tractor_modes`

`_tractor_modes` (`golden_fight.py:489-525`):

```python
while scene.tick < spec.ticks:
    scene.tick += 1
    ...beats, tow turn, starvation...
    App.g_kTimerManager._time += TICK_DELTA
    game_loop._update_ship_subsystems()
    ships = list(iter_ships())
    with host_loop._combat_effect_scope():
        host_loop._advance_weapons(ships, TICK_DELTA)
        ...
        host_loop._advance_combat(ships, TICK_DELTA,
                                  player=scene.player,
                                  push_render_data=False)
    host_loop._combat_tick_boundary()
    scene.record()
    sensor_contacts.tick(...)
```

- This runs whole ticks at tpf 1, with no motion.
- Poses move by the **tractor force**, then in `cb.tractors`; since phase 2 Task 7 in the motion stage's `motion.tractors`, called here as `ship_motion.tick_tractors` (Enemy-1 moves on 641 ticks, the Player on 510) and by the scripted turns. This is the pose writer of NMP open question 1.

### 2.4 Whole ticks through GameLoop: `k1_gameloop_ai`, `sdk_dumb_fire`

`k1d._loop_arm` (`k1d:1084`, `:1115-1127`):

```python
loop = game_loop.GameLoop()         # configure() reads the env
...
while scene.tick < ticks:
    scene.tick += 1
    loop.tick()
    ships = list(iter_ships())
    with host_loop._combat_effect_scope():
        host_loop._advance_weapons(ships, TICK_DELTA)
        host_loop._advance_combat(ships, TICK_DELTA,
                                  player=scene.player,
                                  push_render_data=False)
    host_loop._combat_tick_boundary()   # as the host does (native damage)
    scene.record()
    sensor_contacts.tick(scene.player, App.g_kUtopiaModule.GetGameTime())
```

- **This is ruling 2's order already**: AI, motion and subsystems, then combat, then the boundary, at tpf 1. `sdk_dumb_fire` is the same arm with `combat_stress._AI_DIFFICULTY = 0.0` (`golden_fight.py:577-603`).
- **Not the host's boundary placement.** The scene builds `GameLoop()` with the default `owns_boundary=True`. So every `GameLoop.tick` ends with its own `effect_queue.boundary()` and `native_combat.drain(boundary=True)` (`loop.py:131-136`), before combat runs. The host builds `GameLoop(owns_boundary=False)` (CT `host_loop.py:11740`), so the GameLoop tick's held effects are delivered at the combat tick boundary, after combat. Phase 4 has to decide which of the two the new order means (**inferred**: ruling 2's "then the combat tick boundary" is `owns_boundary=False`).

**What motion these two goldens exercise** (decoded read-only; branch attribution **inferred**):

- **Branch 6, powered ramp:** all 8 AI ships move on every tick (`k1_gameloop_ai`: 1499 of 1500 ticks). Peak speeds are 1.24 to 5.70 GU/s, and up to 7.5 in `sdk_dumb_fire`.
- **Branch 5, every pod out:** in `k1_gameloop_ai`, Enemy-3's velocity is bit-identical from tick 515 to 1500 while its rotation keeps changing (rotation changes on 1485 ticks). That fits branch 5's frozen `_drift_velocity` plus `_integrate_rotation`. Its hull reaches 0 by tick 600 and IsDead is set at 982. Pods destroyed, or the death sequence, could explain it equally; this is not checked.
- **Branch 4, the manual-player exclusion:** the Player has no AI (`combat_stress.py:247-249` creates it; only `created` ring ships get `SetAI`, `:290-327`) and never moves. Branch 4's `drift.step` itself is not exercised: every other ship has setpoints.
- **Not exercised:**
  - branch 1, immobile;
  - branch 2, in-system warp (no `ET_IN_SYSTEM_WARP`, `0x8000ef`, in any golden);
  - branch 3, arriving;
  - the fallback limits (no ship lacks authored IES limits).
- So NMP §5.2's "the goldens pin motion bit-exactly, since `k1_gameloop_ai` runs GameLoop" is true for the ramp and probably total loss. It pins them only through position, rotation and `_velocity`: a bit difference in `_current_angular_velocity` shows up one tick later in rotation, and one in `_drift_velocity` shows up in velocity. The failure message names the pose row, not the state field.

---

## 3. What a motion-focused scene needs

### 3.1 The branches to cover (`ship_motion.py:173-338`, CT)

| # | Branch | Where | How a scene reaches it |
|---|---|---|---|
| 1 | Immobile: return before anything else | `:198-199` (`IsImmobile`, `objects.py:966`) | `SetStatic(1)` (`objects.py:717`) or `SetStationary(1)` (`:962`) on a ship that also has a setpoint |
| 2 | In-system warp: `warp_flight.step` returns True → return; False (an "ai" flight holding for parts) → fall through to the impulse path | `:205-207`; `warp_flight.py:324-350` | `ship.InSystemWarp(target, distance)` (`ships.py:758-836`): target beyond radius + distance and nose on it (`IN_SYSTEM_WARP_FACING_COS`), which starts a `WarpFlight(speed_policy="ai")` and posts `ET_IN_SYSTEM_WARP`. A rigged ship (Bird of Prey) gets `_parts_hold > 0` (`warp_flight.py:253-279`), the fall-through case. For a heading flight: `begin_warp_flight(WarpFlight(target=None, ...))` (`ships.py:838-842`). Put the warp ship **between** other rows, so the kernel's segments (NMP §5.2) are tested with ships before and after it |
| 3 | Arriving: return | `:212-213`; `warp_state.is_arriving` (`warp_state.py:97-104`) | A dewarp drive: `sub.SetPlacement(p)`, `SetWarpState(WES_WARPING)`, `TransitionToState(WES_DEWARP_INITIATED)` (`tests/unit/test_dewarp_drive.py:84-88`), or `loadspacehelper.CreateShip(..., 1)`. Needs `GameLoop.tick`: `tick_warp_states` runs there before motion (`loop.py:97-99`). The slide is 2.0 s |
| 4 | No setpoints: `drift.step` unless the ship is the current player | `:215-231`; `drift.py:45-76` | A ship with no AI, never given a setpoint, with `SetVelocity` and `SetAngularVelocity(v, MODEL_SPACE)` (post-multiplied), and a second with world-space spin (pre-multiplied). The player with no setpoints must not move |
| 5 | Every pod out: `_drift_velocity` snapshot, translate, `SetVelocity`, `_integrate_rotation` | `:256-271` | Powered flight, then every IES child `SetCondition(0)`, or `IsDisabled`, so `impulse_fractions(ies)[0] <= 0` (CT `subsystems.py:3705`). Then repair one pod: the snapshot clears and `_current_speed` is re-seeded from `drift_vec.Length()` (`:274-277`) |
| 6 | Powered ramp with caps | `:279-322` | Setpoints above `max_speed` (cap), partial pod damage below the current speed (`_cap_keep` does not brake, `:134-146`), reverse speed, an angular setpoint above `max_ang_vel`, IES `TurnOff` (output fraction 0, so the limits are 0 but `f > 0`), power slider `SetPowerPercentageWanted(0.5)`, model-space and world-space directions, `sp is None` with `av` set (`:234-236`) |
| 6' | Fallback limits | `:91-131`, `:282-288`, `:310-317` | `has_linear`/`has_angular` False: an IES whose authored max speed and max angular velocity are 0, or no IES at all (`ies is None` → `impulse_fractions` returns `(1.0, 1.0)`). Both give `FALLBACK_MAX_ACCEL` snaps. A bare `ShipClass()` added to the set, as `tests/unit/test_ship_motion.py:27-32` does |

The latent `_radiation_out` gap (NMP §5.2): give a pod `_radiation_out = True`. The fused walk ignores it under `_ship_known_good`, while `impulse_online_fraction` does not.

### 3.2 What the recorder lacks

The pose row has velocity (`_velocity` through `GetVelocityTG`, `objects.py:653-654`). It lacks the motion state. Add a `motion` row kind, written only by the new scenes:

```
"motion": ("name", "_current_speed", "_current_angular_velocity",
           "_drift_velocity", "_speed_setpoint", "_target_angular_velocity_setpoint",
           "_angular_velocity", "_angular_space", "warp_flight",
           "_warp_consumed", "warp_state", "arriving",
           "impulse_fractions", "effective_motion")
```

- Floats are hex.
- `warp_flight` is `None` or `[target label, speed_policy, _parts_hold, _held, ended_reason]`.
- `impulse_fractions` is `(online, output)` from one `subsystems.impulse_fractions(ies)` call. It is a pure read: no writes beyond `_is_offline` (**inferred**).
- `effective_motion` is the six `_effective_motion` values.
- Read through `getattr`, so the recorder keeps working when phase 2 makes these attributes row-backed (NMP §5.2).

**Schema.** Rows only the new scenes write do not change any existing file. Adding the kind to `FIELDS` needs no `SCHEMA` bump (**inferred** from `check`'s rule, `:862-866`). Adding `motion` rows to every scene would change every file: a bump, plus a re-record of all seven scenes in one deliberate commit.

**Arms.** `ARMS` (`:90`) knows only the combat switch. Fire control becomes native whatever the switch says (FS M9), and `=0` keeps governing K0/K2/K3/K4. A motion scene needs a motion switch (for example `DAUNTLESS_NATIVE_MOTION`, name not decided). Either extend `ARMS` with motion entries, or let the scene's `run` read a second switch.

### 3.3 Driver shape for the motion scene

- Drive with `GameLoop(owns_boundary=False).tick()` then `host_loop._combat_tick_boundary()` per tick, as the host does (CT `host_loop.py:11740`, `:12708`).
- The scene can skip `_advance_weapons` and `_advance_combat`: nothing fires. Keep the tractor out of it; NMP open question 1 decides where the tractor force sits.
- It does not need `k1d._Scene`. `_Scene.__init__` asserts the ship count and freezes its ship, system and label lists at construction (`k1d:165-189`), so ships added afterwards are never recorded. Write a small scene class that reuses `_seed_every_rng`, `clear_in_flight`, `isolate_fight_audio`, `effect_split.Queued` (for `ET_IN_SYSTEM_WARP` and other events) and the `_pose_rows` helper.
- With no AI on the scripted ships, there are no AI draws. The seeding stays for safety. Neither the warm-up arm nor `_deterministic_loop` is needed (**inferred**: both exist for combat_stress's AI). If the scene keeps combat_stress's two AI ships, keep both.

---

## 4. What a frame-level scene needs (phase 4)

### 4.1 The frame's sim section (CT `engine/host_loop.py`)

Order inside `run()` (`:10734`), from `frame_profiler.mark("sim")` (`:12373`) to the end of `sim.render_xforms` (`:13063`):

1. **Freeze, clock, ticks**
   - `pause.set_external_freeze(_devtools_frozen(_h))`;
   - `_frame_clock()` (`:238`, patchable);
   - `step_accumulator(_accumulator, _frame_dt, TICK_DT, MAX_FRAME_DT)` (`:12397`; `timestep.py:11-34`; `TICK_DT = 1/60`, `MAX_FRAME_DT = 0.25` at `:11778-11779`);
   - `_player_dt`, `_frame_game_dt`, `_interp_alpha`;
   - `advance_ticks(_xform_buf, n, _tick_gameloop, _interp_live_poses)` (`:12425`; `transform_buffer.py:65-87`: `roll()` once, `n` GameLoop ticks, re-seat prev before the last).
2. **Between the ticks and combat**
   - `warp.preload` (`:12429`);
   - on a frame with ticks, the mission-swap drain and its resets (`:12434-12464`);
   - `sim.session_sync` (`:12467`): preload-done event, object deletions, Quick Battle panel, then `_sync_player_identity`;
   - `sim.keys` (`:12520`): scroll routing; dev keys, F12 and Cmd+R under the pause menu.
3. **`sim.input`** (`:12569-12665`): alert keys, camera keys, `_apply_input` (the manual player integrator, `_player_dt`), the bridge officer click, `_poll_mouse_buttons`, `_poll_function_keys`, `_poll_fire_keys`, `_poll_modifier_chords`, `_poll_raw_keyboard`, `_poll_skip_dialogue`, and `manual_aim.update` (`:12665`).
4. **Combat ticks** (`:12685-12708`): the ship list, then `for _tick_i in range(_sim_ticks_this_frame)`. Each tick runs `_combat_effect_scope()` around `_advance_weapons` and `_advance_combat(..., ship_instances, ship_emitters, player, push_render_data=False)`, then `_combat_tick_boundary()`.
5. **Once per frame after combat:**
   - `sensor_contacts.tick`, crew hazard prompts;
   - the nebula tracker and radiation driver, per tick (`:12752`);
   - thunder, hull discharge and wake;
   - `sync_flythrough`;
   - debris chunks (`_player_dt`, `r`);
   - `collisions.tick_collisions(_player_dt, ship_instances)` (`:12897`);
   - rock breakup, minor and scenery contact, rock promotion;
   - `_effect_queue.boundary()`, the frame-end boundary (`:12920`);
   - `dash.tick`, `handoff.tick`.
6. **`sim.reconcile`** (`:12960`): `_reconcile_scene(session, controller.renderer, ...)` (`:7635`) realises and tears down instances, and loads the system.
7. **`sim.render_xforms`** (`:12985-13063`): player interpolation, hand-off rebase, view rebase, the handover smoother, `_make_render_pose_provider`, then `_sync_instance_transforms(r, session, ...)` (`:10087`). That last call updates glow, emissive and articulation and pushes the interpolated poses: the poses K2 traces and Manual Aim read next frame (NMP §2.3).

### 4.2 What the section depends on

**`run()` locals it reads** (static scan of `:12381-13077`; the module-level names are excluded):

- **Host and render:** `_h` (host module), `r` (module import `engine.renderer`, `:17`; needs the built `.so`).
- **Controller and session:** `controller` (`.session`, `.pending_swap`, `._drain_pending_swap()`, `.renderer`; `HostController`, `:7799`). `session` (`MissionSession`, `:6711`) comes through `controller.session`.
- **Camera and view:** `director` (`chase` and `tracking.set_ship_radius`, `snap`, `toggle_mode`, zoom and reverse, `start_zoom_target`), `view_mode`.
- **Player and pause:** `player_control` (`_PlayerControl`, `:3055`), `pause` (`sim_frozen`, `is_open`, `set_external_freeze`).
- **Interpolation:** `_xform_buf`, `_handover`, `_interp_live_poses`, `_tick_gameloop` (closes over `loop`), `_snap_scene`.
- **Input:** `input_map`, `_consume_scroll`, `_cef_send_wheel`, `_cursor_in_panel`, `_mx`, `_my`.
- **Panels:** `crew_menu_panel`, `perf_monitor_panel`.
- **Swap-only resets:** `cutscene`, `bridge_camera`, `char_anim`, `walk_ctrl`, `watch_ctrl`, `idle_gestures`, `node_anim`, `lip_runtime`, `_letterbox_anim`, `_close_star_map`.
- **Other:** `collisions`, `verbose`, `TICK_DT`, `MAX_FRAME_DT`, `step_accumulator`, `advance_ticks`.

**Loop-carried state it writes:** `_accumulator`, `_previous_real_time`, `z_held_prev`, `v_held_prev`, `_bridge_left_pick_active`, `_prev_interp_player`, `_prev_player_set`, `_prev_view_set`, `_prev_drawn_player_pose`.

**Module globals it creates:** `_crew_hazard_prompts`, `_nebula_tracker`, `_radiation_driver`, `_nebula_thunder`, `_hull_discharge`, `_nebula_wake`, and `_warp_hidden` inside `_sync_instance_transforms`.

**Outputs the render half reads after `:13077`:** `_ships_this_tick` (`:13296`), `_pose_of` (`:13132`), `_player_interp_pose`, `_interp_player`, `_interp_alpha`, `_sim_ticks_this_frame`, `_frame_dt` (`:13823-13832`), `_player_dt` (18 reads), `_frame_game_dt` (`:13643`), `_wall_dt` (`:13687`), plus `session` and `player`.

**Hard dependencies on GL, window, CEF or input**

- `engine.renderer` imports `_dauntless_host` unguarded (`renderer.py:9`).
- `_reconcile_scene` realises models (GL) once a session exists.
- `_sync_instance_transforms` calls `r.set_world_transform`, `r.set_emissive_scale` and others.
- `_debris_chunk.tick(_, r)`; `r.nebula_lightning_enabled()` and `r.volumetric_nebulae_enabled()` whenever an active set exists; `r.instance_surface_points`.
- `bridge_officer_picking.handle_click(_h, r, ...)` on the bridge only.
- `host_io` input reads no-op when `_h` is None (`host_io.py:30-33`).
- `_poll_mouse_buttons` and `_poll_modifier_chords` return on `None` (`:391`, `:498`). The other pollers' None handling was not checked.
- `manual_aim.update` returns on `player is None` and otherwise needs the TCW and instances.
- CEF matters only through `_cef_send_wheel` and the pause-menu keys (F12, Cmd+R).

### 4.3 What has to be stubbed or extracted

- **Extract** the sim section into a callable with an explicit context object: the dependencies above as attributes, the loop-carried state as fields, and the outputs as a returned record. Take `frame_dt` as an argument, or keep `_frame_clock` patchable.
- **For a GL-free golden, inject:**
  - a fake `_h` whose `keys` constants exist and whose reads return False (it must mirror the real surface, per project memory "doubles mirror surface"), or `_h=None`;
  - stubs for `director`, `view_mode` (exterior) and `pause` (`sim_frozen=False`, `is_open=False`);
  - a controller holding a `MissionSession(mission_name=...)` with the player, empty `ship_instances` and `pending_swap=None`.
  - `_reconcile_scene` must then become an injected step (a no-op headless), because a real reconcile realises models. Alternatively use the GL tier below.
- **GL tier** (pins ruling 3 effects as well): `r.init(256, 256, ...)` on a hidden window, `host_loop.MissionSession` and `host_loop.realize_set_objects(session, set, r, include_planets=False)`, exactly the `host` fixture of `tests/host/test_native_posed_differential.py:71-91` and `posed_fight.py:243-246`. No CEF and no `run()`.
- **Repoint the source-structure guards.** About 25 tests read `inspect.getsource(host_loop.run)` and assert call order inside it. Moving the section out of `run()` breaks every one that names a call in it. Among them:
  - `tests/host/test_scene_reconcile_ordering.py:26-60` (`loop.tick()`, `_advance_combat(` and others before `_reconcile_scene(`);
  - `tests/integration/test_damage_queue_order.py:144-150`;
  - `tests/unit/test_effect_queue.py:223-229`;
  - `tests/unit/test_native_deferred_frees.py:590+` (the `sim_frozen` drain);
  - `tests/host/test_warp_state_host_wiring.py:41-48`;
  - `tests/host/test_frame_rate_independence.py`'s structural guard ("TICK_DT only inside `for ... in range(_sim_ticks_this_frame)`");
  - also `test_contacts_pump`, `test_dash_render_continuity`, `test_view_set_rebase`, `test_camera_dt_wiring`, `test_viewscreen_bars_game_loop_call`, `test_letterbox_pump`, `test_render_space_feeds`, `test_minor_contact`, `test_minor_rocks_mission_swap`, `test_running_lights_host_push`, `test_spv_anchor_pose`, `test_spv_part_box_overlay`, `test_warp_preload_host`, `test_foundation_sounddef`, `test_far_host_wiring`, `test_paths_resolve`, `test_host_loop_first_run`, `test_boot_notice_pump`, `tests/cameras/test_speed_fov.py`.

  Each must read the new callable's source, or `run()` plus it. The extraction commit has to carry them.

### 4.4 Existing tests that drive the host frame headlessly

- **Through `hl.run()`**, with `OPEN_STBC_HOST_HEADLESS=1` (a hidden window, still a real GL context and `cef_initialize`, `:10824`), a patched `_frame_clock` and `max_ticks` = **frames** (`ticks += 1` per frame, `:13843-13845`):
  - `tests/host/test_frame_rate_independence.py:39-104` (M1Basic, 15 and 120 fps, 40 frames);
  - `tests/host/test_native_combat_scene_audit.py:42-103` (combat_stress, 16 ships, frames of 0.1 s, about 6 ticks each, 120 frames);
  - `tests/host/test_passive_state_scene_audit.py` (combat_stress, 120);
  - `test_host_loop_unit.py`, `test_host_loop_lighting.py`, `test_host_loop_planets.py`, `test_sun_integration.py` (M1Basic, 2-5 frames).

  None of these seeds the sim's RNGs inside `run()`; the mission loads inside it. They are not golden material as they stand (**inferred**).
- **Pieces with fakes:** `tests/host/test_handover_continuity.py` (`_drive_handover_smoother`, `_make_render_pose_provider` with a `_FakeShip` and `_FakeSession`).
- **Real instances without `run()`:** `tests/host/test_native_posed_differential.py` (`host` fixture).
- **Fixtures:** `bc_assets.require_game_dir` / `GAME_ROOT`, an empty `DAUNTLESS_MODS_DIR`, a module-scoped `r.init` / `r.shutdown`. There is no `tests/host/conftest.py` on CT.

---

## 5. Sketch of the two new scenes

### 5.1 `motion_branches` (phase 2; record from the Python motion, check native)

- **World:** `headless_mission.load("engine.dev_missions.combat_stress")` with `DAUNTLESS_COMBAT_SHIPS=2`, the same RNG, audio and in-flight setup as `_Scene.__init__`. Add scripted ships to `QuickBattleRegion` with `loadspacehelper.CreateShip`, so their IES has real pods. Add one bare `ShipClass()` with no IES. The two AI ships can keep fighting far away, or be `SetAI(None)`.
- **Cast, in set order** (row order decides the kernel's segments; set iteration is insertion order, **inferred**):
  1. `Anchor`: Galaxy, `SetStatic(1)`, with a speed setpoint written (branch 1);
  2. `Ramp`: Galaxy, scripted setpoints (branch 6 beats below);
  3. `Warper`: Galaxy facing `Target` 600 GU away; at tick 30 `InSystemWarp(Target, 50)`, flight to the drop and exit (branch 2);
  4. `WarperBoP`: Bird of Prey (rigged), `InSystemWarp` at tick 30. Parts hold, then flight (branch 2's False path, falling through to its setpoints);
  5. `Arriver`: Galaxy with a dewarp drive started at tick 20 onto a placement (branch 3), then setpoints after arrival;
  6. `Drifter` and `DrifterW`: no AI and no setpoints, `SetVelocity` plus model-space and world-space `SetAngularVelocity` (branch 4);
  7. `Cripple`: ramping. At tick 200 every pod gets `SetCondition(0)` (branch 5 snapshot, with spin held). At tick 400 one pod is repaired (re-seed from `drift_vec.Length()`). One pod carries `_radiation_out = True` throughout;
  8. `Bare`: `ShipClass()` with no IES, plus a second with an IES whose authored limits are 0 (fallback snaps, branch 6');
  9. `Target`: a still ship for the warp. The Player: no setpoints (never moved), then a speed setpoint at tick 500 (into the ramp).
- **`Ramp` beats:** speed above max (cap); pods to 50% while above the new cap (no brake); reverse; angular setpoint above `max_ang_vel`; `SetPowerPercentageWanted(0.5)`; `TurnOff` / `TurnOn`; world-space direction; `sp None` with `av` set.
- **Driver:** per tick, the beats, then `GameLoop(owns_boundary=False).tick()`, then `_combat_tick_boundary()`, then the record. Use 700 ticks (covers the arrival slide, the 400-tick repair and the Player's 500-tick setpoint).
- **Rows:** `pose` plus the new `motion` row per ship, and events (`ET_IN_SYSTEM_WARP` true and false).
- **Self-checks, the "scene is what it claims" asserts:**
  - `Anchor`'s pose never changes;
  - a `warp_flight` was seen and ended;
  - `arriving` was True for about 120 ticks;
  - `_drift_velocity` was set, then cleared;
  - `Bare`'s speed equals its setpoint after one tick;
  - the Player did not move before tick 500.
- **Size:** about 2 KB per tick gzipped, so about 1.5 MB (**inferred** from §1.6).
- Doubles as NMP §5.2's "motion differential on scripted ships".

### 5.2 `host_frames` (phase 4; recorded through the extracted callable before the reorder)

- **World:** `k1d._loop_arm`'s setup (combat_stress, 8 ships, hull 5%, shields down, Friend-3 turned away, `_deterministic_loop`, `_seed_every_rng(SEED)`), with its discarded warm-up arm.
- **Driver:** the extracted frame-sim callable, GL-free tier (§4.3). A scripted frame-dt cycle covers multi-tick, single-tick and zero-tick frames, for example `[3, 1, 6, 0, 2]` ticks, each frame `k·TICK_DT + 0.3·TICK_DT`. The accumulator carry is then exercised but deterministic. Use about 300 frames (about 700 ticks).
- **Ops:** optionally, at frame start, the K1 op stream's `fire`, `stop` and `retarget` (no Manual Aim in the GL-free tier).
- **Record:** wrap `host_loop._combat_tick_boundary` (a module global looked up at call time) to call the original and then record. The rows are then taken at the same point before and after the reorder. Per frame, add a note `["frame", first_tick, n_ticks]`.
- **Reorder commit (ruling 2):** the same scene re-recorded. Its first difference falls on the first multi-tick frame's second combat tick (**inferred**). With it in the same commit: `k1_ops_tpf6`'s driver rewritten to whole ticks (subsystems then combat, per tick; its between-batch ops move to frame start, the same RNG draws in the same order), and its re-record.
- **Size:** similar to `k1_gameloop_ai`, about 1-2 MB (**inferred**).

---

## 6. Things that block or slow phases 2 and 4

1. **The harness is uncommitted work in progress** in WT, and plan Task 6 turns the K1 differential's Python comparisons into goldens. `golden_fight.py` imports `_Scene`, `OPS` and `_loop_arm` from `test_native_k1_differential.py`, which may move or shrink. Build on whatever lands after the fire-control merge.
2. **No motion fields are recorded**, and branches 1-4 and the fallback limits appear in no golden. Phase 2 needs §5.1 recorded from the Python motion before the kernel.
3. **The arm switch is combat-only** (`ARMS`, `:90`), and `=0` stops meaning "Python fire control" after FS M9. A motion arm needs its own switch.
4. **`k1_gameloop_ai` uses `owns_boundary=True`**, unlike the host. Phase 4's "already whole ticks" claim holds, but its boundary placement is not the host's.
5. **About 25 source-order tests parse `run()`.** The extraction commit has to repoint them.
6. **The sim section reaches `r` and GL** in the reconcile and `_sync_instance_transforms`, so a GL-free frame golden needs those injected. A GL tier needs a hidden window: a `tests/host` test.
7. **Cost:** the GameLoop scenes each run a discarded 1500-tick warm-up arm. A frame-level scene on combat_stress inherits that.
8. **Goldens exist only for darwin (R9).** A motion kernel on Linux or Windows is not pinned by any golden.
