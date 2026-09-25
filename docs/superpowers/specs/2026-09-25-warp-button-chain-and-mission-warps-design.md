# The warp button chain and mission-advancing warps (design)

**Date:** 2026-09-25
**Status:** design approved in brainstorming; spec awaiting review. Not implemented.
**Branch:** `feat/system-frames` (Mark: the in-system warp depends on it, and the
branch does not merge before it anyway). Built **before**
`2026-09-25-in-system-warp-design.md`, whose rule D needs it.

## Goal

Pressing Warp runs BC's mission handlers again, so a mission can refuse a warp,
queue actions into it, or turn it into a jump to the next mission or episode.
And those jumps actually happen: the campaign advances through warps with the
player's own ship carried across, as BC does.

## Why (measured in the tree, 2026-09-25)

- **Nothing sends `ET_WARP_BUTTON_PRESSED`.** An `STWarpButton` click calls the
  engine's engage directly (`engine/ui/crew_menu_panel.py:227-233`;
  `engine/host_loop.py` ~8756 "Stage 1 deliberately bypasses the SDK
  ET_WARP_BUTTON_PRESSED / WarpPressed path"). The 26 Maelstrom handlers
  registered on the warp button, and SDK `HelmMenuHandlers.WarpPressed`, have
  never run. No mission can refuse a warp.
- **No warp changes mission.** `STWarpButton.get_mission_name` /
  `get_episode_name` have no callers; `WarpSequence.GetDestinationMission` /
  `GetDestinationEpisode` are hard-wired to None (`engine/appc/warp.py:652-653`);
  Set Course copies only the placement off a `SortedRegionMenu`, never its
  mission or episode name (67 SDK `SetMissionName`/`SetEpisodeName` sites).
  **The campaign stalls** wherever BC advances by warp: E6M5 → Episode 7, E7M6 →
  Episode 8, E6M1 → E6M2, and every menu-named mission.
- **The button's queues do not exist.** `AddActionBeforeWarp`,
  `AddActionBeforeDuringWarp`, `AddActionDuringWarp`, `AddActionAfterDuringWarp`,
  `AddActionAfterWarp`, `ClearBDASequences` (SDK `App.py:8723-8738`) are
  unimplemented — calls fall to a do-nothing stub. E6M5 and E7M6 queue their
  episode cutscenes there; E5M4 its win; E3M1 its rough-warp shake; E2M0 its
  Episode 2 cutscene; E4M5 its Chambana dialogue.
- **Direct episode loads stack on the live mission.** `Game.LoadEpisode` /
  `Episode.LoadMission` (`engine/core/game.py:322, 186`) import and initialise
  without terminating or clearing anything. E2M6 (`StartEpisode3`) and E5M4
  (`LoadNext`) call `LoadEpisode` from a sequence action.
- **The SDK's own `Terminate(pMission)` is never called** anywhere in `engine/`.

## How BC does it (SDK evidence; the C++ half is inferred)

- The button click sends `ET_WARP_BUTTON_PRESSED` with the **button as
  destination** (E6M5:2632, E7M6:959, E3M1:737 cast `pEvent.GetDestination()` to
  `STWarpButton`). Handlers run newest-first; `WarpPressed` is the oldest
  (registered at bridge build, `HelmMenuHandlers.py:259-261`). A handler that
  returns without `CallNextHandler` stops the warp.
- `WarpPressed` (`HelmMenuHandlers.py:726-916`) checks, speaks, starts the
  pre-warp camera, and passes on. It never builds the warp: that happens in C++
  after the chain (inferred), via `WarpSequence_Create` with the button's
  destination, placement, mission and episode, then `WarpSequence.SetupSequence`.
- `SetupSequence` (`WarpSequence.py:145-165`) plays the DURING piece after a
  player-only `WaitForQueued` (waits for `MissionLib.g_idMasterSequenceObj`), then
  POST_DURING, and places the ship there — "has to go after the during-warp
  action, since mission changing may load new systems".
- The player survives a mission change **in the warp set**: missions'
  `Terminate` call `MissionLib.DeleteShipsFromWarpSetExceptForMe()`, and
  `MissionLib.CreatePlayerShip` (`MissionLib.py:538-620`) **reuses** the existing
  player when the class matches, ignoring the set and waypoint it was given.
  `Maelstrom.py:258-262` shows the bridge set is "specifically ignored from
  mission to mission".

