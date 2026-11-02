# Random-number map for roadmap decision 12 (presentation RNG)

Read-only research, worktree `.claude/worktrees/native-combat-k3` (branch `ws/combat-launch-cache`).
Paths are repo-relative unless prefixed `SDK/` (= `/Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/`).
Anything not read off code is marked **inferred**.

Streams:
- **S1** `App.g_kSystemWrapper.GetRandomNumber`: one `random.Random()` built with no seed (`App.py:994-1004`, so OS-entropy seeded per process). `SetRandomSeed` reseeds it (`App.py:1003-1004`).
- **S2** the process-global `random` module.
- **P** (proposed) the presentation generator.

**Superseded where built (2026-11-02):** the design in §7 is implemented on `ws/combat-presentation-rng`; spec `docs/superpowers/specs/2026-11-02-presentation-rng-design.md` §10 is the record of what was built and where it departs from this map (blast size of a damaging blast is gameplay, §7.4; NanoFX spin stays on S1, X7; resets in `_reset_session_scratch`, §7.1). Line numbers below are the pre-change code.

---

## 0. Corrections to the existing docs

1. **damage-map H10 is wrong where it guesses that headless has no sound manager.** `App.g_kSoundManager` is the `TGSoundManager.instance()` singleton (`engine/audio/tg_sound.py:534`, imported at `App.py:198-200`). It is `None` only after the test helper `shutdown_audio_for_tests` (`tg_sound.py:564-576`). `_play_audio` (`engine/appc/hit_feedback.py:463-466`) therefore goes on to `GetRandomSound`, which draws S1 **headless as well**. `GetSound(name)` returning None comes after the draw (`hit_feedback.py:496-499`). `tests/helpers/fight_audio.py:1-20` exists because of this.
2. **The audio throttle is reset when the view mode changes** (`engine/host_loop.py:3854`, `hit_feedback.reset_audio_throttle()`). Entering or leaving the bridge re-arms every (ship, severity) edge, so the next hit makes an extra `GetRandomSound` S1 draw. The player's camera view can therefore shift gameplay rolls.
3. **Bridge animations draw S1 in the live host**, and nothing documents it. The hit reactions (`engine/bridge_hit_reactions.py:65`) and the idle gestures (`engine/bridge_idle_gestures.py:131-132`) call SDK animation builders through `build_sequence_clips` (`bridge_idle_gestures.py:28-31`). 37 of those builders draw S1 (`SDK/Bridge/Characters/{Common,Medium,Small,Large}Animations.py`), including `HitStanding` and `HitHardStanding`, which are reached on every player `ET_WEAPON_HIT` (registered at `host_loop.py:11255`). The idle gestures are bridge-view gated and step on the frame `_player_dt` (`host_loop.py:13106-13114`). As a result, **whether the player is on the bridge, and the wall-clock frame rate, change the gameplay S1 sequence.**

---

## 1. Every draw reachable from a combat tick

Legend: **PRES** = no effect on game state. **GAME** = affects damage, AI choice, mission or the timing of gameplay. **MIXED** = both.

### 1.1 Hit path (`combat.apply_hit` → `hit_feedback.dispatch`; inside K2 for beam pulses, after K3 for torpedoes, in collisions, in death splash)

| # | Site | Stream | Class | Notes |
|---|---|---|---|---|
| H1 | `engine/appc/hull_hit_smoke.py:93` `GetRandomNumber(10)` smoke roll | S1 | PRES | Only for torpedo/phaser hull hits (`:19`). Phasers are throttled per (target, source) on game time (`:86-91`). The effect level is always HIGH (`engine/appc/particles.py:185-187`). **The roll happens headless too**: the instance check comes after it (`:95-97`). |
| H2 | `hull_hit_smoke.py:123` `GetRandomNumber(30)` puff life | S1 | PRES | Live only, after a passing roll and a resolved instance. |
| H3 | SDK `Effects.CreateSmokeHigh` (`SDK/Effects.py:288,292,306,310`), called `hull_hit_smoke.py:124` | S1 ×2-4 | PRES | SDK script run purely for presentation. |
| H4 | Particle controller seed `particles.py:65` `_random.random()` (one per controller created by H3) | S2 | PRES | Seed goes to the renderer (`particles.py:319` → `native/src/host/host_bindings.cc:8447`). |
| H5 | `hit_feedback.py:473,480` → SDK `LoadTacticalSounds.GetRandomSound` (`SDK/LoadTacticalSounds.py:165`) | S1 | PRES | Gated by the **wall-clock** edge trigger (`hit_feedback.py:187-200`, see §6). Also mutates `g_dRecentSounds` (presentation state). Reached by collisions too: severity HULL with `weapon_type="collision"` still plays. |
| H6 | `hit_feedback.py:487` CRITICAL → `LoadDamageHitSounds.GetRandomSound` (rebound to the LTS function, `LoadDamageHitSounds.py:64-67`) | S1 | PRES | Same gate. |
| H7 | Bridge hit reaction `bridge_hit_reactions.py:65` → SDK `CommonAnimations.HitStanding/HitHardStanding` | S1 | PRES | Live host only, player target only. A synchronous `ET_WEAPON_HIT` handler, so it runs **inside the K2 walk** for a phaser pulse (**inferred** from synchronous dispatch, event-inventory §0.1). |
| — | `hit_vfx.spawn`, shield splash, decals, `hull_wear`, `camera_shake`, `part_severance` | none | — | No draws (grep of those modules). |

