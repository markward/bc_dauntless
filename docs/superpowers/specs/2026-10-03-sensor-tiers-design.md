# Sensor model sub-project 1 — two tiers — design

Status: design approved by Mark 2026-10-03 (brainstorming). Roadmap and standing
decisions: `2026-10-03-sensor-model-roadmap.md` — read it first; this spec does not
restate the evidence table.

## Goal

Split "listed" from "identified" the way BC does. A contact inside sensor range is
listed; it reads **"Unknown N"** in grey with restricted information until it has sat in
the **near band (half range)** for the **identification dwell (4.0 s)**, or until a scan
identifies it. The SDK's sensor surface — `FAR/NEAR_PROXIMITY`, `GetIdentificationTime`,
`IsObjectNear/Far/Visible` — becomes real. No occlusion; no change to AI.

## Current state (verified 2026-10-03)

- `sensor_identification.identify_contacts(player)` runs at ~4 Hz from `host_loop.py`
  (~:11055) and identifies every contact that passes `can_detect` — i.e. at **full**
  range, **instantly**. So nothing is ever listed-but-unknown passively.
- `_identify_one` is the single commit point (localise name → `AddKnownObject` → post
  `ET_SENSORS_SHIP_IDENTIFIED` with destination = object). Used by the passive sweep, Scan
  Area (`identify_all_in_set`), `IdentifyObject` and `ForceObjectIdentified` — all
  immediate.
- `ET_SENSORS_SHIP_FAR_PROXIMITY` / `NEAR_PROXIMITY` are never posted.
  `GetIdentificationTime` is a live stub (heatmap rank 149). `App.g_kRadarUnknownColor`
  is an undefined App constant (rank 182). `STSubsystemMenu.ShowUnknownName` /
  `ShowRealName` are no-ops (`engine/appc/target_menu.py:71-77`). `IsObjectNear`,
  `IsObjectFar`, `IsObjectVisible`, `GetSensorRange` are absent from `SensorSubsystem`.
- `ship_display_panel._resolve_ship_for_role` deliberately skips the SDK's
  `IsObjectKnown` gate (comment: "nothing scans for contacts yet").
- The target list and radar payloads use `ship.GetName()` as both the displayed text and
  the click/selection key (`engine/ui/target_list_view.py:295`, `sensors_panel.py`).
- Science adds a Scan Object button labelled `GetDisplayName()` on BOTH
  `ET_SENSORS_SHIP_IDENTIFIED` and `ET_TARGET_LIST_OBJECT_ADDED`
  (`ScienceMenuHandlers.py:91-94`); `CreateScanButton` de-dupes by that label (:179) and
  `ExitedSet` removes by it.

## Design

### 1. Contact manager — `engine/appc/sensor_contacts.py` (new)

One describable idea: *for the player's sensors, which contacts are in which band, and
which are on their way to being identified.* Player-only, as BC's manager is.

State (module-level, reset on mission swap and in `tests/conftest.py`'s autouse reset):
- `_near`, `_far`: sets of ships currently inside each band (weak-keyed, like the
  concealment latch).
- `_pending`: ship → `(commit_gt, by_scan)`. `by_scan` entries (from `IdentifyObject`)
  commit unconditionally; passive entries re-check at commit time.
- `_next_sweep_gt`: game time of the next sweep.

`tick(player, now_gt)` — called every sim tick from `host_loop` where the 4 Hz
`identify_contacts` call is today (sim-gated, never from `render_payload`). It:
1. Commits every `_pending` entry whose time has come — a scan entry always, a passive
   entry only **if the ship is still in the near band and still perceivable** (otherwise
   it is dropped and re-armed by a later sweep). Commit = `_identify_one`.
2. If `now_gt >= _next_sweep_gt`, runs the sweep and schedules the next one
   `sweep_period_s` later.

The sweep walks the player set's `GetObjectList()` filtered to `ShipClass` and `Planet`
(exactly the filter `identify_contacts` uses today — `contact_index` buckets ships only,
and planets must still be identifiable), skipping the player:
- `r = effective_sensor_range(player)`; `near = dist <= r * near_fraction`,
  `far = dist <= r`. **Pure distance**, as BC's bands are — no nebula, no cloak.
  (E8M1 depends on FAR firing for a ship inside a nebula before it is seen.)
- Band crossings post `ET_SENSORS_SHIP_FAR_PROXIMITY` / `ET_SENSORS_SHIP_NEAR_PROXIMITY`
  as a `TGBoolEvent`, bool = entered, **source = the ship** (the SDK handlers read
  `GetSource()`), destination = the player's sensor subsystem. Fired on enter and leave.
  Order within one sweep: FAR before NEAR on entry, NEAR before FAR on exit.
- A contact that is in the near band, passes `can_detect(player, ship)`, is not known and
  has no pending entry gets `_pending[ship] = (now_gt + identification_time(), False)`.

Set changes:
- `on_exited_set(set, obj)`: purge obj from `_near`, `_far`, `_pending`, and
  `RemoveKnownObject` it from the player's sensors (BC's `HandleExitSet`). If obj is the
  player: wipe the manager and the player's known set.
