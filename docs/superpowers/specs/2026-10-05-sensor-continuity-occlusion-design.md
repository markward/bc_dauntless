# Sensor model sub-project 2 — continuity and occlusion — design

Status: design approved by Mark 2026-10-05 (brainstorming). Roadmap and standing
decisions: `2026-10-03-sensor-model-roadmap.md` (decisions 7–11 are this sub-project).
Sub-project 1 (two tiers) is merged (`b1e1e05a`); its spec is
`2026-10-03-sensor-tiers-design.md`.

## Goal

Rocks, nebulae and cloak can hide a contact; asteroid fields and moderate nebula hide
its identity; and a short concealment does not cost the player a contact the ship's
computer can infer is the same object, while a long one loses the track. Only a
HIDDEN contact (rock, dense nebula core) can lose the track: cloak and a medium alone
never do (Mark's rulings 1A/2A, 2026-10-05 — see Continuity).

## Rules

### Two kinds of concealment

1. **Hidden** — the contact is dropped from the list, the radar, weapons, torpedoes and
   AI target selection. Causes:
   - a **major rock** blocks the line between the observer's and the target's centres
     (new — this sub-project);
   - the target is in the **dense nebula core** (`concealment_at ≥ LOCK_BREAK_T`, with
     the existing hysteresis — unchanged);
   - the target is **cloaked outside the detection bubble** (unchanged).
   A major rock is a `RockClass` in the observer's set whose scaled radius
   (`rocks.rock.effective_radius`) is at least `min_blocker_radius_gu` (dial, default
   2.0 GU — the size at which a breakup remnant becomes targetable). Planets, suns, ships
   and minor/near-band rocks never occlude (roadmap decision 7). Fields between observer
   and target never occlude. A rock whose sphere contains the observer's centre or the
   target's centre does not occlude that pair: that ship is beside the rock, not behind
   it (final-review fix 1 — otherwise a ship parked against a big rock was blind in every
   direction and hidden from everyone).

2. **Unknown by medium** — the contact stays listed and targetable, but reads "Unknown N"
   with restricted information (no subsystem rows, no target panel; AI ships lose
   subsystem aim, falling back to hull centre exactly as against a cloaked target).
   Causes: the target is inside an asteroid field
   (`far_tier.field_strength_at(target) ≥ field_unknown_threshold`, dial, default 0.5),
   or in moderate nebula (`concealment_at(target) ≥ nebula_unknown_threshold`, dial,
   default 0.14 — half of `LOCK_BREAK_T`).

### Continuity (player only — only the player identifies)

A contact is **concealed** — runs the lost-track clock — when it is in the player's set,
inside the player's sensor range, and **hidden** (`not can_detect(player, obj)`: a major
rock or the dense nebula core). Leaving sensor range is NOT concealment — identity
survives it (roadmap decision 3). Mark's rulings (2026-10-05) narrow it further:

- **1A — cloak never starts the clock.** Identity survives cloak, as in BC. A fully
  cloaked target (`sensor_detection.is_hidden_by_cloak`) is never concealed; its row and
  list behaviour is unchanged (`can_detect` still decides perception). On decloak it
  shows its real name at once.
- **2A — a medium alone never loses the track.** Unknown by medium only changes the
  DISPLAY (`shows_identity` False: "Unknown N", no subsystems, AI subsystem aim hidden);
  the ship stays known however long it stays in the field or moderate nebula.

- **Concealed for less than `continuity_window_s`** (dial, default 5.0 s): identity is
  kept silently. A hidden contact's row disappears at once (Mark, 2026-10-05: no
  "obscured" row). The player's lock drops at once
  (`clear_undetectable_player_lock`, unchanged).
