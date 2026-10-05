# Sensor model sub-project 2 — continuity and occlusion — design

Status: design approved by Mark 2026-10-05 (brainstorming). Roadmap and standing
decisions: `2026-10-03-sensor-model-roadmap.md` (decisions 7–11 are this sub-project).
Sub-project 1 (two tiers) is merged (`b1e1e05a`); its spec is
`2026-10-03-sensor-tiers-design.md`.

## Goal

Rocks, nebulae and cloak can hide a contact; asteroid fields and moderate nebula hide
its identity; and a short concealment does not cost the player a contact the ship's
computer can infer is the same object, while a long one loses the track.

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
   and target never occlude.

2. **Unknown by medium** — the contact stays listed and targetable, but reads "Unknown N"
   with restricted information (no subsystem rows, no target panel; AI ships lose
   subsystem aim, falling back to hull centre exactly as against a cloaked target).
   Causes: the target is inside an asteroid field
   (`far_tier.field_strength_at(target) ≥ field_unknown_threshold`, dial, default 0.5),
   or in moderate nebula (`concealment_at(target) ≥ nebula_unknown_threshold`, dial,
   default 0.14 — half of `LOCK_BREAK_T`).

### Continuity (player only — only the player identifies)

A contact is **concealed** when it is in the player's set, inside the player's sensor
range, and either hidden (`not can_detect(player, obj)`) or unknown by medium. Leaving
sensor range is NOT concealment — identity survives it (roadmap decision 3).

- **Concealed for less than `continuity_window_s`** (dial, default 5.0 s): identity is
  kept silently. A hidden contact's row disappears at once (Mark, 2026-10-05: no
  "obscured" row). The player's lock drops at once
  (`clear_undetectable_player_lock`, unchanged). An in-medium contact reads Unknown;
  if it leaves the medium within the window it shows its real name again.
- **Concealed for the whole window: lost track.**
  1. `sensors.RemoveKnownObject(obj)`;
  2. `Bridge.HelmMenuHandlers.ExitedSet(obj)` called directly — removes its Hail button
     (or fleet submenu). Never a synthetic `ET_EXITED_SET`.
  3. Science: a hidden contact has already left the target list, so the existing
     `ET_TARGET_LIST_OBJECT_REMOVED` → `ScienceMenuHandlers.ExitedSet` removed its Scan
     button. A contact **still listed** (in a medium) keeps its Scan button, relabelled
     from the real name back to its "Unknown N" placeholder (`STMenu.RenameButton`), so
     it can still be scanned (E2M1's Karoon among the asteroids).
- The clock is evaluated on the contact manager's sweep (`sweep_period_s`, 1 s), so the
  window is accurate to about ±1 sweep. Documented, not hidden.

### Re-identification

- **Passive** (sub-project 1's dwell) additionally requires the contact not to be
  concealed — nothing inside a field or behind a rock identifies passively.
- **Scan** (`IdentifyObject`, `ScanAllObjects`) identifies through a medium but not
  through a major rock: a pending scan entry whose target is rock-blocked when it falls
  due is dropped. A ship scanned while inside a medium shows its real name for one
  `continuity_window_s` from the scan; if it is still concealed at the end of that
  window, the track is lost again (Mark, 2026-10-05).

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
| `engine/appc/sensor_occlusion.py` (new) | Does a major rock block the line A→B? | Segment-vs-sphere on `effective_radius`, excluding A and B. Per-set major-rock list built once per sim tick; per-(A, B) answers cached for the tick, keyed on game time. Never raises (a failure answers "not blocked" and is logged once). |
| `engine/appc/sensor_media.py` (new) | Is this target inside a medium that hides its identity? | `medium_unknown(target)`; `subsystems_hidden(target)` = `medium_unknown or is_hidden_by_cloak`. |
| `sensor_detection.can_detect` | (unchanged idea) | Gains the occlusion gate after range, before the nebula gate. Skipped when `ENHANCED_SENSOR_CONTEST` is False, so "off" restores pre-stage-4 behaviour. |
| `sensor_contacts` | (unchanged idea, plus continuity) | `_concealed_since[obj]`, `_scanned_at[obj]`; lost-track side effects; passive arm/commit require not concealed; scan commit drops rock-blocked targets. |
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
3. Concealment of the full window forgets identity and removes the Hail button; the
   ship must be identified again.
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

## Out of scope

Probes and over-boost listing (roadmap "later"); planets/suns as occluders; fields
occluding between ships; partial-lock UI; a set-explicit field model.

## Live check (for Mark)

`./build/dauntless --developer` from this worktree. E2M1: let the Karoon drift into the
asteroids — E2M1's are loose major rocks, so expect line-of-sight drops (and, if a field
also covers the spot, Unknown); it must stay recoverable and scannable, and after ~5 s
hidden it loses its Hail button until identified again. For field Unknown, use the
developer mission "Rock Fields: inside Beol 4". Fly so a big rock sits between you and a
ship: it drops off the list and radar, reappears with its name if it was hidden <5 s.
Dials: Developer Options → Lighting → "Dial keys" → sensors.