- Hooked from the existing `ET_EXITED_SET` posting in `engine/appc/sets.py:283-307`
  (direct call beside it, same shape as `contact_index.on_removed`), not a new handler.
- A player swap (`SetPlayer`) wipes the manager; the new player's known set is its own.

Identity survives leaving range: nothing here forgets a known contact except set exit.

### 2. `SensorSubsystem` surface — `engine/appc/subsystems.py`

| Method | Behaviour |
|---|---|
| `GetIdentificationTime()` | `sensor_dials.identification_time_s` (default 4.0) |
| `GetSensorRange()` | `sensor_detection.effective_sensor_range(parent ship)` — one rule |
| `IsObjectNear(obj)` | same set ∧ dist ≤ range × `near_fraction` |
| `IsObjectFar(obj)` | same set ∧ dist ≤ range |
| `IsObjectVisible(obj)` | BC's algorithm minus probes: range 0 → 0; target fully cloaked → 0; different set → 0; `jammed` = owner or target inside any nebula (`contact_index.nebulae_in` membership); `NormalPowerPercentage > 1.2` and not jammed → 1; `IsObjectFar` → 1; jammed → 0; else `IsObjectKnown(obj)` |
| `IdentifyObject(obj)` | **deferred**: `_pending[obj] = (now + dwell, True)` via the manager (no band or detection requirement — a scan reaches anywhere in the set); no-op if known; commits through `_identify_one` |
| `ForceObjectIdentified(obj)` | unchanged — immediate |
| `ScanAllObjects()` | the returned sequence identifies one contact per action, actions spaced by `GetIdentificationTime()`, skipping self and already-known (BC); same contact filter as today |

`IsObjectVisible` is consumed only by SDK callers that ask it directly
(TacticalInterfaceHandlers:797/867, E1M2:6694, E3M2:2558-2765). It is NOT a new list
gate — the list follows `can_detect` (roadmap decision 2).

Scan-path commits (`IdentifyObject`, `ScanAllObjects`) do not re-check the near band or
`can_detect` at commit time; the passive path does. Sub-project 2 adds the line-of-sight
condition to scans (roadmap decision 11).

### 3. Perception — `engine/appc/perception.py`

`Contact` gains `identified: bool` — the observer's `GetSensorSubsystem().IsObjectKnown`
(False when the observer has no sensors). Records are only ever built for the player;
AI code never reads them (`ai_driver` uses `is_hidden_by_cloak` directly, deliberately),
so this changes nothing for AI.
`subsystems_targetable` becomes `not cloaked and identified`. `perceivable` /
`targetable` are unchanged: unknown contacts are listed and lockable.

### 4. Unknown labels — `engine/appc/unknown_labels.py` (new)

One idea: *the placeholder name an unidentified contact shows.*
- `label_for(ship)` → `"Unknown N"` for an unknown, listed contact, else
  `ship.GetDisplayName()`. N is the lowest free positive integer, assigned on first
  request and held until `release(ship)`.
- Released on identification (from `_identify_one`, before the event is posted) and on
  set exit. Reset on mission swap.

### 5. Display

- **Target list.** `STTargetMenu.set_contacts` calls `row.ShowUnknownName()` /
  `row.ShowRealName()` from `Contact.identified`; those set the row caption via
  `unknown_labels` (they stop being no-ops). The row's affiliation reads `"UNKNOWN"` while
  unidentified (overriding `resolve_affiliation`, restored on identification).
  `ResetAffiliationColors` (called by E2M2/E2M6 after regrouping) must keep unknown rows
  `UNKNOWN`, or a mission regroup would reveal allegiance. Unknown rows show no subsystem
  rows (falls out of `subsystems_targetable`).
