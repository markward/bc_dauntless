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