## Design

### 1. The warp button event

**Click Warp →** the engine sends `ET_WARP_BUTTON_PRESSED` to the warp button
(destination = the button), through the ordinary synchronous dispatch
(`engine/appc/events.py`, LIFO). Mission handlers run newest-first; one that
does not pass the event on stops the warp.

**The bottom of the chain is the engine's step, not `WarpPressed`.** When
`HelmMenuHandlers` registers `WarpPressed` on the button, the engine registers
its own final handler in that place. It runs `warp_gates.warp_gate` (the port of
`WarpPressed`'s seven checks and lines — speaking the deny line and stopping on
refusal), then the existing engage steps (`announce_warp_engaged`, Helm menu
disable, `drop_menus_turn_back`), then builds and plays the warp. `WarpPressed`
itself is not run: its pre-warp camera cutscene would fight the flythrough.
The gate therefore runs **exactly once**, and the direct-call bypass in
`crew_menu_panel.py` / `engage_warp` is removed.

**The warp is built from the whole button:** destination set, placement,
mission, episode, and the five queues. `WarpSequence.GetDestinationMission` /
`GetDestinationEpisode` return the real names (`ConditionWarpingToMission` reads
them).

**The five queues** on `STWarpButton`: `AddActionBeforeWarp`,
`AddActionBeforeDuringWarp`, `AddActionDuringWarp`, `AddActionAfterDuringWarp`,
`AddActionAfterWarp(action, delay=0.0)`; `ClearBDASequences` empties all five.
Queues are consumed by the warp they are built into (a refused warp leaves them
for the next press, as BC's button holds them). They play at these points of
our tunnel sequence:

| Button queue | Plays |
|---|---|
| before warp | at engage, before the align |
| before-during, then during | in transit, after departure |
| after-during | in transit, after the during queue — the mission change (§2) runs here |
| after warp | after arrival, once control returns |

**Transit holds.** Today the destination swap is on a fixed timer. It becomes
chained: the swap waits until the during queues have finished **and** the
mission's master dialogue sequence (`MissionLib.g_idMasterSequenceObj`) is idle —
BC's `WaitForQueued`, player only. The streak simply holds until then.

**Set Course carries mission and episode.** `record_course_selection` copies the
chosen `SortedRegionMenu`'s `GetMissionName()` / `GetEpisodeName()` onto the
button alongside the placement; a new pick clears names from an older one.

### 1b. The tunnel runs through BC's `warp` set

Added in planning (Mark: option A). The handlers this spec switches on expect
BC's warp set: E6M5 and E7M6 call `App.WarpSequence_GetWarpSet()` then
`Warp_P.LoadPlacements("warp")` and queue their episode cutscene to play there;
E6M1–E6M5's `PlayerEntersWarpSet` (on `ET_ENTERED_SET`) create ships during the
tunnel that E6M1 dereferences on arrival without a None check; 12 missions test
`GetName() == "warp"` as their in-transit guard. Today the tunnel parks the
player in a private `_WarpTransit` set that is recreated per warp, deleted on
arrival, and deliberately excluded from `ET_ENTERED_SET`/`ET_EXITED_SET`
(`engine/appc/sets.py:300`), and `WarpSequence_GetWarpSet` is unimplemented.

- **`App.WarpSequence_GetWarpSet()`** returns the set named `"warp"`, creating
  it on first call. It is the tunnel's transit set.
- **It persists.** Departure no longer deletes and recreates it, and arrival no
  longer deletes it — objects a mission put there (placements, ships) survive
  until the mission clears them (`MissionLib.DeleteShipsFromWarpSetExceptForMe`)
  or the mission changes. It survives the §2 clear while the player is in it.
- **Entering and leaving it are ordinary set transitions:** the
  `_WARP_TRANSIT_SET_NAME` broadcast exclusion is removed, so `ET_ENTERED_SET` /
  `ET_EXITED_SET` fire for the player and missions' `PlayerEntersWarpSet` run.
- BC's own region banner already skips it (`HelmMenuHandlers.py:407`,
  `GetName() != "warp"`).

### 2. Changing mission in transit

