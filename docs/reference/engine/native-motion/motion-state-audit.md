# Native motion (phase 2): motion-state reader/writer audit

Read-only map, 2026-11-03, branch `project/combat_threading` at **`2369cba41`**. Every line number is at that commit (read with `git show`/`git grep`; the working tree is an older main). SDK lines are from the BC SDK scripts root (`paths.sdk_scripts()`). Input to `docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md` §5.2 ("Python attributes become row-backed... Audit every reader and writer first"). Nothing was built, run or measured. Anything not read directly off the code is marked **inferred**.

Abbreviations:

| Abbrev. | File |
|---|---|
| **SM** | `engine/appc/ship_motion.py` |
| **SHIPS** | `engine/appc/ships.py` |
| **OBJ** | `engine/appc/objects.py` |
| **SS** | `engine/appc/subsystems.py` |
| **HL** | `engine/host_loop.py` |
| **LOOP** | `engine/core/loop.py` |
| **WF** | `engine/appc/warp_flight.py` |
| **DASH** | `engine/appc/dash.py` |
| **COL** | `engine/appc/collisions.py` |
| **DR** | `engine/appc/drift.py` |
| **NC** | `engine/appc/native_combat.py` |
| **SDK/** | the BC SDK scripts root |

## 0. Stages, in frame order

"When" in the tables below uses these names. Per **tick** (GameLoop.tick, `advance_ticks` HL:12425 runs N of them back to back):

| Stage | Where | What touches motion state |
|---|---|---|
| `gl.timers.*` | LOOP:45-48 | SDK timer actions (`TGSequence` script actions, e.g. `Actions.ShipScriptActions.SetImpulse`) |
| `gl.ai` | LOOP:61-62 | SDK AI trees (setpoints, `CompleteStop`, `InSystemWarp`, `SetAI`/`ClearAI`), preprocessors (velocity reads) |
| `gl.warp_states` | LOOP:98-99 | dewarp drive `_hold_ship` |
| `gl.motion` | LOOP:105-106 | `tick_all_ship_motion` (SM:154), incl. `warp_flight.step` and `drift.step` |
| `gl.rock_motion` | LOOP:109-110 | rocks only (`drift.step`); not ship rows |
| `gl.subsystems` | LOOP:116-117 | power update reads `_power_percentage_wanted` |

Per **frame**, after all of the frame's ticks (HL line order):

| Stage | Where | What touches motion state |
|---|---|---|
| `sim.input` | HL:12569, `_apply_input` HL:12625 → `_PlayerControl.apply` HL:3322 | manual player integrator + AI hand-off |
| combat ticks | HL:12687-12697 (`sim.weapons`, `sim.combat`; `cb.tractors` HL:1454) | `_velocity` readers (K1/K3 rows, Python fallbacks); tractor zeroes `_velocity` |
| `sim.debris_chunks` | HL:12886 | chunk spawn reads parent `GetVelocity` |
| `sim.collisions` | HL:12897 | reads `_velocity`, `_current_angular_velocity`, `IsImmobile` |
| `sim.rock_breakup` | HL:12907 (`_pump_scenery_contact`) | `collisions._resolve_body(player)` again |
| `sim.travel` | HL:12927 (`dash.tick`, `handoff.tick`) | dash writes `_velocity`, `_current_speed`, setpoints, transit |
| `sim.render_xforms` | HL:12985 | `subsystem_glow` reads the speed setpoint |
| UI / camera | per frame | `GetVelocity(TG)`, `GetAngularVelocityTG`, `GetImpulse` readers |

Event-driven (any time on the main thread): SDK mission handlers, Engineering UI, button presses (Set Course / Warp on Heading), `SetupProperties` at spawn.

---

## 1. Field by field

### 1.1 `_current_speed` (ShipClass, float, GU/s, signed)

Plain instance attribute, initialised SHIPS:169. **Not mirrored.** Rebound only (a float).

| Site | Op | When |
|---|---|---|
| SHIPS:169 | write 0.0 | construction |
| SM:276 | write `drift_vec.Length()` (drift → powered re-seed) | gl.motion |
| SM:283, 285 | read (cap, gap) | gl.motion |
| SM:289 | write (ramp) | gl.motion |
| SM:260-262 | read (drift snapshot) | gl.motion |
| SM:291-301 | read (translate, `SetVelocity`) | gl.motion |
| SHIPS:357 `GetImpulse` | read `abs(_current_speed)/authored max` | SDK, any stage (§3) |
| SHIPS:363 `IsReverse` | read `< 0` | SDK, any stage |
| SHIPS:371 `CompleteStop` | write 0.0 | gl.ai (SDK `AI/Player/Stay.py:9`), SDK `MissionLib.py:1893` |
| SS:2064 `_hold_ship` | write 0.0 | gl.warp_states, every tick of a warp-in slide |
| WF:307 / WF:310 | write 0.0 / `engaged_speed` (`_finish` exit policy) | gl.motion (python-owned row) |
| WF:312 | read (keep_pre_warp exit speed) | gl.motion (python-owned row) |
| HL:3275 `_sync_ship_integrator_from_control` | write (manual→AI seed from `_PlayerControl._current_speed`) | sim.input, first frame an AI owns the player |
| DASH:512 `abandon` | write 0.0 | event (RecreatePlayer / QB ship swap) |
| DASH:561, DASH:574 `drop_out` | write 0.0 | sim.travel |

Not to be confused with `_PlayerControl._current_speed` (HL:3089, the manual integrator's own copy; read by `weapons_display_panel.py:196` and `GetCurrentSpeed` HL:3169). That one is on the control object, not a ship, and stays Python (spec §4 non-goal).

### 1.2 `_current_angular_velocity` (ShipClass, TGPoint3, body frame, rad/s)

Plain instance attribute, initialised SHIPS:170. **Not mirrored.** `TGPoint3` is a mutable `__slots__ = ("x","y","z")` class (`engine/appc/math.py:15-18`). Two write styles coexist: **rebind** a new TGPoint3, and **in-place** component writes.

| Site | Op | When |
|---|---|---|
| SHIPS:170 | write (rebind) | construction |
| SHIPS:372 `CompleteStop` | write (rebind, zero) | gl.ai / SDK |
| SS:2065 `_hold_ship` | write (rebind, zero) | gl.warp_states |
| SM:309 | holds a reference (local `cav`) | gl.motion |
| SM:311-313 | read | gl.motion |
| **SM:318-320** | **in-place mutate** `cav.x/.y/.z = _ramp_toward(...)` | gl.motion |
| SM:330 (`_integrate_rotation`) | re-reads `ship._current_angular_velocity` and expects to see SM:318-320's writes | gl.motion (also the f≤0 drift branch, SM:270) |
| **HL:3209-3213** `_apply_body_rotation` | `player.__dict__.get(...)`, then **in-place mutate** (pitch→x, −yaw→z, −roll→y), every manual frame, zero included | sim.input |
| **HL:3276-3280** `_sync_ship_integrator_from_control` | `getattr(...)`, then **in-place mutate** (manual→AI seed) | sim.input |
| HL:3292-3296 `_sync_control_from_ship` | read (AI→manual resume) | sim.input; also dash drop-out resume (HL:3360) |
| COL:310-313 `_resolve_body` | `obj.__dict__.get(...)`, read, copied into `w` before rotating | sim.collisions; sim.rock_breakup (`rocks/scenery_contact.py:77`) |

Same attribute name on a non-ship: `DebrisChunk` (`debris_chunk.py:63`, read `:189`). COL:310 reads it from either class through `__dict__`. Chunks are not motion rows.

Tests that touch it (not exhaustive): rebinding is the norm (`test_collision_sustained_contact.py:78…208`, `test_dewarp_drive.py:180`, `test_ship_motion.py:179,217`, `test_shipclass_accessors.py:81`, `test_cross_set_interaction_gate.py:370`). **In place:** `tests/unit/test_player_ai_motion_handoff.py:142-143` (`cav = player._current_angular_velocity; cav.x, cav.y, cav.z = ...`, then expects the ship to resume from it). **Through `__dict__`:** `tests/unit/test_player_control_velocity.py:127,133`. Read via `getattr`: `tests/oracle/conftest.py:131`.

### 1.3 `_drift_velocity` (ShipClass, TGPoint3 or absent/None, world frame)

**Never set in `__init__`**: absent until a ship first loses every pod. Readers use `getattr(ship, "_drift_velocity", None)`, which only works because `TGObject.__getattr__` raises for `_`-names (`engine/core/ids.py:229-238`; its comment names this field). Not mirrored. Rebound only.

| Site | Op | When |
|---|---|---|
| SM:257 | read (getattr default) | gl.motion, f≤0 |
| SM:259-264 | write (rebind, snapshot `world_dir × _current_speed`); the local alias is used for SM:266-269 the same call | gl.motion |
| SM:274 | read | gl.motion, powered |
| SM:277 | write None | gl.motion |

No reader or writer outside SM. Tests read it: `tests/integration/test_engines_disabled_decays_velocity.py:55,61`, `tests/unit/test_impulse_degradation_motion.py:237,242`, `tests/unit/test_ids.py:33-34`, `tests/unit/test_in_system_warp.py:188`.

`_PlayerControl._drift_velocity` (HL:3093, 3446-3467) is the manual integrator's own copy, on the control object.

### 1.4 `_speed_setpoint` (ShipClass, `(float speed, TGPoint3 dir, int frame)` or None)

Initialised None SHIPS:167 (eager, so `getattr` sees None not a `_Stub`). Rebound only; `SetSpeed` copies the direction (SHIPS:297-301). Not mirrored.

| Site | Op | When |
|---|---|---|
| SHIPS:297 `SetSpeed` | write | gl.ai (SDK AI: `Intercept`, `Stay`, `FollowWaypoints`, `Ram`, `StationaryAttack`, `TurnToOrientation`, `Warp`, `DockWithStarbase`); SDK `MissionLib.py:4631` (player) |
| SHIPS:333 `SetImpulse` → `SetSpeed` | write (fraction × authored max) | gl.ai (19 SDK files, e.g. `GoForward`, `Flee`, `EvadeTorps`, `Preprocessors`); gl.timers (`Actions/ShipScriptActions.py:423`); `collision_avoidance.py:730` (test driver only, :639-650) |
| SHIPS:374 `CompleteStop` | write `(0.0, (0,1,0), 0)` | gl.ai / SDK |
| DASH:287, DASH:338 | write None | event (Set Course / Warp on Heading press) |
| HL:3297 `_sync_control_from_ship` | write None | sim.input |
| SM:215 | read | gl.motion |
| SHIPS:335-336 `GetSpeedSetpoint` | returns the **stored tuple itself** (live TGPoint3 inside) | — |
| `subsystem_glow.py:92` | read `sp[0]` via `GetSpeedSetpoint` | sim.render_xforms |
| `ui/ai_inspector_model.py:489` | read `ship.__dict__.get(...)` | dev UI |

No caller mutates the returned tuple's TGPoint3 (both readers take `sp[0]`).

### 1.5 `_target_angular_velocity_setpoint` (ShipClass, TGPoint3 or None, body frame)

Initialised None SHIPS:168. Rebound only; `SetTargetAngularVelocityDirect` copies (SHIPS:338-341). Not mirrored.

| Site | Op | When |
|---|---|---|
| SHIPS:341 `SetTargetAngularVelocityDirect` | write | gl.ai (SDK direct callers in 4 files) and SHIPS:621 (`TurnToward*`, SHIPS:629-700, called by SDK AI) |
| SHIPS:375 `CompleteStop` | write zero | gl.ai / SDK |
| DASH:288, DASH:339 | write None | event |
| HL:3298 | write None | sim.input |
| SM:216, SM:308 | read | gl.motion |
| SHIPS:343-344 `GetTargetAngularVelocitySetpoint` | read | engine-internal; no engine caller found |

### 1.6 `_velocity` (PhysicsObjectClass, TGPoint3, world frame) — already a NativeField

`_velocity = NativeField(VEC3)` (OBJ:632), comment "Always rebound (SetVelocity), never mutated in place" (OBJ:630-631). Checked: no in-place write anywhere in `engine/` (grep for `_velocity.x =`, `_velocity.Set/Add/...`). **`NativeField` has no `__get__`** (NC:622-660): the value lives in `obj.__dict__`, Python reads are plain attribute reads, and every rebind pushes to the Object row (`combat_set_fv`), or queues the push when off the main thread (NC:656-657). Getters return copies (OBJ:645-652).

Writers (all `SetVelocity`, OBJ:645-646):

| Site | When |
|---|---|
| SM:269 (drift), SM:298-302 (powered) | gl.motion |
| WF:315 (`_finish`), WF:422, 511, 533, 541, 572 | gl.motion (python-owned row) |
| SHIPS:889 `_end_in_system_warp` (zero) | wherever a transit ends: gl.ai (SetAI/ClearAI/CompleteStop/StopInSystemWarp), gl.motion (WF), sim.input, sim.travel, death (`ship_death.py:229`) |
| SS:2062 `_hold_ship` (zero) | gl.warp_states |
| `tractor.py:109` `_zero_velocity` (HOLD) | combat ticks, `cb.tractors` |
| HL:3343 (warp override), HL:3398 (take helm mid-warp), HL:3461 (drift), HL:3521 (powered) | sim.input (manual player only) |
| DASH:289, 462, 472, 513, 562, 575, 709 | event / sim.travel (player) |
| `warp.py:828` `_PlacePlayerAction._do_play` (zero) | warp sequence action (gl.timers) |
| `compat/fx_api/NanoFX_ScriptActions.py:60` | mod script action |
| SDK `SetVelocity` (12 files: `E1M2`, `E2M1`, `E3M1`, `E3M2`, `E3M5`, `E7M2`, `E8M1`, `E8M2`, `MissionLib`, `Actions/ShipScriptActions`, `AI/PlainAI/Warp.py:69`, `DockWithStarbase`, ...) | event / gl.ai |
| `rocks/death.py:272`, `rocks/promotion.py:164` | rocks (not motion rows) |

Readers (engine): `DR:60` (gl.motion and gl.rock_motion), COL:300 (sim.collisions), HL:3290 `_sync_control_from_ship` (sim.input), DASH:321 (event), `debris_chunk.py:134` (severance), `collision_avoidance.py:186-188` (AvoidObstacles preprocessor, gl.ai), `weapon_subsystems.py:604-605, 689-690` and `projectiles.py:696-697, 776, 1205` (combat Python fallbacks), HL:2216 (emitters), HL:8632 (camera speed), `camera_modes.py:493`, `ui/reticle_text.py:46`, `ui/ship_display_panel.py:631`, `ui/weapons_display_panel.py:182` (under AI), `ui/ai_inspector_model.py:482,518`. Native readers of the Object row: `weapon_geometry.cc:364-365` (K1 lead), `k1_fire_control.cc:1020` (launch velocity), `projectile_geometry.cc:406` (K3 guidance).

### 1.7 `_angular_velocity` and `_angular_space` (PhysicsObjectClass; scripted spin)

`_angular_velocity` initialised OBJ:637; **`_angular_space` is NOT** (absent until the first `SetAngularVelocity`; `RockClass._become_rock` setdefaults it, `rocks/rock.py:24`). Readers use `getattr(..., DIRECTION_WORLD_SPACE)` (DR:71). Both rebound only. Not mirrored.

| Site | Op | When |
|---|---|---|
| OBJ:663-668 `SetAngularVelocity` | write both | SDK (12 files, e.g. `E8M2` Matan model-space spin); SS:2063 `_hold_ship` (zero, world); `NanoFX_ScriptActions.py:70`; rocks |
| `rocks/rock.py:42-44` | override, writes `_angular_space` again | rocks |
| DR:64, DR:71 | read | gl.motion (setpoint-less non-player ships, SM:229-230), gl.rock_motion |
| OBJ:670-674 `GetAngularVelocity(TG)` | read (copy) | `camera_modes.py:522`, `NanoFX_ScriptActions.py:66`, `ai_inspector_model.py:484` |

The motion ramp never writes `_angular_velocity`.

### 1.8 `_insystem_warp_transit` (ShipClass, `WarpFlight` or None)

A Python object; the kernel only needs "is set". Initialised SHIPS:177. Rebound only.

| Site | Op | When |
|---|---|---|
| SHIPS:842 `begin_warp_flight` | write | gl.ai (`InSystemWarp` SHIPS:758, from SDK Intercept), sim.travel (`DASH:533` `_engage`) |
| SHIPS:888 `_end_in_system_warp` | write None (+ `SetVelocity(0)` SHIPS:889, + `ET_IN_SYSTEM_WARP` False) | gl.ai, gl.motion (WF `_finish`), sim.input (HL:3302-3303), sim.travel (DASH:493-494, 568-569), death (`ship_death.py:228-229`) |
| SM:205 | read → `warp_flight.step`; **False (parts hold) falls through to normal motion** | gl.motion |
| WF:333 | read | gl.motion |
| SHIPS:795, 883, 903 | read | gl.ai (`InSystemWarp`, `IsDoingInSystemWarp` for AvoidObstacles) |
| HL:3302, 3380 | read | sim.input |
| DASH:450, 493, 568 | read (identity with the dash's flight) | sim.travel |
| `systems/handoff.py:99` | read | sim.travel |
| `ship_death.py:228` | read via `__dict__.get` | death |

### 1.9 Static / stationary

| Field | Storage | Writers | Readers |
|---|---|---|---|
| `_static` (bool) | OBJ:640, `SetStatic` OBJ:715-716 | SDK mid-mission: `E1M1.py:810`, `E3M1.py:387,396,401,1768`, `E3M2.py:2083,2086`, `E3M4.py:191`, `E2M1.py:484`, `Multi1.py:107`, `Multi6_S.py:68`; `dev_missions/collision_sim.py:67` | `IsStatic` OBJ:718-719 |
| `_stationary` (int) | SHIPS:139, `SetStationary` SHIPS:962 | `SetupProperties` from `ShipProperty.GetStationary` (SHIPS:1302) at spawn | `IsStationary` SHIPS:961; `systems/station_hostility.py:107` |
| derived | `IsImmobile` SHIPS:964-971 = `IsStatic() or IsStationary()` | — | SM:198 (gl.motion), DR:58, COL:294 (sim.collisions), `collision_avoidance.py:690` (gl.ai), `rocks/scenery_contact.py:79`, `rocks/death.py:99` |

`_static` changes mid-mission, so an immobile flag must be pushed on write, not taken at spawn. `ShipClass.IsStationary`/`SetStationary` are **not BC surface on ShipClass**: the SDK's App.py binds them only on `ShipProperty` (`SDK/App.py:9761, 9772`). `PlacementObject` has its own `SetStatic` (`placement.py:40-43`), not a motion row.

### 1.10 Impulse engine authored limits (`_max_speed`, `_max_accel`, `_max_angular_velocity`, `_max_angular_accel`)

Plain floats on `ImpulseEngineSubsystem`, initialised SS:1828-1831. Not mirrored.

- **Writers:** `SetMaxSpeed`/... SS:1846-1851, called **only** from `SetupProperties` (SHIPS:1313-1320, from `ImpulseEngineProperty`). No other engine caller (grep). The SDK has no `ImpulseEngineSubsystem.Set*` binding: its `SetMax*` are on `ImpulseEngineProperty` (`SDK/App.py:9826-9829`). So they are spawn-time constants.
- **Readers:** `GetAuthoredMax*` SS:1839-1844 → SM:109-130 (`_effective_motion`), HL:3158 (`GetTargetSpeed`), SHIPS:330 (`SetImpulse`), SHIPS:354 (`GetImpulse`), `subsystem_glow.py:98`. Live `GetMax*` SS:1859-1869 and `GetCurMax*` SS:1885-1888 = authored × `impulse_output_fraction` → SDK AI (§3), HL:3159, HL:3394, `TurnToward*` in SHIPS.
- `Torpedo._max_angular_accel` (`projectiles.py:90`, a `TorpedoField`) is a different field with the same name.

### 1.11 `_power_percentage_wanted` (PoweredSubsystem, float in [0, 1.25])

A **`FrozenField`** (SS:1397): a passive-power thaw descriptor. Writes thaw a frozen consumer (`passive_state.py`; CLAUDE.md "a new input of `_update_power`/`_wants_power` MUST be a FrozenField"). Not mirrored.

- **Writers:** `__init__` SS:1424 (1.0), IES SS:1827, warp engine SS:1940; `SetPowerPercentageWanted` SS:1446-1458 (clamp, rescales `_power_wanted`, fires `ET_SUBSYSTEM_POWER_CHANGED`). Its callers: SDK `Bridge/EngineerMenuHandlers.py:446`, `Bridge/PowerDisplay.py:931-955`, `AI/Compound/DockWithStarbase.py:120`, `AI/PlainAI/Warp.py:258`, `Actions/ShipScriptActions.py:124`, missions (`E1M1:1278`, `E2M2:2386,2436,2585`, `E3M1:2663`, ...); engine alert policy for weapons and shields only (SHIPS:1055-1069); `ui/engineering_power_panel.py:43`. All event-driven.
- **Readers:** SS:278 and SS:3768 (`impulse_output_fraction` / `impulse_fractions`, gl.motion and every live `GetMax*`), SS:1512/1518 (power draw, gl.subsystems), `warp_gates.py:57`, `tg_ui/eng_power.py:82`, `engineering_power_panel.py:93,145`.

---

## 2. Flagged items

### 2.1 References to the angular-velocity object, and in-place mutation

**No code holds `_current_angular_velocity` (or `_drift_velocity`) across calls.** Every holder is a local inside one function. But three sites depend on in-place writes reaching the ship:

1. **SM:309-330.** The ramp mutates the ship's own TGPoint3 (SM:318-320), and `_integrate_rotation` re-reads the attribute (SM:330). If the attribute returns a copy, the ramp's writes are lost before the rotation uses them. This is inside the kernel being ported. But the Python reference copy that stays for the switch-off path would need a rebind (or one local passed on).
2. **HL:3209-3213 `_apply_body_rotation`** (sim.input, every manual frame). It publishes the player's body rates for collisions by writing into `__dict__`'s object in place. With a copy-returning representation it becomes a silent no-op, which is the 2026-09-21 "pitch through a Warbird with no contact" bug (`test_player_control_velocity.py:110-136`) coming back. With the existing NativeField pattern (value in `__dict__`, push on rebind), Python still sees it but the **row never does**.
3. **HL:3276-3280 `_sync_ship_integrator_from_control`** (manual→AI seed). The same problem: under a row-backed field the kernel's first AI-owned tick would ramp from the stale row value. Python ramps from the seeded value, so the two diverge on the hand-off.

Tests that encode the in-place contract: `test_player_ai_motion_handoff.py:142-143` (mutates in place, expects the ship to see it).

`_drift_velocity` is aliased only inside SM's f≤0 branch (SM:257-269). That is copy-safe once the kernel owns it.

### 2.2 `__dict__` readers (break if a field becomes a descriptor with storage elsewhere)

- `COL:310` `obj.__dict__.get("_current_angular_velocity")`: ships **and** DebrisChunk through one line.
- `HL:3209` `player.__dict__.get("_current_angular_velocity")`.
- `ship_death.py:228` `ship.__dict__.get("_insystem_warp_transit")`.
- `ui/ai_inspector_model.py:489` `ship.__dict__.get("_speed_setpoint")`.
- Tests: `test_player_control_velocity.py:127,133`.

The torpedo precedent (`projectiles.py:283-291`, `_velocity` as a property over `_vel`) moved storage off `__dict__` too. Its comment records the same rule: write-through is safe only because "nothing does [an in-place mutation]".

### 2.3 The mirror is Python-authoritative today

The NativeField design assumes Python holds the truth and the row is a copy:
- `_drop` (NC:491-515): an unrepresentable value or a stale handle drops the row, and the object "takes the Python path".
- `configure` (NC:158-178) turns the switch off and on at runtime. `resync` (NC:2891-2914) re-pushes every row from Python `__dict__`.
- `audit_mirror` (LOOP:122-126) compares row against Python every tick.

So if kernel M writes `_current_*`, `_drift_velocity` or **`_velocity`** only into the row, Python's copy goes stale. A later drop, switch-off or resync would then lose the motion state, or overwrite it with the stale copy (**inferred** from the code paths above, not exercised). It is the same for `_velocity` already: `GetVelocityTG` reads `__dict__` (OBJ:651-652), and its readers run after motion. They include the next tick's gl.ai, sim.input `_sync_control_from_ship` (HL:3290), sim.collisions (COL:300) and the UI.

### 2.4 Save, load and pickling

None of these fields is serialised.
- `engine/appc/save_load.py` writes JSON of Python-side globals only. Its docstring (`save_load.py:15-23`) says the ShipClass graph is not saved.
- No engine class defines `__getstate__`/`__setstate__`/`__reduce__` (grep of `engine/`). The one mention is a comment, SS:2188-2192, about SDK classes that round-trip.
- No `copy.deepcopy` of ships.
- Mission swap (`engine/core/mission_change.py`) keeps the in-transit player object, so its Python attributes (and any row) survive. No swap path writes these fields (grep of `engine/core`, `engine/missions`, `engine/quickbattle`, `engine/systems`: only `handoff.py:99`, a read).

### 2.5 Off-main-thread and finalizer writers

None.
- The only Python thread in `engine/` is the log tee follower (`log_tee.py:310`).
- The finalizers are `objects.py:110` (`_release_transform_slot` → `native_combat.defer_free`, record only), NC:1459 (`unregister_handle`) and `hum_allocator.py:170` (stops a sound). None touches motion state.
- `NativeField.__set__` already queues an off-main push (NC:656-657), so a future off-main writer would not corrupt a row. But it would apply only at the next drain.

### 2.6 The `_PlayerControl` hand-off, the dewarp drive and collisions

**Hand-off** (HL:3378-3413, inside `apply`, sim.input, once per frame **after** the frame's ticks):
- **AI installed, no manual input:** on the first such frame `_ai_owned = True` and `_sync_ship_integrator_from_control` seeds `ship._current_speed` (rebind) and `_current_angular_velocity` (**in place**) (HL:3270-3280). Then `apply` returns, so the manual integrator is skipped.
- **Inferred timing:** an AI installed inside a tick's gl.ai is ramped by that frame's gl.motion ticks from the ship's stale `_current_*`. The seed lands only in sim.input afterwards. Phase 4 (sim.input moved to frame start) changes when it lands.
- **Manual input while an AI owns:** `_cancel_player_ai` → `ClearAI` (which ends any transit: `SetVelocity(0)`), then `_sync_control_from_ship`. That reads `GetVelocity` (`_velocity`) and `_current_angular_velocity`, and writes both setpoints None (HL:3282-3303). Mid-warp, it then forces full impulse: `SetVelocity` HL:3394-3400.
- **AI released:** `_sync_control_from_ship` (HL:3409-3413).
- **Dash drop-out:** `_sync_control_from_ship` (HL:3357-3362).
- **Under manual flight:**
  - `_apply_body_rotation` writes the ship's `_current_angular_velocity` in place every frame (HL:3209-3213), for COL only.
  - The ship's `_current_speed` is **not** maintained. Only HL:3275 writes it, at the hand-off, so `GetImpulse`/`IsReverse` read a stale value for a manually flown player (**inferred** from the writer list; affects SDK `AI/Player/FlyForward.py:9-10`, `E3M1.py:3076`, `BridgeHandlers.py:1390`, `TacticalInterfaceHandlers.py:152,520,544`).
  - `SetVelocity` is published every frame (HL:3521).
- **Manual player with a stale setpoint (inferred double driver).** SM's manual-player exclusion (SM:229) applies only when both setpoints are None. SDK `MissionLib.StopShip` (`MissionLib.py:4631`, `SetSpeed(0)` with no AI) and `MissionLib.py:1893` (`ClearAI` then `CompleteStop`) leave setpoints on a manually flown player. If `_ai_owned` was already False, nothing clears them, so gl.motion ramps and rotates the player each tick and `_PlayerControl.apply` integrates it again each frame. Not observed live. The spec's branch 4 ("except the manual player") reproduces this exactly.

**Dewarp drive `_hold_ship`** (SS:2058-2065, gl.warp_states, every tick of the 2.0 s slide, before gl.motion):
- `SetTranslate`, `SetMatrixRotation`, `SetVelocity(0)`, `SetAngularVelocity(0)` (so `_angular_space` = world), `_current_speed = 0.0`, and `_current_angular_velocity` **rebound** to a new zero.
- Rebind only, so copy semantics are safe if the write goes through whatever setter the row uses.
- SM skips the row while arriving (SM:212-213). The flag is already mirrored (`push_arriving` NC:2510-2517, Object field `arriving`).
- Pinned by `test_dewarp_drive.py:175-195`.

**Collisions** (`_resolve_body` COL:281-329, sim.collisions per frame, after every tick and after sim.input; also `rocks/scenery_contact.py:77`):
- Reads `IsImmobile()` (COL:294), `GetVelocity()` (copy, COL:300) and `__dict__["_current_angular_velocity"]` (COL:310), copied into a new `w` and rotated to world.
- Writes only poses (`SetTranslateXYZ` COL:828, 835, 1051) and its own `_collision_velocity` overlay (COL:272-278). It never writes `_velocity` or `_current_*`.
- For AI ships it reads the last tick's ramp value. For the manual player it reads this frame's `_apply_body_rotation` value.

---

## 3. SDK getters → fields

| BC getter (SWIG, `SDK/App.py`) | Ours | Field read | SDK script callers |
|---|---|---|---|
| `PhysicsObjectClass.GetVelocityTG` / `GetVelocity` (5256 / 5244) | OBJ:648-652, copy | `_velocity` | gl.ai: `AI/Preprocessors.py:748,1728,1788,1794,1865`, `PlainAI/Intercept.py:132,238`, `TorpedoRun.py:134-135,143,217`, `EvadeTorps.py:114-115`, `StationaryAttack.py:87`, `Ram.py:99`, `EvilShuttleDocking.py:96,123`, `Warp.py:69`; UI/events: `Bridge/HelmMenuHandlers.py:2450,2619`, `BridgeHandlers.py:1389`, `Actions/ShipScriptActions.py:548`, `E1M2.py:3369,3422,7457`, `E2M1.py:2307`, `E2M0.py:3567` |
| `PhysicsObjectClass.GetAngularVelocityTG` / `GetAngularVelocity` (5260 / 5272) | OBJ:670-674, copy | **`_angular_velocity` (scripted), NOT `_current_angular_velocity`** | none in SDK scripts |
| `PhysicsObjectClass.GetAccelerationTG` (5264) | OBJ:654-661 | none: always zero | 7 files (Intercept-style predictions) |
| `ShipClass.GetImpulse` (5495) | SHIPS:346-358 | `_current_speed` / authored `_max_speed` | `BridgeHandlers.py:1390`, `TacticalInterfaceHandlers.py:152,520,544`, `E3M1.py:3076`, `AI/Player/FlyForward.py:9` |
| `ShipClass.IsReverse` (5496) | SHIPS:360-363 | `_current_speed` | `TacticalInterfaceHandlers.py:517,545`, `FlyForward.py:10` |
| `ImpulseEngineSubsystem.GetMaxSpeed/Accel/AngularVelocity/AngularAccel` (6689-6692) | SS:1859-1869 | `_max_*` × pods × `_is_on` × `_power_percentage_wanted` | `Intercept.py:118,220,222`, `FollowWaypoints.py:183,228`, `Ram.py:85`, `MoveToObjectSide.py:242-243`, `SSDiag.py` |
| `ImpulseEngineSubsystem.GetCurMax*` (6693-6696) | SS:1885-1888 (= live) | same | `AI/Preprocessors.py:523`, `SSDiag.py:114-117` |
| `ShipClass.IsDoingInSystemWarp` (5501) | SHIPS:894-905 | `_insystem_warp_transit` (+ `_doing_in_system_warp`) | 5 files incl. `Preprocessors.py:1692-1693` |
| `PoweredSubsystem.GetPowerPercentageWanted` (5696) | SS:1460 | `_power_percentage_wanted` | 13 files (power UI, Helm gates) |
| `PhysicsObjectClass.IsStatic` (5301) | OBJ:718 | `_static` | none in SDK scripts (`IsStatic(` 0 hits) |
| `ShipClass.GetTargetAngularVelocityTG` (5446) | **not implemented** (`_Stub`) | — | none in SDK scripts |
| `ShipClass.SetTargetAngularVelocityFraction` (5503) | **not implemented** (`_Stub`) | — | `TacticalInterfaceHandlers.py:340` (player path; known gap) |

---

## 4. Recommendation table

| Field | Native representation question |
|---|---|
| `_current_speed` | **Row-backed, copy semantics safe** (a float, rebind only). Needs a decision on **who keeps Python's copy current** (§2.3): `GetImpulse`/`IsReverse` and WF:312 read it from Python after the kernel. Also needs a decision on whether the manual player's row should finally carry `_PlayerControl`'s speed (§2.6, inferred stale today; a behaviour change if fixed). |
| `_current_angular_velocity` | **Needs a decision.** In-place writers at HL:3211-3213 and HL:3278-3280 (and SM:318-320 in the Python copy) must become rebinds through a setter that pushes, or the row goes stale. `__dict__` readers at COL:310 and HL:3209 (also used for DebrisChunk) rule out a property with off-`__dict__` storage unless they change too. The test `test_player_ai_motion_handoff.py:142-143` encodes the in-place contract. |
| `_drift_velocity` | **Row-backed, copy safe.** Only SM touches it. Decide its absent/None encoding (valid flag) and whether tests keep reading it from Python. |
| `_speed_setpoint` | **Row-backed (mirror on rebind), copy safe.** The kernel reads only. It needs a tuple encoder (valid, speed, dir xyz, frame). `GetSpeedSetpoint` hands out the live tuple; no caller mutates it. |
| `_target_angular_velocity_setpoint` | **Row-backed (mirror on rebind), copy safe.** The kernel reads only; encode None as invalid. |
| `_velocity` | **Already a NativeField. Needs a decision on the direction of authority.** Today Python writes and the row mirrors. After the kernel writes the row, Python's `__dict__` copy must be refreshed (write-back), or `GetVelocity(TG)` must read the row. Many Python readers run after motion (§1.6). Drop, switch-off and resync (§2.3) assume Python is current. |
| `_angular_velocity`, `_angular_space` | **Mirror on rebind, copy safe.** The kernel reads only (drift branch). `_angular_space` is absent by default: encode world (1). |
| `_insystem_warp_transit` | **Mirror a bool only, copy safe.** Needs a decision on the segment protocol: `warp_flight.step` returning False (parts hold, WF:334-339) means the row **also** runs normal motion that tick, so "python-owned" is not "skip natively". |
| `_static` / `_stationary` | **Mirror on write, copy safe.** `_static` changes mid-mission (§1.9), so it cannot be a spawn snapshot. Mirror the derived "immobile" or both. |
| IES `_max_*` (four) | **Mirror on write, copy safe.** Written only at `SetupProperties`. |
| `_power_percentage_wanted` | **Mirror on write, copy safe**, but it must stay a FrozenField: use the existing `NativeFrozenField` (as `_is_on` SS:1395, `_power_factor` SS:1402). A plain NativeField would break the passive-power thaw contract. |