- **Concealed for the whole window: lost track.**
  1. `sensors.RemoveKnownObject(obj)`;
  2. `Bridge.HelmMenuHandlers.ExitedSet(obj)` called directly — removes its Hail button
     (or fleet submenu). Never a synthetic `ET_EXITED_SET`.
  3. Science: a contact that has left the target list had its Scan button removed by
     the existing `ET_TARGET_LIST_OBJECT_REMOVED` → `ScienceMenuHandlers.ExitedSet`. A
     contact **still listed** keeps its Scan button, relabelled from the real name back
     to its "Unknown N" placeholder (`STMenu.RenameButton`), so it can still be scanned.
- The clock is evaluated on the contact manager's sweep (`sweep_period_s`, 1 s), so the
  window is accurate to about ±1 sweep. Documented, not hidden.

### Re-identification

- **Passive** (sub-project 1's dwell) additionally requires the contact not to read
  Unknown by medium (it already required `can_detect`) — nothing inside a field, a
  moderate nebula or behind a rock identifies passively.
- **Scan** (`IdentifyObject`, `ScanAllObjects`) identifies through a medium but not
  through a major rock: a pending scan entry whose target is rock-blocked when it falls
  due is dropped. A ship scanned while inside a medium shows its real name for one
  `continuity_window_s` from the scan; after that window its display simply reverts to
  Unknown and it stays known (ruling 2A). A HIDDEN ship scanned (dense nebula core) has
  its clock restarted from the scan: one window, then the track is lost again.

### Guards

- **E5M2** — `Maelstrom.Episode5.E5M2.E5M2.ShipIdentified` (E5M2.py:610) replays
  dialogue and re-adds a goal on every Outpost identification. Wrapped so only the first
  Outpost identification per mission runs the mission body; later ones skip it and call
  `pObject.CallNextHandler(pEvent)`. Every other ship passes straight through.
- **Helm race** — `HelmMenuHandlers.AddHailButton` (HelmMenuHandlers.py:568) runs 1 s
  after identification and never re-checks. Wrapped to return 0 without adding when the
  player no longer knows the object.

Both wraps live in `engine/appc/sensor_mission_guards.py`, are idempotent, are installed
beside `science_scan_labels.install()` (boot and mission swap), and wrap by module
attribute (handlers resolve by name at dispatch — `engine/appc/events.py:_resolve_handler`).

## Architecture

| Unit | One idea | Notes |
|---|---|---|
| `engine/appc/sensor_occlusion.py` (new) | Does a major rock block the line A→B? | Segment-vs-sphere on `effective_radius`, excluding A and B and any rock whose sphere contains A's or B's centre. Per-set major-rock list built once per sim tick; per-(A, B) answers cached per set for the tick, keyed on game time. Never raises (a failure answers "not blocked" and is logged once). |
| `engine/appc/sensor_media.py` (new) | Is this target inside a medium that hides its identity? | `medium_unknown(target)`; `subsystems_hidden(target)` = `medium_unknown or is_hidden_by_cloak`. |
| `sensor_detection.can_detect` | (unchanged idea) | Gains the occlusion gate after range, before the nebula gate. Skipped when `ENHANCED_SENSOR_CONTEST` is False, so "off" restores pre-stage-4 behaviour. |
| `sensor_contacts` | (unchanged idea, plus continuity) | `_concealed_since[obj]` (hidden, non-cloaked contacts only), `_scanned_at[obj]`; lost-track side effects; passive arm/commit require `can_detect` and not Unknown by medium; scan commit drops rock-blocked targets. |
| `perception` | | `Contact.identified` = known ∧ (not `medium_unknown` ∨ scanned within the window). `subsystems_targetable` uses `sensor_media.subsystems_hidden`. |
| `ai_driver` | | Subsystem aim falls back to hull when `sensor_media.subsystems_hidden(target)` (was `is_hidden_by_cloak`). |
| `sensor_dials` | | Adds `continuity_window_s` 5.0, `min_blocker_radius_gu` 2.0, `field_unknown_threshold` 0.5, `nebula_unknown_threshold` 0.14. |
| `engine/appc/sensor_mission_guards.py` (new) | Mission/SDK re-identification guards | E5M2 Outpost, Helm AddHailButton. |

## Known limits (stated reasons)

- **Field strength covers the viewed set only.** `field_strength_at` reads the tile
  fields last pushed for `frames.viewing_set()`. Contacts in the player's set — the only
  ones the player identifies — are covered. AI-vs-AI in an unviewed set sees no field, so
  medium-Unknown never restricts their subsystem aim there. Accepted: the restriction is
  a display/aim nicety, and the alternative is a set-explicit field model this
  sub-project does not need.
- **Window granularity** is one sweep (≤1 s).
- **Centre-line occlusion**: a ship larger than the rock that half-covers it is either
  hidden or not by its centre line. The size dial is the lever.

## Performance

`can_detect` has 12 call sites, some per frame (firing chokepoint, perceived_by) and per
torpedo per frame, plus the AI candidate filters. The occlusion term must therefore be
cached per tick and cheap per rock. Verified two ways:
1. a headless benchmark test (`can_detect` with 54 major rocks — the Multi1 count — and
   a combat-sized roster) with a recorded budget;
2. a frame-profiler run (`docs/engine/frame-profiler.md`), CPU only, with
   `DAUNTLESS_MISSION=engine.dev_missions.combat_stress` and a rock-heavy mission,
   comparing occlusion on/off. **Mark approves each game launch first.**

## Behaviour changes (deliberate, pinned by tests)

1. A ship behind a major rock leaves the list, radar and weapons, for the player and AI.
2. A ship inside an asteroid field or moderate nebula reads Unknown with no subsystems,
   even if identified; AI cannot aim at its subsystems.
3. Being HIDDEN (rock, dense nebula core) for the full window forgets identity and
   removes the Hail button; the ship must be identified again. Cloak and a medium alone
   never lose the track (rulings 1A/2A): a cloaked ship keeps its identity, an in-medium
   ship keeps it but displays Unknown.
4. A scan of a ship behind a major rock does nothing.

## Testing

Unit: occlusion geometry (blocked / clear / small rock ignored / endpoints excluded /
scaled radius used), per-tick cache invalidation, `medium_unknown` thresholds,
continuity clock (window − ε keeps identity, full window loses it; leaving range never
starts the clock; a scan inside a field grants exactly one window), lost-track side
effects (RemoveKnownObject, Helm ExitedSet called, Science relabel when listed, no
synthetic ET_EXITED_SET), passive identification blocked while concealed, scan dropped
when rock-blocked, AI symmetry (candidate filter and subsystem aim), toggle-off restores
the old answer. Integration: E2M1 Karoon among the asteroids stays listed-or-recoverable
and scannable; E5M2 re-identification of the Outpost replays nothing; Helm race.
Benchmark as above. Gate: `scripts/check_tests.sh` exit 0 (except any failures recorded
as pre-existing on main with evidence).

## As built

Built on branch `feat/sensor-continuity` (local, unmerged). Rulings and deviations from
the SDD ledger (`.superpowers/sdd/2026-10-05-sensor-continuity-occlusion/progress.md`),
beyond what the Rules/Architecture sections above already describe:

- **`begin_tick` cache ruling.** `sensor_occlusion.begin_tick(now_gt)`, called first thing
  in `sensor_contacts.tick`, folds the contact manager's own tick time into BOTH the
  per-(observer, target) cache and the per-set major-rock-list cache, alongside App's game
  time. Production already advances App's game time every sim tick, so this changes no
  observable behaviour there — but tests (and this spec's own integration test) drive
  `sensor_contacts.tick(player, now_gt)` against a STATIC App game time while moving rocks
  or ships between calls, and App time alone would never invalidate either cache on a
  move. Cost if wrong: one extra element in each cache key.
- **Benchmark uses `time.process_time()`, not wall clock.** `test_sensor_occlusion_bench.py`
  measures CPU time: one `perf_counter` run hit 3.34× under shared-machine load while
  `process_time` runs sat at 1.4–2.4×. The budget is about this code's own CPU cost, not
  machine contention. Cost if wrong: misses a regression that only shows as wall-clock
  (e.g. waits), which this pure-CPU path cannot have.
- **Concealment keyword hand-off.** `sensor_media.medium_unknown(obj, *, concealment=None)`
  and `subsystems_hidden` forward a caller's own `concealment_at` sample unchanged, rather
  than re-deriving it — mirroring the existing `dist_sq_gu`/`concealment` precedent on
  `sensor_detection.can_detect`. `perception.perceived_by` is the one caller that supplies
  it, having already taken that density sample this frame for `can_detect` too; every
  other caller passes nothing and the function samples it itself. `concealment_at` is
  sampled ONCE per contact per frame, not twice.
- **`shows_identity(obj, now_gt=None, sensors=None)`.** "Known" is read from the passed
  `sensors` when given (`perceived_by` passes the observer's), else from the current game
  player's sensors (reticle, Science). Keeps sub-project-1 unit tests that identify via a
  bare `AddKnownObject` with no `Game` working, and keeps the answer observer-correct for
  `perceived_by(ai_ship)` callers. Cost if wrong: a slightly wider signature than strictly
  needed.
- **`STMenu.DeleteChild` now also drops the button/submenu from the label index**
  (`engine/appc/characters.py`), not only from `_children`. Without it, a lost-track Hail
  button stayed "found" by the SDK's label-keyed dedupe (`CreateHailButton`'s
  `GetButtonW` check) and could never be re-added once a track was lost and recovered.
  Identity-based removal, not label-based: a newer child sharing the old label keeps its
  own index entry.
- **Planets are exempt from concealment and Unknown-by-medium.** `_has_signature` restricts
  both `is_concealed` and `shows_identity`'s medium check to `ShipClass` contacts — a
  planet (any non-ShipClass contact) has no signature to hide, mirroring the existing
  exemption `sensor_detection.clear_undetectable_player_lock` already makes. Without it, a
  planet behind a rock or inside a field would lose its Hail button (E1M2's Haven).
- **A rescan of a KNOWN-but-Unknown-by-medium contact restarts its glimpse** without
  re-firing `ET_SENSORS_SHIP_IDENTIFIED` — `_identify_one` would refuse an already-known
  contact anyway, so `_commit_due`'s scan branch just re-stamps `_scanned_at` and, if still
  concealed, restarts `_concealed_since` from the scan. Matches Mark's rule that a scan
  names a contact for one window, repeatable.
- **Broadcast handlers are not chained in this engine.** `ET_SENSORS_SHIP_IDENTIFIED`
  reaches `E5M2.ShipIdentified` as a broadcast func handler; `TGEventManager.AddEvent`
  walks a flat snapshot and calls every registered handler unconditionally —
  `CallNextHandler` only advances a per-object dispatch frame that this path never pushes.
  The E5M2 guard's "already seen" branch therefore just `return`s (not
  `pObject.CallNextHandler(pEvent)`, which would be an inert no-op here) — correct, and
  clearer about what actually happens.
- **`install_after_import` is shared by both mission-load paths.** There are two
  independent paths that import a mission module and run its `Initialize()` — the dev
  loader (`host_loop._init_mission`) and the production campaign path
  (`engine.core.game.Episode._load_mission_raw`, reached through `Episode.LoadMission` /
  `mission_change.change()` while a mission is already running). Both call
  `sensor_mission_guards.install_after_import(module_name)` rather than a raw
  `importlib.import_module`, so the E5M2/Helm guards install before the module's own
  `Initialize()` can register its unwrapped handler on either path. A Task 5 review found
  the production path had been missing this call entirely.
- **Out of scope, surfaced not fixed:** re-entering E5M2 via `mission_change.change()` in
  one process raises `KeyError` from `CutsceneCameraBegin('CutsceneCam', 'bridge')`
  ("already been called on the set: bridge") because the kept bridge set's per-set
  registry is never cleared across the re-entry. `change()` catches it and returns
  `False`. Pre-existing, unrelated to sub-project 2's guards; surfaced for Mark, not
  addressed here.
- **Task 6 (this integration test):** `test_e2m1_karoon_hidden_then_recovered` drives the
  REAL `E2M1.CreateAsteroids` / `CreateBeolShips` (not a synthetic fixture) — every one of
  the mission's 16 Beol4 asteroids' `effective_radius` already clears `min_blocker_radius_gu`
  (2.0), so the mission's own asteroid field doubles as the occluder with no extra
  construction needed. The player boards at Vesuvi6 while the Karoon lives in Beol4
  (`CreateBeolShips`, normally deferred to `PlayerExitsSet`); the test moves the player
  into Beol4 directly (`RemoveObjectFromSet("player")` + `AddObjectToSet`), the same
  set-reassignment idiom `test_condition_all_in_same_set_live.py` uses — occlusion only
  ever looks at rocks in the OBSERVER's own set, so player and Karoon must share one.
  `SensorSubsystem.IdentifyObject` always schedules its due time off the REAL
  `App.g_kUtopiaModule.GetGameTime()` (static at 0.0 in this headless harness), not the
  synthetic clock the test drives `sensor_contacts.tick` on — so the scan's dwell is
  already elapsed the moment any later synthetic tick runs; the test does not attempt to
  pin a "not due yet" instant for the scan path (see the test's own comment).

- **Final-review rulings (Mark, 2026-10-05).** 1A: cloak never starts the continuity
  clock — `is_concealed` returns False for a fully cloaked target, so identity survives
  cloak as in BC; perception is unchanged. 2A: a medium alone never loses the track —
  `is_concealed` no longer includes `medium_unknown`; a medium only makes
  `shows_identity` False. Passive identification inside a medium is still blocked, via
  `sensor_contacts._unknown_by_medium` in the passive arm/commit gates. Tests that
  asserted the old behaviour (in a field for the window loses track; scan glimpse then
  lost track) were rewritten to the ruled behaviour; the lost-track paths they used to
  cover are now pinned on the dense nebula core.
- **Final-review fix 1 — beside a rock is not behind it.** `sensor_occlusion.blocked`
  skips any rock whose sphere contains the observer's or the target's centre. Before,
  the segment started inside the sphere, the closest point was the observer itself, and
  a ship parked against a big rock was blind in every direction and hidden from all.
- **Final-review fix 4.** `host_loop._reset_sensor_state` calls
  `sensor_occlusion.reset()` with every other sensor cache on a mission swap.
- **Final-review fix 5.** The pair cache is keyed per set (as the rock cache already
  was), each set with its own `(game time, tick time, rock count)` signature, so callers
  alternating between sets in one tick no longer clear each other's answers.

## Out of scope

Probes and over-boost listing (roadmap "later"); planets/suns as occluders; fields
occluding between ships; partial-lock UI; a set-explicit field model.

## Live check (for Mark)

`./build/dauntless --developer` from this worktree. E2M1: let the Karoon drift into the
asteroids — E2M1's are loose major rocks, so expect line-of-sight drops (and, if a field
also covers the spot, Unknown); it must stay recoverable and scannable, and after ~5 s
hidden behind a rock it loses its Hail button until identified again (in a field alone
it only reads Unknown, and keeps its Hail button). For field Unknown, use the
developer mission "Rock Fields: inside Beol 4". Fly so a big rock sits between you and a
ship: it drops off the list and radar, reappears with its name if it was hidden <5 s.
Park beside a big rock — the list stays (you are beside it, not behind it). E8M1
Belaruz: hail the KessokHeavy and command your fleet inside the nebula — they read
Unknown but keep their Hail/fleet buttons. A known ship that cloaks keeps its identity
and shows its real name the moment it decloaks.
Dials: Developer Options → Lighting → "Dial keys" → sensors.

Task 6 added a headless integration proof against this exact scenario
(`tests/integration/test_sensor_continuity_missions.py::test_e2m1_karoon_hidden_then_recovered`)
driving the real E2M1 asteroids and Karoon — it does not substitute for this live check.