When the warp names a mission or episode different from the current one, the
change runs in transit, at the after-during point, before arrival:

1. **End the old mission:** the SDK's `Terminate(pMission)` on the mission
   module; the episode module's `Terminate` too when the episode changes.
2. **Clear the old world, keeping three things:** the `Game`; the player's ship
   (in the warp transit set); the bridge set. Every other set is deleted and the
   mission's timers, event handlers and render instances go with it. Every item
   `reset_sdk_globals()` / `_drain_pending_swap` resets today is sorted into
   **keep** or **reset** with a stated reason — a plan task, whose table lands in
   this spec.
3. **Load the next:** a new episode through `Game.LoadEpisode`, whose
   `Initialize` picks its first mission as BC's episode scripts do; a new
   mission alone through `Episode.LoadMission`. The mission's own `Initialize`
   runs; its `CreatePlayerShip` reuses the ship (or swaps the class if the
   mission names another), its `LoadBridge` handles the bridge. `ET_MISSION_START`
   is posted as today.
4. **Arrive** at the button's destination set and placement — which exists now,
   because the new mission created it — through the tunnel's existing arrival.

**One mission-change path.** `Game.LoadEpisode` and `Episode.LoadMission`, when
a mission is already running, perform the same change (steps 1-3) — so E2M6's
and E5M4's direct loads stop stacking on the live mission. A change already in
progress is not started twice (E5M4 queues its win on the button **and** calls
`LoadEpisode`).

**Unchanged:** the dev mission picker keeps its full reset (`swap_mission`).

#### Keep / reset table (`engine/core/mission_change.py`)

Derived from `reset_sdk_globals` and `_drain_pending_swap`. The shared resets
are named helpers in `engine/host_loop.py` (`_reset_timers`,
`_reset_action_registry`, `_reset_session_scratch`, `_reset_missionlib_state`,
`_reset_system_loader_state`, `_reset_sensor_state`) called by both paths.
Rows marked † were changed from the plan's draft because the code proved the
draft wrong.

| Item | Carry-over change | Why |
|---|---|---|
| `Game`, player ship object, its subsystems/damage/AI-free state | **keep** | BC reuses the player (`MissionLib.CreatePlayerShip` reuse branch) |
| Bridge set(s) and bridge characters | **keep** | "specifically ignored from mission to mission" (`Maelstrom.py:258-262`) |
| `"warp"` set, and the player's containing set | **keep** | the player is in it |
| Every other set | **reset** (teardown hook + `DeleteSet`) | BC's unload deletes them |
| Game/realtime timer managers | **reset except** survivors | the warp must finish; everything else is the old mission's |
| Game clock (`_time`) | **keep** | the warp's hold deadline and every surviving timer are on it |
| `_appc_actions` deferred-playing registry | **reset except** survivors | as timers |
| Event manager **func** broadcast handlers † | **reset** those owned by the old Mission, a replaced Episode, a deleted set or an object in one; **keep** the rest (the input handler stays registered, so it is not re-added) | the kept bridge's menus (`HelmMenuHandlers`, `EngineerCharacterHandlers`, `PowerDisplay`, …) register theirs once, in `LoadBridge.CreateAndPopulateBridgeSet`, which never runs again for a kept bridge set |
| Event manager **method** broadcast handlers † | **reset** those whose wrapped instance is a `Conditions.*` or `AI.*` object; **keep** the rest | conditions and AI are the old mission's and its ships'; `DynamicMusic` is initialized once per Game (`Maelstrom.py`) and its `ET_MISSION_START` handler exists for exactly this change |
| `crew_speech` bus | **reset** | as swap |
| `contact_index` † | **reset** the deleted sets' buckets only (`forget_set`) | buckets are event-maintained; a full reset would drop the player from the kept warp set for good |
| `ObjectGroup._live` | **reset** | as swap |
| Tooltip throttle/owner | **reset** | as swap |
| Projectile module cache | **keep** | same SDK tree |
| `MissionLib.ResetViewscreen()`, `g_idMasterSequenceObj = NULL_ID` | **reset** | the queued dialogue finished before the change point |
| `system_loader.reset()`, `_mapped_body_warned` | **reset** | new mission, new systems |
| Waypoint registry | **reset** entries not contained in a kept set | names repeat across sets |
| `App._next_event_type_id` | **keep** | kept objects may hold allocated types |
| Target menu singleton, TCW singleton, `st_widgets` registry, ShipDisplay slots, TacticalInterfaceHandlers/manual_aim/crew hotkeys re-wire † | **keep** | `LoadBridge.Load` returns early for an existing bridge set of the same config (`IsSameConfig`) and otherwise swaps only model/characters; `CreateCharacterMenus` runs only in `CreateAndPopulateBridgeSet`, so a reset TCW would never get its menus back |
| `top_window` shim | **keep** | the warp's cinematic/control state is live |
| `render_instances` mirror | **keep** | the player and the bridge are still drawn; deleted sets' instances go through the teardown hook |
| Nebula trackers, concealment latches, `_last_identify_gt` | **reset** | as swap |
| `g_kTGActionManager._registered` | **reset except** survivors | as timers |
| dev tutorial flag | **re-apply** | as swap |
| Render origin, camera eye, focus solver, WarpVFX / warp_state / `ReturnControl` | **keep** | the camera is mid-flight and the warp is live |
| Per-ship engine modules (`ship_lifecycle`, `ship_death`, `visible_damage`, `registry_texture`, `hit_feedback` throttles, …) | **keep** | keyed per ship; the player's entries must survive; deleted ships' entries go with `DeleteSet` |