- **Payloads.** `target_list_view` rows gain a `label` field (the caption, from a new
  engine-only `STSubsystemMenu.GetCaption()`). `name` stays `ship.GetName()` — it is the
  selection/click key and must never change with identification. `target_list.js`
  displays `label`. `GetLabel()` keeps returning the REAL display name, because
  `STTargetMenu.GetSubmenuW` resolves rows by it for E2M0/E1M2 tutorial arrows. The radar
  draws no names (only a hidden `data-name` key), so it needs no label field.
- **Radar.** Unknown blips use the `UNKNOWN` affiliation colour (grey).
- **`g_kRadarUnknownColor`** gets a real definition on the App module (the SDK's
  `LoadInterface.py:140` sets it; the shim must not answer with a stub before then).
- **Target panels.** `ship_display_panel._resolve_ship_for_role` applies the SDK gate:
  target role resolves to None for an unknown target (the comment there anticipated this).

### 6. Science Scan Object button — no name leak

A thin wrapper installed beside the AI sensor gate (same idempotent-install pattern, own
module `engine/appc/science_scan_labels.py`):
- **`CreateScanButton`** is wrapped so the label it uses (both for the `GetButtonW`
  de-dupe and for `STButton_CreateW`) is `unknown_labels.label_for(obj)`.
- **`ExitedSet`** is wrapped to remove by the placeholder too when the object is unknown.
- **On identification**, `_identify_one` renames an existing placeholder button to the
  real display name (`STButton.SetLabel`) **before** posting `ET_SENSORS_SHIP_IDENTIFIED`.
  Otherwise Science's `ShipIdentified` misses the de-dupe and adds a duplicate.

Helm needs nothing: it adds Hail buttons only on identification, which is now later.

### 7. Dials — `engine/appc/sensor_dials.py` (new)

A "sensors" group registered with `engine/dev_dial_groups.py` (shared / L O keys):
`identification_time_s` (4.0, RE'd), `near_fraction` (0.5, RE'd), `sweep_period_s`
(1.0, RE'd). Production reads the constants; `--developer` reads the live dial (the
`dev_nebula_dials` pattern). Step sizes: 0.5 s, 0.05, 0.25 s; clamps keep each > 0 and
`near_fraction` ≤ 1.

### 8. Deletions

`identify_contacts` (the full-range passive sweep) and its `host_loop` 4 Hz call and
`_last_identify_gt` global are deleted; the manager replaces them. Tests that named them
are rewritten to drive the manager — and checked to still bite (this subsystem has a
history of tests going vacuous when a call becomes a no-op).

## Behaviour changes (deliberate, pinned by tests)

1. Contacts entering range now appear as "Unknown N", grey, without subsystems, Hail
   button or target panel, and become named ~4 s after reaching half range.
2. `IdentifyObject` (Scan Object) completes after the dwell; Scan Area identifies one
   contact per dwell interval.
3. Mission beats keyed on `ET_SENSORS_SHIP_IDENTIFIED` arrive later; beats keyed on
   FAR/NEAR proximity fire for the first time (E2M2 `ShipInSensorRange`, E2M6
   `Galors5And6OnSensors`, E8M1 `DetectingObject`/`DetectingKessok`).

## Testing

TDD per task. Unit: the manager with a fake clock (bands, enter/leave events and their
source, dwell commit, dwell abort on leaving near band or losing `can_detect`, set-exit
purge, player-exit wipe); `IsObjectVisible`'s eight steps; label allocation and release;
the Science wrapper's de-dupe across identification (no duplicate button). Integration
(headless missions): E1M2 Scan Area flow; E2M1 unknown-contacts line then naming; E2M2
low-sensor arrival — ships listed grey, scan prompt, scan identifies; E8M1 FAR before NEAR
in Belaruz 1; E2M6 Galors on-sensors beat. Gate: `scripts/check_tests.sh` exit 0.

## Risks

- **Scan timing.** E1M2's `ScanComplete` and E2M2's scan handlers assumed instant
  identification; the dwell may reorder their beats. Integration tests drive them through
  to completion.
- **Event shape.** If `TGBoolEvent` is not the shape BC used for the entered bit, no SDK
  handler notices (none reads it); recorded as RE-inferred.
- **The list-vs-memory gap** (roadmap decision 2) — live-check against Mark's memory of BC.

## Out of scope