### 1.2 Death path (`ship_death.begin`, `engine/appc/ship_death.py:74-113`; `death_cascade`)

| # | Site | Stream | Class | Notes |
|---|---|---|---|---|
| D1 | `death_cascade.roll_duration` `death_cascade.py:150` `rand(100)` | S1 | GAME | Sets the throes length → `_mark_dead`, the destroyed event and lock clearing (`ship_death.py:89-93, 151-165`). |
| D2 | `death_cascade.plan` `:177` `rand(4)` per blast | S1 | GAME (MIXED) | The blast times are also when the damage lands (D5). All are drawn up front at `begin` (`:193`). |
| D3 | `_fire` `:239` `ship.GetRandomPointOnModel()` (`engine/appc/objects.py:389` live `randrange`; `:397-399` headless 3×`gauss`) | S2 | **MIXED** | The same point feeds `AddDamage` (gameplay, `:246` → `objects.py:1036-1042` `combat.apply_hit(..., splash_radius, bypass_shields=True)`) **and** the VFX (`:249`). It is drawn on every blast, although only about 30% of blasts damage. Live and headless consume S2 differently (1 draw vs gauss's paired draws). |
| D4 | `roll_blast_scale` `:157,163` (2 draws per blast) | S1 | **MIXED** | `m` scales only the *visible* hole (`visible_damage.py:70-92, 134-135`; `apply_hit` never sees it) and the blast size. The visible hole then becomes wear, and `hull_breakup.after_wear` (`visible_damage.py:276-278`) can sever parts: `_destroy_subsystems_inside`, colliding debris chunks (`hull_breakup.py:167-177`). That tail is live-only, because it needs an instance. These draws **sit before D5 in S1**, so every blast's cosmetic size shifts the next damage roll. |
| D5 | `_fire` `:243` `rand(10) < 3` → `AddDamage` | S1 | GAME | |
| D6 | `_debris_explosion` `:302` puff count | S1 | PRES | Then `Effects.CreateDebrisExplosion` makes no S1 draw (none in `SDK/Effects.py`), but its controllers draw S2 seeds (H4-style). |
| D7 | `_death_sound` `:329` → SDK `Effects.GetDeathExplosionSound` → `GetRandomSound` (`SDK/Effects.py:881`) | S1 | PRES | Throttled by blast time (`:212-219`), so this is deterministic. |
| D8 | `_fire_final` `:271,279` `GetRandomPointOnModel` ×3 or ×5 | S2 | PRES | Points used for VFX only. |
| D9 | `_fire_final` `:272` SDK `Effects.CreateDebrisSparks` (`SDK/Effects.py:460,477`) | S1 ×2 | PRES | |
| D10 | `RunDeathScript` (`ship_death.py:98-101`; rocks `engine/rocks/death.py:62-65`; impl `engine/appc/ships.py:1923-1937`) | S1 + S2 | **MIXED** | All three stock death scripts draw only for presentation: E1M2 `AsteroidExploding` (`SDK/Maelstrom/Episode1/E1M2/E1M2.py:3109-3119`: point, sparks, sound), E7M1 `FreighterExploding` (`E7M1.py:1397-1413`), E3M2 `ProbeExploding` (`E3M2.py:871-879`). The same scripts also do gameplay (`SetLifeTime`, `SetCollisionsOn`). A mod death script could draw for gameplay. |
| D11 | Death splash `splash_damage.apply` (`ship_death.py:108-111`) → nested `apply_hit` → H1-H7 for each victim | as H | as H | |
| D12 | `debris_chunk.spawn` `engine/appc/debris_chunk.py:131,151` (`rng or random`, 3 uniforms) | S2 | MIXED (**inferred** GAME-ish) | The chunk spin of a body that collides (`collisions.py:1218-1222`). Live only. |
| — | Rock breakup `engine/rocks/breakup.py:79-80,130`, gravel `rocks/death.py:167` | private (crc32 of name) | GAME / PRES | Already isolated and deterministic. |

### 1.3 AI, missions and the rest of the tick

| # | Site | Stream | Class |
|---|---|---|---|
| A1 | `engine/appc/ai_driver.py:1008` `random.choice(ai._untried)` (RandomAI) | S2 | GAME |
| A2 | SDK `AI/Preprocessors.py:412` (FireScript visibility-check jitter), `:908` (which subsystem to update) | S1 | GAME |
| A3 | SDK `AI/Preprocessors.py:2291` FelixReportStatus line pick | S1 | PRES inside gameplay code (MIXED by location) |
| A4 | SDK PlainAI: `Defensive.py:59`, `FollowThroughWarp.py:52,192,218`, `IntelligentCircleObject.py:296`, `Intercept.py:84`, `PhaserSweep.py:127`, `Ram.py:55`, `StationaryAttack.py:46`, `Warp.py:239`; Compound `FedAttack.py:13`, `NonFedAttack.py:13` | S1 | GAME |
| A5 | `TGPoint3_GetRandomUnitVector` `engine/appc/math.py:462-474` (Flee, EvadeTorps, Warp, Preprocessors AvoidObstacles) | private `_unit_vector_rng` | GAME |
| A6 | `collision_avoidance._rng` `engine/appc/collision_avoidance.py:114, 219-221` | private | GAME |
| M1 | Missions in combat: `SDK/Maelstrom/Episode7/Episode7.py:111` (TorpedoFired), E8M2 `:759,854,887,949,983,5164`, E3M2 `DamageShip :3111-3184`, E7M1 waves `:1479-1656`, `CollisionAftermath :1894`; `SDK/MissionLib.py:5286` `GetRandomDamage`; `SDK/QuickBattle/QuickBattle.py:2850-2862`; `SDK/WarpSequence.py:173-692` | S1 | GAME |
| M2 | Gameplay handlers with a line-pick draw: `SDK/MissionLib.py:3970,3975,4014,4097,4100` (friendly fire), `SDK/Bridge/HelmMenuHandlers.py:869,1314,1379,1395,2250,2285,2542`, `TacticalMenuHandlers.py:1248,1258,1315,1379`, `ScienceCharacterHandlers.py:454,477`, `EngineerMenuHandlers.py:333,341`, others in `Bridge/*` | S1 | PRES draws inside GAME handlers (MIXED) |
| R1 | Radiation `engine/appc/radiation.py:67,92,102,105` | private, **unseeded** `random.Random()` | GAME (outages) |
| N1 | `nebula_thunder.py:42,77-113`; `hull_discharge.py:40,58-68` | private, fixed seeds | PRES |
| X1 | `crew_hazard_prompts.py:93,126` | private, unseeded | PRES |
| X2 | `engine/appc/crew_speech.py:274-279` `_rand5` (ack line) | S1 | PRES |
| X3 | Idle gestures `bridge_idle_gestures.py:131-132` → SDK builders (`CommonAnimations.WallSlides`, Console* …) | S1 (plus private pick `host_loop.py:11098`) | PRES; live, bridge view, frame dt |
| X4 | `engine/appc/viewscreen_static.py:38` default `rng=random.random`, called every frame `host_loop.py:9691` while static | S2 | PRES; frame-rate dependent |
| X5 | `engine/rocks/minor_contact.py:74` `random.randint(1, 8)` grit sound | S2 | PRES |
| X6 | SDK `DynamicMusic.py:163` music pick (driven by SDK events, `engine/appc/music_manager.py`) | S1 | PRES |
| X7 | NanoFX compat `engine/compat/fx_api/NanoFX_Lib.py:45,57`, `NanoFX_ScriptActions.py:51,83` | S1 | PRES (mods only) |
| X8 | `objects.RandomOrientation` `objects.py:427` (mission setup, Multi*) | S1 | GAME (setup, not per tick) |
| X9 | `late_arrivals.py:33,124,262`; `shuttle_service.py:264,1179` | private, unseeded | GAME |
| X10 | `native_combat._self_check` `native_combat.py:380` | private, fixed | test harness only |

**Counts (call sites on the shared streams in or near a combat tick):**
- **PRES:** 18 engine sites: H1, H2, H4, H5, H6, H7, D6, D7, D8, D9, X2, X3, X4, X5, plus the presentation draws inside D10, H3, X6 and X7, which are SDK or compat code.
- **GAME:** 6 engine sites: D1, D2, D5, A1, X8, and the AddDamage half of D3. Plus all the SDK AI and mission sites.
- **MIXED:** 6: D3, D4, D10, D12, A3/M2 (presentation draws inside gameplay SDK handlers), and A5's shared generator, which `SDK/Effects.py:840` would also draw from (not reached by the engine today).

---

## 2. SDK scripts the engine calls purely for presentation (scope candidates)

| SDK function | S1 draws | Engine call site |
|---|---|---|
| `LoadTacticalSounds.GetRandomSound` | 1 (`LoadTacticalSounds.py:165`) | `hit_feedback.py:473,480,487`; inside `Effects.GetDeathExplosionSound` |
| `Effects.GetDeathExplosionSound` | 1 (`Effects.py:881`) | `death_cascade.py:329` |
| `Effects.CreateSmokeHigh` | 2-4 (`Effects.py:288-310`) | `hull_hit_smoke.py:124` |
| `Effects.CreateDebrisSparks` | 2 (`Effects.py:460,477`) | `death_cascade.py:272` |
| `Effects.CreateDebrisExplosion` | 0 S1, S2 via controllers | `death_cascade.py:278,300` |
| `Bridge.Characters.*Animations.<builder>` | 1-n | `bridge_idle_gestures.py:31` (`build_sequence_clips`, both hit reactions and idle) |
| Mission death scripts via `RunDeathScript` | S1 + S2 | `ship_death.py:98-101`, `rocks/death.py:62-65` (whole call; see the D10 caveat) |
| `DynamicMusic.ProcessQueue` | 1 (`DynamicMusic.py:163`) | SDK-internal callers (`:126,211,240,255`). The engine has no single entry to wrap: **leave on S1** or wrap the `music_manager` callbacks that end in it (**inferred** feasible). |

Gameplay SDK draws that must stay on S1: all of §1.3 A2, A4, M1, plus `RandomOrientation` setup. SDK-seeded fields (`Systems/Multi1/Multi1.py:97`, `Multi4_S.py:19`, `multi2_S.py:39`, `Multi6_S.py:58`, `Multi7_S.py:79` `SetRandomSeed(42/40)`) rely on S1 staying the gameplay stream.

Not reached by the engine: `Effects.ObjectExploding/CreateObjectExplosion/TorpedoHullHit/PhaserHullHit/CollisionEffect/CreateWeaponSparks` (reimplemented in Python or not registered; grep of `engine/` finds no call), and `Bridge/bridgeeffects.py`.

---

## 3. Existing private generators

| Generator | Seed | Use | Keep or join P |
|---|---|---|---|
| `collision_avoidance._rng` (`:114`) | fixed `0xC0111DE`, reseeded in `reset_avoidance_state` (`:140`) | AI flee candidates | **Keep** (gameplay) |
| `math._unit_vector_rng` (`:450`) | fixed `0xF1EEC0DE`, reset per test (`tests/conftest.py:1646-1655`) | AI | **Keep**. If `Effects.CollisionEffect` is ever run, put it in the scope so its `GetRandomUnitVector` uses P. |
| `hull_discharge` (`:40`) | fixed 2027, reset per mission (`host_loop.py:5042`) | nebula sparks VFX | Could join P. Already isolated: **leave** (no benefit). |
| `nebula_thunder` (`:42`) | fixed 1337, reset per mission (`host_loop.py:5040`) | flash and sound | **Leave** |
| `crew_hazard_prompts` (`:93`) | **unseeded** | crew lines | Leave, or seed from P for reproducibility |
| `radiation` (`:67`) | **unseeded** | GAMEPLAY outages | **Keep separate**. Unseeded gameplay is a determinism gap (out of scope). |
| `late_arrivals` (`:33,124`), `shuttle_service` (`:264`) | unseeded, injectable | gameplay | Keep |
| rocks `breakup` / `death` gravel | crc32 of name | gameplay / visual | Keep (stateless) |
| `lip_sync_runtime` (`:93-94`), idle gestures (`host_loop.py:11098`) | fixed | presentation | Keep. The idle gestures' **SDK builder** draws still need the scope. |

---

## 4. Native side

- **Combat kernels draw nothing random.** `native/src/combat/src/*.cc` has no RNG. Nebula density noise is a pure function of a position-derived seed (`combat/src/nebula_density.cc:107-111`; `sensor_detect.cc:272-278`). A future native damage port (roadmap D) would inherit H9.
- **The renderer uses stateless hashes or private splitmix only.** Examples: `torpedo_anim.h:88-100` `hash01`, `hit_vfx_pass.cc:91-138` (hash of position), `particle_pass.cc:215-300` (hash of the emitter seed), `nif/legacy_rng.h` (per-system splitmix), `rock_random.h`, `rockgen/src/shape.cc:32-35` (`mt19937_64`, generation tool), the breach seed counter `host_bindings.cc:2759-2762`.
- **Python-to-C++ handoffs:** the particle emitter seed comes from **S2** (`particles.py:65`, then `:319`), and surface points are picked in Python from the renderer's list (`objects.py:384-389`). No C++ code draws from or seeds S1/S2. Moving H4 to P changes particle looks only.

---

## 5. Determinism today

- **Production:** S1 is unseeded (`App.py:996`), and S2 is never seeded by the engine. Neither is reseeded per mission (grep: only `engine/dev_missions/damage_preview.py:88` and the SDK Multi* systems call `SetRandomSeed`). `damage_preview` notes that S2 stays unseeded (`:73-77`). Live fights are therefore not reproducible today in any case.
- **Tests:**
  - `seed_every_rng` (`tests/helpers/k3_fight.py:69-78`) seeds S2, S1, avoidance and unit vectors. Private copies: `tests/integration/test_native_k1_differential.py:121-131`, `tests/host/test_native_k2_differential.py:190-196`. Used by K1/K2/K3 differentials and `posed_fight.py:232`.
  - `random.seed(0)` only: `test_native_combat_step_differential.py:86`, `test_native_can_detect_differential.py:90`, `test_passive_weapons_differential.py:69`, `test_passive_power_differential.py:45`, `test_native_combat_k2_mirror.py:345`, `test_native_combat_weapons_mirror.py:518`.
  - `isolate_fight_audio` (`tests/helpers/fight_audio.py:26-38`) clears `g_dRecentSounds` and the throttle, swaps the wall clock for game time in `hit_feedback`, `crew_speech` and `speak_queue`, and resets the bridge `g_fLast*` stamps. It exists because hit sounds and officer animations shift S1.
- **Tests pinning exact sequences:**
  - `tests/unit/test_ai_driver.py:308-322` (`random.choice` on S2: breaks if A1 moves off S2).
  - `test_system_wrapper.py:26-28`, `test_random_orientation.py:21-37` (S1 reproducibility, unaffected).
  - `test_shuttle_service.py:50,1712`, `test_ai_intercept_smoke.py:44`, `test_dormant_priority_child_recovers.py:58` (S1-seeded AI scenes; may shift if presentation draws are removed from their path, **inferred**).
  - `test_death_cascade.py` injects `rand=` (`:102-103, 257`), so it is unaffected unless the signatures change.
  - `test_damage_preview_impulse_steps.py:82,121` (fake wrapper).
- **Differentials:** each compares a native arm with a Python arm on the same seed. **There are no stored golden traces** (find over `tests/` for json/txt/pkl differential files returned nothing). The "re-record" in the roadmap amounts to:
  - (a) add P to every `seed_every_rng` copy;
  - (b) re-run, because the fights now play out differently, and re-check the fight-dependent coverage assertions (`> 0` counts: K2 `test_native_k2_differential.py:975-1105`; K3 `test_native_k3_differential.py:585-596`; K1 23 such asserts). Scripted-geometry literals like tick 89 (`test_native_k3_differential.py:568-590`) look independent of the RNG (**inferred**);
  - (c) once §6 lands, `isolate_fight_audio`'s `hit_feedback` clock patch becomes redundant (`crew_speech` and `speak_queue` still need theirs).

---

## 6. The hit-sound wall-clock throttle

Code (`engine/appc/hit_feedback.py:172-200`, call `:354-355`):
```python
now = time.monotonic()
last = _last_dispatch_time.get(key)
_last_dispatch_time[key] = now
if last is None:
    return True
return (now - last) >= _AUDIO_CONTACT_GAP_S   # 0.15
```

Why it depends on real time: several sim ticks run in one frame (`host_loop.py:12344-12347` `step_accumulator`), so their dispatches are microseconds apart in wall time even though they are 1/60 s apart in game time. A slow frame therefore plays fewer sounds and makes fewer S1 draws.

Game-time source: `damage_decals.current_game_time()` (`engine/appc/damage_decals.py:65-80`, which is `App.g_kUtopiaModule.GetGameTime()` = `g_kTimerManager.get_time()`, `App.py:1161-1162`). `hull_hit_smoke._now` already uses it (`hull_hit_smoke.py:45-49`), as do the decal throttles.

Behaviour under game time:
- Game time advances `TICK_DELTA` (1/60) per `GameLoop.tick` (`engine/core/loop.py:39`).
- Pause runs zero ticks (`host_loop.py:12342-12347`), so the gap freezes.
- **No time-scale is implemented** (grep finds no `SetTimeScale`/`SetTimeRate` in `engine/`), so there is nothing to scale.

Pitfalls:
- `g_kTimerManager._time` is zeroed on mission swap (`host_loop.py:4731`), but the audio throttle is **not reset there**. The mission-swap block at `host_loop.py:7898-7906` resets the decal and smoke throttles but not this one. Add `hit_feedback.reset_audio_throttle()` to that block, or treat `now < last` as a fresh contact. Otherwise a reused `id(ship)` stays silent.
- The view-change reset (`host_loop.py:3854`) is presentation-only once audio draws from P, so it can stay.

---

## 7. Recommended design

### 7.1 Generator
- New module `engine/appc/presentation_rng.py`:
  - `_rng = random.Random(PRESENTATION_SEED)`;
  - `rand(n)` with exactly `GetRandomNumber` semantics (`n <= 0 → 0`, `randrange(int(n))`);
  - `random()`, `uniform()`, `gauss()`, `randrange()`;
  - `reset(seed=PRESENTATION_SEED)`.
- **Seeding policy:** a fixed constant, **reseeded at every mission load**. Put the reset in the mission-swap block next to `hull_hit_smoke.reset()` (`host_loop.py:7904`) and in the `tests/conftest.py` autouse reset beside `reset_random_unit_vector_rng`.
  - Per mission rather than per session, so a capture of mission N looks the same regardless of what ran before. It never needs to be unpredictable.
  - `damage_preview._apply_seed` (`damage_preview.py:71-90`) should seed P too, which also fixes its "captures are not identical" caveat.

### 7.2 Scoped override for SDK presentation calls
- `presentation_rng.scope()` is a context manager that increments a **thread-local** depth. The roadmap moves presentation to an effect queue and the Python work to its own thread, so a global flag would leak across threads.
- `_SystemWrapper.GetRandomNumber` (`App.py:998-1001`) answers from P while the depth is above 0.
- `ObjectClass.GetRandomPointOnModel` (`objects.py:362-404`) takes its randomness from P in scope and from S2 otherwise. Refactor it into `_random_point_on_model(rng)` so engine code can choose the stream explicitly.
- Wrap:
  - `_play_audio`'s picker calls (`hit_feedback.py:470-492`);
  - `hull_hit_smoke._emit_smoke` (`:121-127`);
  - `death_cascade._fire_final` (`:263-288`), `_debris_explosion` (`:293-305`), `_death_sound` (`:322-332`);
  - `build_sequence_clips` (`bridge_idle_gestures.py:28-31`), which covers both hit reactions and idle gestures;
  - `crew_speech._rand5` → `presentation_rng.rand`;
  - NanoFX compat draws;
  - **`RunDeathScript`: needs Mark's decision.** All stock death-script draws are cosmetic, but a mod script could draw for gameplay inside it.
- In scope and nested gameplay: a presentation call that triggers gameplay (none known in stock) would draw from P. Add a debug assert in `combat.apply_hit` that the depth is 0, to catch it.

### 7.3 Direct moves (engine code that draws itself)
- H1 `hull_hit_smoke.py:93` and H2 `:123` → `presentation_rng.rand`.
- H4 `particles.py:65` → `presentation_rng.random()`.
- X4 `viewscreen_static.py:38` default `rng=presentation_rng.random`.
- X5 `minor_contact.py:74` → P.
- D6 `death_cascade.py:302` → P.

### 7.4 Mixed cases
- **D3/D4/D5 (`_fire`):** draw the gameplay roll D5 first, on S1. If it passes, draw the damage point from S2 (gameplay) and reuse it for the VFX, so the hole and the blast still coincide. If it fails, draw the VFX point from P.
  - D4 `roll_blast_scale` → P. It is the visible tier under Ruling 5, and its breakup tail on an already-dying ship is accepted as presentation-driven (**flag to Mark**). **Reversed in the build (2026-11-02, final review I1):** only a damaging blast makes a hole, and its size reaches gameplay through `hole_scale` around `AddDamage`, so a damaging blast draws its size on S1 right after its damage roll; a non-damaging blast's size feeds only particles and light and stays on P.
  - D1 and D2 stay on S1.
  - This is a one-time order change, in line with the roadmap.
- **D12 debris spin:** stays on S2 (collidable body) or moves to a gameplay-private generator. Leave as is.
- **M2/A3 (SDK line picks inside gameplay handlers):** stay on S1. They can't be separated without editing the SDK. Note as residual.
- **X6 DynamicMusic:** residual on S1 unless the music callbacks are wrapped.
- **A1 AI `random.choice`:** stays on S2. Once H4, X4, X5 and D3's VFX half leave S2, the only S2 consumers are AI (A1), gameplay surface points and debris spin.

### 7.5 Tests that pin "a cosmetic roll no longer shifts a gameplay roll"
1. **Unit:** inside `scope()`, `GetRandomNumber` leaves `App.g_kSystemWrapper._rng.getstate()` unchanged and advances P. Outside, the reverse.
2. **Unit:** one `hit_feedback.dispatch` hull hit (torpedo, sound manager present, instance map with a fake `world_to_body`) leaves the S1 and S2 `getstate()` unchanged.
3. **Unit:** `death_cascade`: seed S1 and S2 and run `begin` plus `advance` to the end, recording (D1, plan, D5 outcomes, damage points). Run again with the effect level LOW / sound forced / an extra `presentation_rng.rand` between blasts. The records must be identical.
4. **Integration falsifier:** the `combat_stress` fight twice with the same `seed_every_rng`. In the second arm, inject cosmetic noise every tick: monkeypatch `_audio_should_play` to always return True, call `presentation_rng.rand(1000)` N times, and run `build_sequence_clips` for a fake officer. Assert identical per-tick hull/shield/subsystem conditions, the event log, deaths, and the final S1/S2 state. Today the same test fails, which proves it pins something.
5. **Throttle:** `_audio_should_play` returns the same answer when `time.monotonic` jumps but game time does not, and the reverse. Also add the mission-swap reset.
6. **Source guard:** an AST test that the presentation modules (`hull_hit_smoke`, `particles`, `viewscreen_static`, `minor_contact`, `crew_speech`, the presentation functions of `death_cascade`) never reference `g_kSystemWrapper.GetRandomNumber` or module-level `random` directly.
7. **Update:** every `seed_every_rng` copy (§5) calls `presentation_rng.reset()`.

---

## 8. Other observations (outside the brief)

- `ship_death.begin` rolls the throes (`ship_death.py:89`) **before** `RunDeathScript` (`:98`). A death script's `SetLifeTime` (E7M1 `E7M1.py:1390` 4.0; E3M2 `E3M2.py:867` 2.0) therefore cannot shorten the rolled window. Instead it registers `object_lifetime` (`objects.py:905-908`), which `death_cascade.py:23-28` names as the cause of a duplicate `ET_OBJECT_DESTROYED`. **Inferred** consequence; not run.
- `visible_damage.advance` holds wear behind a **wall-clock** budget (`visible_damage.py:170-196`, `time.perf_counter`). When the breakup part check (gameplay) runs therefore depends on real time (live only).
- `crew_speech` and `speak_queue` expire speech on the wall clock (`fight_audio.py:13-15`). Whether an officer's line, and so its S1-drawing animation, plays depends on real time.