**Survivors.** `TGTimer` records no owner; its event's destination *is* the
owner — the `TGSequence` for a step delay, the action itself for a
`_complete_after` deferral (`_HoldUntilAction`, sound waits). The survivors are
every playing `WarpSequence` whose ship is the player, plus every action and
dependency in its steps, recursively through nested sequences (a during-warp
cutscene). A timer, deferred-playing entry or named-action registration
survives iff its owner is a survivor. Not covered: a leaf a survivor spawns
dynamically without making it a step (e.g. a script action that queues onto
MissionLib's master sequence) — its timers are the old mission's and go.

## Testing

**In the gate (`scripts/check_tests.sh`):**

- **Chain:** handlers run newest-first; a swallowing handler stops the warp; a
  passed event reaches the engine step; `warp_gate` runs exactly once and its
  refusal stops the warp with the deny line.
- **Queues:** each of the five plays at its point; `ClearBDASequences` empties
  them; transit holds until the during queues and the master dialogue sequence
  finish.
- **Set Course:** mission and episode names reach the button; a new pick clears
  stale ones; `GetDestinationMission`/`GetDestinationEpisode` report them.
- **Mission changes, headless:** E6M5 → Episode 7 (E7M1 at Starbase 12);
  E7M6 → Episode 8; E6M1 → E6M2 via the Set Course menu; E2M6's direct load →
  Episode 3. In each: the **same ship object** arrives, damage intact; the old
  mission's `Terminate` ran; only the bridge set survived the clear; no second
  change starts.
- **Warp set:** `WarpSequence_GetWarpSet()` returns one persistent `"warp"`
  set; the tunnel parks the player there; `ET_ENTERED_SET` fires for it; objects
  a mission put there survive arrival; E6M1's in-tunnel Artrus ships exist on
  arrival.
- **Sweep:** every campaign mission loads, Warp is pressed headlessly, and
  nothing raises — all 26 handlers exercised.

**Live (Mark):** finish E6M5 and warp into Episode 7; finish E1M2 and continue
into Episode 2; attempt a warp a mission refuses (E1M1's tutorial).

## Risks

- **MissionLib module globals already carry across missions** (they are never
  reset — `reset_sdk_globals` docstring). BC carried them too, so this is
  probably right; unproven.
- **Bridge reuse** when the next mission loads the same bridge config.
- **E5M4's double load** — guarded.
- **Handlers that have never run** will now run in all 26 missions; the sweep
  catches crashes, not wrong behaviour. The live pass covers the three
  transitions most likely to matter.

## Deliberately out of scope

- `WarpPressed`'s pre-warp cutscene camera and its Helm "Yes" line (the
  flythrough replaces the first; the second was deliberately not reproduced).
- Loading screens / movies between episodes.
- Save/load across a mission change.
- Multiplayer (`Multiplayer/MissionShared.py`).