Occlusion, the obscured window, lost tracks, nebula/field Unknown, E5M2 / Helm-race guards
(sub-project 2); probes and over-boost listing (later); AI identification (never — BC has
none).

## Live check (for Mark)

`./build/dauntless --developer` from this worktree. E2M1 opening: contacts appear grey as
"Unknown N", named a few seconds later; Science Scan Object shows no real names early.
E2M2 Serris 2 arrival with low sensors: ships listed unknown, scan names them. Dials:
Developer Options → Lighting → "Dial keys" → sensors.

## As built

Deviations from this spec made during execution, by task:

- **Task 4 (`sensor_contacts._sync_player`).** Wipes `_near`/`_far`/`_pending` only when
  a *previous* player existed and differs from the new one — not on first sight (when
  `_player_ref` is `None`, right after `reset()`). §1's "A player swap wipes the manager"
  is about swaps, not first observation: wiping unconditionally would let the very first
  tick after mission load silently cancel a scan `IdentifyObject`/`ScanAllObjects`
  scheduled moments earlier (Task 5's own test caught this). Risk if this ruling is wrong:
  a stale scan from a genuinely prior player could survive into the first tick after
  `reset()` — but `reset()` already clears `_pending`, so the exposure is ~0.
- **Task 5 (nav points).** Helm's `SetupNavPointsMenuFromSet` calls `IdentifyObject` on
  nav points, so nav points now become known only after the dwell instead of instantly.
  This is BC-faithful (the nav-point menu never reads `IsObjectKnown`) and not a
  regression; recorded because it's an observable timing change nobody asked for
  explicitly.
- **Task 5 (test fixture).** Scan-driven identification tests pin the session-global
  game clock (`App.g_kUtopiaModule`'s `GetGameTime`) rather than letting it run — the
  dwell is measured in that clock, and letting it free-run made the tests flaky.
- **Task 7 (Science rename).** `_identify_one`'s pre-identification Science-button
  rename uses a new `STMenu.RenameButton` (re-keys `STMenu._buttons` by the new label)
  instead of the spec's bare `STButton.SetLabel`. A bare `SetLabel` leaves the button
  dict keyed by the OLD placeholder label, so the SDK's post-identify `GetButtonW`
  de-dupe (keyed by current label) misses the existing button and adds a duplicate —
  which §6 explicitly forbids. `RenameButton` onto a label another button already holds
  overwrites that dict entry, the same tradeoff `STMenu.AddChild` already accepts and
  documents.
- **Task 9 (E8M1).** No headless test was added for `DetectingObject`/`DetectingKessok`
  (E8M1.py `BelaruzEvents`, registered at line 2221/2224). Unlike E2M2's
  `ShipInSensorRange` (registered unconditionally at mission `Initialize`), E8M1 only
  registers these handlers at the tail of `Belaruz1Arrive()`'s ~25-beat bridge cutscene,
  itself queued from an `EnterSet` handler gated on the player's set becoming
  `"Belaruz1"` — there is no mission-state shortcut comparable to
  `test_campaign_warp_transitions.py`'s warp drive. Per the task brief this is left as a
  live-check item rather than forced through headlessly: **live check** — reach Belaruz 1
  in E8M1 with the KessokHeavy inside far but outside near range; confirm sensors report
  it (FAR fires before the player can see it in the nebula) and that a subsequent NEAR
  crossing targets it and fires the Kessok-detected beat, matching `DetectingObject`'s
  self-removal via `RemoveBroadcastHandler` once it has targeted the ship.
- Minor, deferred (no behaviour impact, carried from earlier tasks' reviews): Task 1
  `identification_time_s`/`sweep_period_s` have no upper clamp; Task 2
  `IsObjectNear`/`Far`/`Visible` recompute distance and range per call; Task 4
  `on_exited_set` has no non-weakrefable-member guard (none exist today) and the wipe
  reaches into `sensors._known_objects` directly, duplicated between `reset()` and
  `_sync_player()`; Task 5 `schedule_area_scan`'s filter duplicates the
  `sensor_contacts._contacts` concept and `test_e1m2_scan_area` re-fetches the player
  redundantly; Task 6 `test_target_menu_shim::test_st_subsystem_menu_show_name_methods_are_noops`'s
  name/docstring is now stale (the methods are no longer no-ops); Task 6 imports
  `unknown_labels` inside the `set_contacts` loop rather than at module scope; Task 8
  `ship_display_panel` repeats the `IsObjectKnown` rationale in both a docstring and an
  inline comment.
