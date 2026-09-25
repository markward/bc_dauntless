# Warp Button Chain and Mission-Advancing Warps — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pressing Warp runs BC's mission handlers; missions can refuse a warp, queue actions into it, or turn it into a jump to the next mission or episode — and those jumps happen, carrying the player's ship across.

**Architecture:** The engine sends `ET_WARP_BUTTON_PRESSED` to the `STWarpButton`; the button's LIFO handler chain ends in an engine step (replacing SDK `WarpPressed`) that gates and builds the warp from the whole button — destination, placement, mission, episode and five action queues. The tunnel parks the player in BC's persistent `"warp"` set, holds in transit until queued actions finish, and — when the warp names a new mission or episode — ends the old mission, clears the world except the `Game`, the player's ship, the bridge set and the warp set, and loads the next mission in transit. `Game.LoadEpisode`/`Episode.LoadMission` route through the same change when a mission is already running.

**Tech Stack:** Python 3 (engine shim over BC's SDK scripts), pytest; no native changes.

**Spec:** `docs/superpowers/specs/2026-09-25-warp-button-chain-and-mission-warps-design.md` (read §1, §1b, §2 before any task).

## Global Constraints

- Worktree: `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/system-frames`, branch `feat/system-frames`. Never merge it.
- Every shell: `export DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" DAUNTLESS_SDK_DIR="/Users/mward/Documents/Star Trek Bridge Commander/sdk"`.
- BANNED git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs only. Temporary mutations: `cp` backup → edit → `cp` restore → `diff` must be silent.
- Never launch the game. Never spell `game` or `sdk` as a path segment in code; never capture a path at import.
- A failure is "pre-existing" only if `scripts/check_tests.sh` says so (baseline `tests/known_failures.txt`).
- SDK scripts are ground truth. Never edit anything under the SDK directory. Evidence tiers: tested > RE'd > SWIG (`App.py`) > SDK script; the C++ half of the warp build is **inferred** — say so in comments where behaviour rests on it.
- Implementers never dispatch subagents.
- Run tests with `uv run pytest <path> -q`.

## Review Focus

1. **A refused warp leaves the UI usable** — a mission handler that swallows the event must not grey the Helm menu or strand the player without control (the engine step, not the click, does the disable). Test in Task 3.
2. **A mission change whose next mission fails to import** must leave a playable state: the player stays in the warp set, the old world is already gone, the error is printed, and the warp completes its arrival to whatever destination set exists or stays parked — never an exception escaping the frame loop. Test in Task 6.
3. **A warp pressed twice** (click during an active warp) must not start a second warp or a second mission change. Test in Task 3.
4. **Stale mission names on the button** — picking a plain course after the button held a mission/episode (from Set Course or a mission's `SetDestination`) must not load that mission. Test in Task 4.
5. **The warp set across a dev mission swap** — `swap_mission` still clears everything including `"warp"`, so the next mission starts with a fresh warp set. Test in Task 2.

---

### Task 1: STWarpButton queues; WarpSequence carries mission and episode

**Files:**
- Modify: `engine/appc/tg_ui/st_widgets.py` (class `STWarpButton`, ~104-191)
- Modify: `engine/appc/warp.py` (`WarpSequence.__init__` ~644-653, `WarpSequence_Create` ~725, `execute_warp` ~901-919)
- Test: `tests/unit/test_warp_button_queues.py` (create)

**Interfaces:**
- Produces: `STWarpButton.AddActionBeforeWarp(action)`, `AddActionBeforeDuringWarp(action)`, `AddActionDuringWarp(action)`, `AddActionAfterDuringWarp(action)`, `AddActionAfterWarp(action, delay=0.0)`, `ClearBDASequences()`, and engine-only `STWarpButton.take_queues() -> dict[str, list[tuple[TGAction, float]]]` with keys `"before"`, `"before_during"`, `"during"`, `"after_during"`, `"after"` (returns and empties). `WarpSequence_Create(ship, dest_module, warp_time=0.0, placement="Player Start", mission=None, episode=None, queues=None)`; `WarpSequence.GetDestinationMission()` / `GetDestinationEpisode()` return the passed names (None when falsy).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_warp_button_queues.py
"""The warp button's five action queues (SDK App.py:8723-8738) and the warp
sequence carrying the button's mission/episode (spec §1)."""
import App
from engine.appc.actions import TGAction
from engine.appc.tg_ui.st_widgets import STWarpButton
from engine.appc import warp


def _a():
    return TGAction()


def test_each_queue_keeps_its_actions_in_order():
    b = STWarpButton("Warp")
    a1, a2, a3, a4, a5, a6 = (_a() for _ in range(6))
    b.AddActionBeforeWarp(a1)
    b.AddActionBeforeDuringWarp(a2)
    b.AddActionDuringWarp(a3)
    b.AddActionDuringWarp(a4)
    b.AddActionAfterDuringWarp(a5)
    b.AddActionAfterWarp(a6, 1.5)
    q = b.take_queues()
    assert q["before"] == [(a1, 0.0)]
    assert q["before_during"] == [(a2, 0.0)]
    assert q["during"] == [(a3, 0.0), (a4, 0.0)]
    assert q["after_during"] == [(a5, 0.0)]
    assert q["after"] == [(a6, 1.5)]


def test_take_queues_empties_them():
    b = STWarpButton("Warp")
    b.AddActionDuringWarp(_a())
    b.take_queues()
    assert all(v == [] for v in b.take_queues().values())


def test_clear_bda_sequences_empties_all_five():
    b = STWarpButton("Warp")
    b.AddActionBeforeWarp(_a())
    b.AddActionBeforeDuringWarp(_a())
    b.AddActionDuringWarp(_a())
    b.AddActionAfterDuringWarp(_a())
    b.AddActionAfterWarp(_a())
    b.ClearBDASequences()
    assert all(v == [] for v in b.take_queues().values())


def test_warp_sequence_reports_mission_and_episode():
    ship = App.ShipClass_Create()
    seq = warp.WarpSequence_Create(ship, None, 0.0, "Player Start",
                                   mission="Maelstrom.Episode7.E7M1.E7M1",
                                   episode="Maelstrom.Episode7.Episode7")
    assert seq.GetDestinationMission() == "Maelstrom.Episode7.E7M1.E7M1"
    assert seq.GetDestinationEpisode() == "Maelstrom.Episode7.Episode7"


def test_warp_sequence_mission_defaults_stay_falsy():
    ship = App.ShipClass_Create()
    seq = warp.WarpSequence_Create(ship, None, 0.0, "Player Start")
    assert seq.GetDestinationMission() is None
    assert seq.GetDestinationEpisode() is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_warp_button_queues.py -q`
Expected: FAIL — `take_queues` / `AddAction*` resolve to a do-nothing `_Stub`, and `WarpSequence_Create` rejects `mission=`.

- [ ] **Step 3: Implement the queues** — in `STWarpButton.__init__` add `self._queues = {k: [] for k in ("before", "before_during", "during", "after_during", "after")}`, and the methods:

```python
    # BC's five warp-button queues (SDK App.py:8723-8738). Missions fill them
    # from their ET_WARP_BUTTON_PRESSED handlers (E6M5:2672 queues the
    # Episode 7 cutscene BeforeDuring; E4M5:1646 AddActionAfterWarp(seq, 0.0)).
    # The C++ that merged them into the warp is not in the SDK; where each
    # plays is spec §1's table (inferred from WarpSequence.SetupSequence).
    def AddActionBeforeWarp(self, action):         self._queues["before"].append((action, 0.0))
    def AddActionBeforeDuringWarp(self, action):   self._queues["before_during"].append((action, 0.0))
    def AddActionDuringWarp(self, action):         self._queues["during"].append((action, 0.0))
    def AddActionAfterDuringWarp(self, action):    self._queues["after_during"].append((action, 0.0))
    def AddActionAfterWarp(self, action, delay=0.0):
        self._queues["after"].append((action, float(delay)))

    def ClearBDASequences(self):
        for v in self._queues.values():
            v.clear()

    # engine-only: the warp that is built consumes the queues.
    def take_queues(self):
        taken = {k: list(v) for k, v in self._queues.items()}
        self.ClearBDASequences()
        return taken
```

- [ ] **Step 4: Carry mission, episode and queues into the sequence** — `WarpSequence.__init__(self, ship, dest_module, warp_time, placement, mission=None, episode=None, queues=None)` stores `self._dest_mission = mission or None`, `self._dest_episode = episode or None`, `self._queues = queues or {k: [] for k in ("before","before_during","during","after_during","after")}`; replace the "No cross-mission warp path exists yet" comment block with one stating the names come from the button. `WarpSequence_Create(ship, dest_module, warp_time=0.0, placement="Player Start", mission=None, episode=None, queues=None)` passes them to the constructor (queues are **stored only** in this task; Task 5 plays them). `execute_warp` becomes:

```python
    placement = button.GetPlacementName()
    WarpSequence_Create(player, dest, button.GetWarpTime(), placement,
                        mission=button.get_mission_name() or None,
                        episode=button.get_episode_name() or None,
                        queues=button.take_queues()).Play()
```

- [ ] **Step 5: Run the new tests and the existing warp tests**

Run: `uv run pytest tests/unit/test_warp_button_queues.py tests/unit/test_warp_spine.py tests/unit/test_warp_vfx_sequence.py tests/unit/test_warp_placement_name.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/tg_ui/st_widgets.py engine/appc/warp.py tests/unit/test_warp_button_queues.py
git commit -m "feat(warp): the warp button's five queues; the sequence carries mission and episode"
```

---

### Task 2: The tunnel runs through BC's persistent `warp` set

**Files:**
- Modify: `engine/appc/warp.py` (`_WARP_TRANSIT_SET_NAME` :22, `_WarpDepartAction` ~520-575, `_ArriveFinalizeAction` ~596-640; add `WarpSequence_GetWarpSet`)
- Modify: `App.py` (project-root shim — export `WarpSequence_GetWarpSet` beside `WarpSequence_Create`, see `App.py:190`)
- Modify: `engine/appc/sets.py` (`_broadcast_set_transition` ~286-310: remove the transit-name exclusion)
- Test: `tests/unit/test_warp_set.py` (create); update `tests/unit/test_set_transition_events.py` (the transit-exclusion test ~L117 now asserts the opposite), `tests/unit/test_warp_spine.py:178`, `tests/unit/test_warp_vfx_sequence.py:85`, `tests/unit/test_warp_leaves_the_set_standing.py:90` (each asserts the transit set is deleted on arrival — now it persists)

**Interfaces:**
- Produces: `warp._WARP_TRANSIT_SET_NAME == "warp"`; `App.WarpSequence_GetWarpSet() -> SetClass` (get-or-create, never None).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_warp_set.py
"""The tunnel parks the player in BC's persistent "warp" set (spec §1b)."""
import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def setup_function(_):
    App.g_kSetManager._sets.clear()


def test_get_warp_set_creates_one_named_warp_and_returns_it_again():
    s = App.WarpSequence_GetWarpSet()
    assert s is not None and s.GetName() == "warp"
    assert App.WarpSequence_GetWarpSet() is s
    assert App.g_kSetManager.GetSet("warp") is s


def _ship_in(pSet, name):
    ship = App.ShipClass_Create()
    ship.SetName(name)
    pSet.AddObjectToSet(ship, name)
    return ship


def test_departure_parks_the_player_in_the_warp_set_and_keeps_its_contents():
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    ws = App.WarpSequence_GetWarpSet()
    other = _ship_in(ws, "Artrus 1")            # a mission's in-tunnel ship
    player = _ship_in(src, "player")
    warp._WarpDepartAction(src, player).Play()
    assert App.g_kSetManager.GetSet("warp") is ws          # not recreated
    assert ws.GetObject("player") is player
    assert ws.GetObject("Artrus 1") is other               # survives departure


def test_entering_the_warp_set_is_broadcast():
    seen = []
    import engine.appc.events as ev
    ws = App.WarpSequence_GetWarpSet()
    ev_type = App.ET_ENTERED_SET
    ws_ship = App.ShipClass_Create(); ws_ship.SetName("player")
    probe = type("P", (), {})()
    # Broadcast handler records every ET_ENTERED_SET destination.
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        ev_type, None, "tests.unit.test_warp_set._record")
    _record.seen = seen
    ws.AddObjectToSet(ws_ship, "player")
    assert ws_ship in seen


def _record(obj, event):
    _record.seen.append(event.GetDestination())
```

(If `AddBroadcastPythonFuncHandler`'s signature differs in `engine/appc/events.py`, match it — read it first; the assertion is what matters: `ET_ENTERED_SET` fires with the ship as destination when it enters `"warp"`.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_warp_set.py -q`
Expected: FAIL — `WarpSequence_GetWarpSet` is a stub; departure recreates `_WarpTransit`; the broadcast is suppressed.

- [ ] **Step 3: Implement** — in `engine/appc/warp.py`: `_WARP_TRANSIT_SET_NAME = "warp"` with a comment citing spec §1b and `HelmMenuHandlers.py:407`; add

```python
def WarpSequence_GetWarpSet():
    """BC's warp set: one set named "warp", created on first use and kept.
    E6M5/E7M6 load placements into it (Warp_P.LoadPlacements("warp")) and
    E6M1-E6M5 create ships there on ET_ENTERED_SET; MissionLib.
    DeleteShipsFromWarpSetExceptForMe clears it. Persistent by design (spec §1b)."""
    import App
    from engine.appc.sets import SetClass_Create
    s = App.g_kSetManager.GetSet(_WARP_TRANSIT_SET_NAME)
    if s is None:
        s = SetClass_Create()
        App.g_kSetManager.AddSet(s, _WARP_TRANSIT_SET_NAME)
    return s
```

In `_WarpDepartAction._do_play` step 2 replace the delete-and-recreate with `transit = WarpSequence_GetWarpSet()`. In `_ArriveFinalizeAction._do_play` delete the block that `DeleteSet`s the transit set (and its comment). In `App.py` export `WarpSequence_GetWarpSet` next to `WarpSequence_Create`. In `engine/appc/sets.py` remove the `_WARP_TRANSIT_SET_NAME` early-return in `_broadcast_set_transition` and its import. Update the four existing tests listed under **Files** so they assert the new behaviour (warp set exists after arrival and no longer holds the player; entering it broadcasts).

- [ ] **Step 4: Dev swap still clears it** — add to `tests/unit/test_warp_set.py`:

```python
def test_reset_sdk_globals_drops_the_warp_set():
    from engine import host_loop
    App.WarpSequence_GetWarpSet()
    host_loop.reset_sdk_globals()
    assert App.g_kSetManager.GetSet("warp") is None
```

- [ ] **Step 5: Run**

Run: `uv run pytest tests/unit/test_warp_set.py tests/unit/test_set_transition_events.py tests/unit/test_warp_spine.py tests/unit/test_warp_vfx_sequence.py tests/unit/test_warp_leaves_the_set_standing.py tests/integration/test_sky_round_trip.py tests/integration/test_target_list_follows_player_system.py tests/unit/test_tier_bc_event_emitters.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/warp.py engine/appc/sets.py App.py tests/unit/test_warp_set.py tests/unit/test_set_transition_events.py tests/unit/test_warp_spine.py tests/unit/test_warp_vfx_sequence.py tests/unit/test_warp_leaves_the_set_standing.py
git commit -m "feat(warp): the tunnel runs through BC's persistent warp set"
```

---

### Task 3: The warp button event chain

**Files:**
- Create: `engine/appc/warp_button.py`
- Modify: `engine/appc/tg_ui/st_widgets.py` (`STWarpButton`: `AddPythonFuncHandlerForInstance`, `ProcessEvent`)
- Modify: `engine/host_loop.py` (`engage_warp` ~8163 becomes a thin wrapper; `on_warp_engage` ~8768 calls `warp_button.press`; remove the "Stage 1 deliberately bypasses" comments ~8756-8764)
- Modify: `engine/ui/crew_menu_panel.py:227-233` (comment only: the callback now presses the button)
- Test: `tests/unit/test_warp_button_chain.py` (create); keep `tests/unit/test_warp_menu_side_effects.py` passing

**Interfaces:**
- Consumes: Task 1's `execute_warp` (reads mission/episode/queues off the button).
- Produces: `engine.appc.warp_button.press(button) -> None` (sends `ET_WARP_BUTTON_PRESSED`, destination and source = button); `engine.appc.warp_button.engage(button) -> None` (the engine step's body: destination guard, `warp_gate`, `announce_warp_engaged`, Helm-menu disable, `drop_menus_turn_back`, `execute_warp`); `engine.appc.warp_button.ENGINE_STEP = "engine.appc.warp_button.engine_warp_step"`; `engine.appc.warp_button.is_warp_active(player) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_warp_button_chain.py
"""ET_WARP_BUTTON_PRESSED runs the button's handler chain, newest first, and
ends in the engine step that replaces SDK WarpPressed (spec §1)."""
import sys, types
import App
from engine.appc import warp_button
from engine.appc.tg_ui.st_widgets import STWarpButton

calls = []


def _mod(name, **fns):
    m = types.ModuleType(name)
    for k, v in fns.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def setup_function(_):
    calls.clear()
    warp_button._engage_override = lambda b: calls.append(("engine", b))


def teardown_function(_):
    warp_button._engage_override = None
    for n in ("_t_old", "_t_new", "Bridge.HelmMenuHandlers"):
        sys.modules.pop(n, None)


def _button():
    b = STWarpButton("Warp")
    b.set_player_destination("Systems.Vesuvi.Vesuvi4")
    return b


def test_handlers_run_newest_first_then_the_engine_step():
    _mod("_t_old", H=lambda o, e: (calls.append("old"), o.CallNextHandler(e)))
    _mod("_t_new", H=lambda o, e: (calls.append("new"), o.CallNextHandler(e)))
    b = _button()
    b.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED, "_t_old.H")
    b.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED, "_t_new.H")
    warp_button.press(b)
    assert calls == ["new", "old", ("engine", b)]


def test_a_swallowing_handler_stops_the_warp():
    _mod("_t_new", H=lambda o, e: calls.append("refused"))
    b = _button()
    b.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED, "_t_new.H")
    warp_button.press(b)
    assert calls == ["refused"]


def test_sdk_warp_pressed_is_replaced_by_the_engine_step():
    _mod("Bridge.HelmMenuHandlers",
         WarpPressed=lambda o, e: calls.append("WarpPressed"))
    b = _button()
    b.AddPythonFuncHandlerForInstance(
        App.ET_WARP_BUTTON_PRESSED, "Bridge.HelmMenuHandlers.WarpPressed")
    warp_button.press(b)
    assert calls == [("engine", b)]


def test_the_engine_step_is_the_oldest_even_with_no_bridge():
    b = _button()
    warp_button.press(b)
    assert calls == [("engine", b)]


def test_the_event_names_the_button_as_destination():
    seen = []
    _mod("_t_new", H=lambda o, e: (seen.append(e.GetDestination()),
                                   o.CallNextHandler(e)))
    b = _button()
    b.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED, "_t_new.H")
    warp_button.press(b)
    assert seen == [b]
```

And, for the engine step itself (no override):

```python
def test_a_refused_gate_leaves_the_helm_menu_enabled(monkeypatch):
    """Review Focus 1: a refusal (by the gate or a mission) must not grey the
    Helm menu -- only a warp that actually starts does."""
    warp_button._engage_override = None
    from engine.appc import warp_gates
    from engine import bridge_officers
    disabled = []
    monkeypatch.setattr(bridge_officers, "disable_helm_menu",
                        lambda: disabled.append(1))
    monkeypatch.setattr(warp_gates, "warp_gate",
                        lambda p: warp_gates.GateResult(False, None, True, "t"))
    monkeypatch.setattr(App, "Game_GetCurrentPlayer",
                        lambda: App.ShipClass_Create())
    warp_button.press(_button())
    assert disabled == []


def test_pressing_during_an_active_warp_does_nothing(monkeypatch):
    """Review Focus 3."""
    warp_button._engage_override = None
    from engine.appc import warp as _w
    started = []
    monkeypatch.setattr(_w, "execute_warp", lambda b: started.append(b))
    monkeypatch.setattr(warp_button, "is_warp_active", lambda p: True)
    monkeypatch.setattr(App, "Game_GetCurrentPlayer",
                        lambda: App.ShipClass_Create())
    warp_button.press(_button())
    assert started == []
```

(`GateResult`'s constructor is `GateResult(allowed, deny_line=None, silent=False, reason=None)`, `engine/appc/warp_gates.py:34-43` — confirm before relying on positional order.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_warp_button_chain.py -q`
Expected: FAIL — `engine.appc.warp_button` does not exist.

- [ ] **Step 3: Create `engine/appc/warp_button.py`**

```python
"""BC's warp button event (spec §1).

In BC a click on the Helm "Warp" button sends ET_WARP_BUTTON_PRESSED to the
button; its instance handlers run newest-first (engine/appc/events.py), the
missions' first and HelmMenuHandlers.WarpPressed last, and a handler that does
not CallNextHandler stops the warp. The warp itself was then built in C++
(inferred: nothing in the SDK builds it). Here the engine step takes
WarpPressed's place at the bottom of the chain: it runs our port of
WarpPressed's checks (warp_gates) and builds the warp from the whole button.
WarpPressed itself is not run -- its pre-warp camera cutscene would fight the
flythrough (spec §1, out of scope).
"""
import App

ENGINE_STEP = "engine.appc.warp_button.engine_warp_step"
_WARP_PRESSED_SUFFIX = "HelmMenuHandlers.WarpPressed"

# Tests replace the engine step's body; production leaves this None.
_engage_override = None


def is_warp_replaced(qualified_name) -> bool:
    return str(qualified_name).endswith(_WARP_PRESSED_SUFFIX)


def ensure_engine_step(button) -> None:
    """Make the engine step the OLDEST handler (index 0 == runs last)."""
    et = App.ET_WARP_BUTTON_PRESSED
    chain = button._handlers.setdefault(et, [])
    if ENGINE_STEP in chain:
        chain.remove(ENGINE_STEP)
    chain.insert(0, ENGINE_STEP)


def press(button) -> None:
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_WARP_BUTTON_PRESSED)
    evt.SetSource(button)
    evt.SetDestination(button)
    App.g_kEventManager.AddEvent(evt)


def engine_warp_step(button, event) -> None:
    if _engage_override is not None:
        _engage_override(button)
        return
    engage(button)


def is_warp_active(player) -> bool:
    eng = player.GetWarpEngineSubsystem() if hasattr(
        player, "GetWarpEngineSubsystem") else None
    return bool(eng is not None and eng.GetWarpSequence() is not None)


def engage(button) -> None:
    """The body of host_loop.engage_warp, moved here so the engine step and
    headless tests share it. See that function's history for why each guard
    exists (destination guard: a course-less click greyed the Helm menu for
    good)."""
    from engine import dev_mode
    from engine.appc import warp as _w
    from engine.appc import warp_gates as _wg
    if not button or not button.GetDestination():
        if dev_mode.is_enabled():
            print("[warp] ignored: no course set", flush=True)
        return
    player = App.Game_GetCurrentPlayer()
    if player is None and _w._player_hook is not None:
        player = _w._player_hook()
    if player is None or is_warp_active(player):
        return
    result = _wg.warp_gate(player)
    if not result.allowed:
        if dev_mode.is_enabled():
            print("[warp] gated: %s (line=%s)" % (
                result.reason or "unknown", result.deny_line or "-"), flush=True)
        if result.deny_line is not None:
            _wg.speak_deny(player, result.deny_line)
        return
    try:
        from engine.bridge_officers import announce_warp_engaged
        announce_warp_engaged()
    except Exception as _e:
        dev_mode.log_swallowed("announce warp engaged", _e)
    try:
        from engine import bridge_officers
        from engine.appc.top_window import drop_menus_turn_back
        bridge_officers.disable_helm_menu()
        drop_menus_turn_back()
    except Exception as _e:
        dev_mode.log_swallowed("warp menu side effects", _e)
    _w.execute_warp(button)
```

Carry `engage_warp`'s existing explanatory comments (announce/HelmMenuHandlers line refs, menu side effects) across verbatim into `engage`.

- [ ] **Step 4: Wire the button and the host**

In `STWarpButton`:

```python
    def AddPythonFuncHandlerForInstance(self, event_type, qualified_name):
        import App
        from engine.appc import warp_button
        # SDK WarpPressed is replaced by the engine step (spec §1).
        if (event_type == App.ET_WARP_BUTTON_PRESSED
                and warp_button.is_warp_replaced(qualified_name)):
            return
        super().AddPythonFuncHandlerForInstance(event_type, qualified_name)

    def ProcessEvent(self, event):
        import App
        from engine.appc import warp_button
        if event.GetEventType() == App.ET_WARP_BUTTON_PRESSED:
            warp_button.ensure_engine_step(self)
        super().ProcessEvent(event)
```

In `engine/host_loop.py`: `engage_warp(button, controller)` keeps its signature (tests call it) and becomes a docstring plus `from engine.appc import warp_button; warp_button.engage(button)` (the `controller.session.player` fallback is already covered by `warp._player_hook`; confirm `_player_hook` is configured in `run()` and say so in the docstring). `on_warp_engage(button)` becomes `warp_button.press(button)`. Replace the "Stage 1 deliberately bypasses …" comment blocks (host_loop ~8756-8764 and `crew_menu_panel.py:227-233`) with one line each pointing at `engine/appc/warp_button.py`.

- [ ] **Step 5: Run**

Run: `uv run pytest tests/unit/test_warp_button_chain.py tests/unit/test_warp_menu_side_effects.py tests/unit/test_crew_menu_panel.py tests/unit/test_warp_gates.py -q`
Expected: PASS (if `test_warp_gates.py` does not exist, run `uv run pytest tests -q -k "warp_gate or warp_menu"` instead).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/warp_button.py engine/appc/tg_ui/st_widgets.py engine/host_loop.py engine/ui/crew_menu_panel.py tests/unit/test_warp_button_chain.py
git commit -m "feat(warp): Warp sends ET_WARP_BUTTON_PRESSED; the engine step replaces WarpPressed"
```

---

### Task 4: Set Course carries mission and episode

**Files:**
- Modify: `engine/appc/warp.py` (`set_course_placement` ~841, `placement_name_for_destination` ~856 — generalise the walk)
- Modify: `engine/appc/tg_ui/st_widgets.py` (`STWarpButton.set_player_destination` also clears mission/episode)
- Test: `tests/unit/test_set_course_mission_names.py` (create)

**Interfaces:**
- Produces: `warp.region_menu_for_destination(dest_module, course_menu) -> SortedRegionMenu | None`; `set_course_placement(button, dest_module)` now also sets the button's mission and episode names from that menu (clearing them when absent).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_set_course_mission_names.py
"""A Set Course pick carries the region menu's mission/episode onto the warp
button (67 SDK SetMissionName/SetEpisodeName sites); a new pick clears stale
names (Review Focus 4)."""
from engine.appc import warp
from engine.appc.tg_ui.st_widgets import STWarpButton, SortedRegionMenu
from engine.appc.characters import STMenu


def _course_menu():
    root = STMenu("Set Course")
    beol = SortedRegionMenu("Beol", "Systems.Beol.Beol4")
    beol.SetMissionName("Maelstrom.Episode6.E6M2.E6M2")
    sb = SortedRegionMenu("Starbase 12", "Systems.Starbase12.Starbase12")
    sb.SetEpisodeName("Maelstrom.Episode6.Episode6")
    plain = SortedRegionMenu("Vesuvi", "Systems.Vesuvi.Vesuvi4")
    for m in (beol, sb, plain):
        root.AddChild(m)
    return root


def test_mission_name_reaches_the_button(monkeypatch):
    monkeypatch.setattr(warp, "find_set_course_menu", _course_menu)
    b = STWarpButton("Warp")
    b.set_player_destination("Systems.Beol.Beol4")
    warp.set_course_placement(b, "Systems.Beol.Beol4")
    assert b.get_mission_name() == "Maelstrom.Episode6.E6M2.E6M2"
    assert b.get_episode_name() == ""


def test_episode_name_reaches_the_button(monkeypatch):
    monkeypatch.setattr(warp, "find_set_course_menu", _course_menu)
    b = STWarpButton("Warp")
    b.set_player_destination("Systems.Starbase12.Starbase12")
    warp.set_course_placement(b, "Systems.Starbase12.Starbase12")
    assert b.get_episode_name() == "Maelstrom.Episode6.Episode6"


def test_a_plain_pick_clears_stale_names(monkeypatch):
    monkeypatch.setattr(warp, "find_set_course_menu", _course_menu)
    b = STWarpButton("Warp")
    b.SetDestination("Systems.Starbase12.Starbase12",
                     "Maelstrom.Episode7.E7M1.E7M1", "Player Start",
                     "Maelstrom.Episode7.Episode7")
    b.set_player_destination("Systems.Vesuvi.Vesuvi4")
    warp.set_course_placement(b, "Systems.Vesuvi.Vesuvi4")
    assert b.get_mission_name() == "" and b.get_episode_name() == ""
```

(Check `STMenu`'s import path and `SortedRegionMenu(label, region)` constructor against `engine/appc/tg_ui/st_widgets.py` / `engine/appc/characters.py` before running.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_set_course_mission_names.py -q`
Expected: FAIL — names never reach the button; stale names survive.

- [ ] **Step 3: Implement** — refactor `placement_name_for_destination`'s `_walk` into `region_menu_for_destination(dest_module, course_menu)` returning the matching `SortedRegionMenu` (same recursion, same `__dict__` read and its comment); `placement_name_for_destination` becomes `m = region_menu_for_destination(...); return m.GetPlacementName() if m else DEFAULT_ARRIVAL_PLACEMENT`. `set_course_placement` becomes:

```python
    menu = region_menu_for_destination(dest_module, find_set_course_menu())
    button.SetPlacementName(menu.GetPlacementName() if menu
                            else DEFAULT_ARRIVAL_PLACEMENT)
    # BC's "warping here starts mission X" (SortedRegionMenu.SetMissionName /
    # SetEpisodeName, 67 SDK sites). Always assigned, like the placement, so a
    # plain course never inherits a previous one's mission (spec §1).
    button.set_course_mission(menu.GetMissionName() if menu else "",
                              menu.GetEpisodeName() if menu else "")
```

and add to `STWarpButton` (engine-only, snake_case):

```python
    def set_course_mission(self, mission_name, episode_name) -> None:
        self._mission_name = str(mission_name or "")
        self._episode_name = str(episode_name or "")
```

`set_player_destination` also resets `_mission_name`/`_episode_name` to `""` (a player pick never inherits a mission's `SetDestination` names; `set_course_placement` then applies the menu's).

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_set_course_mission_names.py tests/unit/test_warp_placement_name.py tests/unit/test_st_widgets_region.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/warp.py engine/appc/tg_ui/st_widgets.py tests/unit/test_set_course_mission_names.py
git commit -m "feat(warp): Set Course carries the region menu's mission and episode"
```

---

### Task 5: Queued actions play in the tunnel; transit holds for them

**Files:**
- Modify: `engine/appc/warp.py` (`WarpSequence_Create` flythrough branch ~740-797 and fallback branch ~801-809; new `_HoldUntilAction`, `_TransitReleaseAction`)
- Modify: `engine/warp_vfx.py` (`WarpVFX`: `hold()`, `release(now)`)
- Test: `tests/unit/test_warp_queued_actions.py` (create); `tests/unit/test_warp_vfx.py` (add hold/release tests — if the file name differs, add to the existing WarpVFX unit test file)

**Interfaces:**
- Consumes: Task 1's `WarpSequence._queues`.
- Produces: in the flythrough sequence, the order **depart → `WarpSequence.WaitForQueued` (SDK script action, player only) → before-during → during → after-during → `_MissionChangePoint` (Task 7 fills it; here a no-op action named `_MissionChangePoint`) → `_HoldUntilAction(deadline = sequence start + t_align + t_transit)` → `_TransitReleaseAction` → swap → place → …**; "before" queue as roots at their delays; "after" queue appended after `_EnableHelmMenuAction` at their delays. `WarpVFX.hold()` freezes transit progress at the plateau (streak 1, flash 0) while held; `WarpVFX.release(now)` resumes with the final 10 % of transit (the exit flash) still to play.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_warp_queued_actions.py
"""The button's queues play at their points of the tunnel; the swap waits for
them and for the mission's master dialogue sequence (SDK WaitForQueued)."""
import App
from engine.appc import warp
from engine.appc.actions import TGAction

log = []


class _Rec(TGAction):
    def __init__(self, tag):
        super().__init__(); self.tag = tag
    def _do_play(self):
        log.append(self.tag)


def _queues(**kw):
    q = {k: [] for k in ("before", "before_during", "during", "after_during", "after")}
    for k, tags in kw.items():
        q[k] = [(_Rec(t), 0.0) for t in tags]
    return q


def test_queues_play_in_bc_order_around_the_swap(monkeypatch):
    log.clear()
    order = []
    monkeypatch.setattr(warp, "ChangeRenderedSetAction_Create",
                        lambda m: _Rec("SWAP"))
    ship = App.ShipClass_Create(); ship.SetName("player")
    seq = warp.WarpSequence_Create(
        ship, "Systems.Vesuvi.Vesuvi4", 0.0, "Player Start",
        queues=_queues(before=["B"], before_during=["BD"], during=["D"],
                       after_during=["AD"], after=["A"]))
    tags = [type(s.action).__name__ if not isinstance(s.action, _Rec)
            else s.action.tag for s in seq._steps]
    # Structural: the swap is reachable only through the queue chain.
    i = tags.index
    assert i("B") < i("BD") < i("D") < i("AD") < i("SWAP") < i("A")
```

Plus a behavioural test driven through the timer manager (read `tests/unit/test_warp_vfx_sequence.py` for how existing tests advance game time through a flythrough sequence — reuse its helper):

```python
def test_transit_holds_until_a_long_during_action_completes(...):
    """A during-warp action that runs past t_transit delays the swap until it
    completes; the player is still in the "warp" set until then."""
```

Write that test with the helper you found: a `_Rec` subclass whose `Play` does not call `Completed()` until the test calls it; advance game time past `t_align + t_transit`; assert the player is still in `"warp"`; call `Completed()`; advance one tick; assert the player is in the destination set.

And for the hold on the master dialogue sequence:

```python
def test_transit_waits_for_the_mission_master_sequence(...):
    """SDK WarpSequence.WaitForQueued (player only): while
    MissionLib.g_idMasterSequenceObj names a playing TGSequence, the swap waits
    for its completion."""
```

(set `MissionLib.g_idMasterSequenceObj` to a playing `TGSequence`'s `GetObjID()`; same advance-then-complete shape.)

WarpVFX:

```python
def test_vfx_hold_freezes_the_transit_plateau_and_release_plays_the_exit():
    from engine.warp_vfx import WarpVFX
    w = WarpVFX()
    w.start((0.0, 1.0, 0.0), 1.0, 8.0, 0.0)
    w.tick(3.0)
    w.hold()
    w.tick(100.0)
    assert w.phase() == "transit" and w.streak_intensity() == 1.0
    assert w.flash_intensity() == 0.0
    w.release(100.0)
    w.tick(100.0 + 0.8 * 0.5)       # inside the final 10 % of transit
    assert w.phase() == "transit" and w.flash_intensity() > 0.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_warp_queued_actions.py -q` and the WarpVFX file.
Expected: FAIL.

- [ ] **Step 3: Implement**

- `WarpVFX.hold()`: set `self._held = True` and remember the elapsed value at the plateau (clamp `e` to `t_align + 0.5 * t_transit` while held). `release(now)`: `self._held = False`; set `self._t0 = now - (self._t_align + 0.9 * self._t_transit)` so the next `tick` resumes in the final 10 % (the exit flash). `tick` honours `_held` by clamping `e`.
- `_HoldUntilAction(TGAction)`: constructed with the sequence; on `Play`, compute `remaining = seq._t_start + t_align + t_transit - App.g_kUtopiaModule.GetGameTime()`; if `remaining <= 0` complete immediately, else schedule completion after `remaining` game seconds (use the same game-time timer mechanism `TGSequence` uses for step delays — read `TGSequence._schedule_timer`; do not use the realtime manager). Record `seq._t_start` in `WarpSequence.Play()`.
- `_TransitReleaseAction`: `warp_vfx.get().release(GetGameTime())` (fail-open try/except like `_WarpVfxBeginAction`).
- `_WarpDepartAction` calls `warp_vfx.get().hold()` after parking the player (fail-open).
- Build the chain in the flythrough branch: after `seq.AddAction(_WarpDepartAction(source, ship), t_align)`, `prev = depart`; if the ship is the current player append `App.TGScriptAction_Create("WarpSequence", "WaitForQueued")` depending on `prev`; then each `before_during`, `during`, `after_during` action in order (each depends on the previous; delays from the queue); then `_MissionChangePoint(seq)` (a TGAction subclass whose `_do_play` is empty in this task), then `_HoldUntilAction`, `_TransitReleaseAction`, then the existing `swap` **chained** (replace `seq.AddAction(swap, total)` with a dependency on the release action). "before" actions: `seq.AddAction(a, delay)` as roots. "after" actions: `seq.AppendAction(a, delay)` after `_EnableHelmMenuAction`.
- Fallback branch (no flythrough): same order without VFX/hold: before (roots) → before_during → during → after_during → `_MissionChangePoint` → swap → place → … → after.
- `WaitForQueued` is the SDK's own function (`WarpSequence.py:557-600`) — do not reimplement it. If the SDK's `ET_OKAY` / `TGObjPtrEvent` / `g_kTGActionManager` completion path it relies on is missing, implement that surface (check `docs/stub_heatmap.md` first) rather than bypassing the SDK function.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_warp_queued_actions.py tests/unit/test_warp_vfx_sequence.py tests/unit/test_warp_spine.py tests/unit/test_warp_leaves_the_set_standing.py tests/integration/test_sky_round_trip.py -q` plus the WarpVFX test file.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/warp.py engine/warp_vfx.py tests/unit/test_warp_queued_actions.py <the WarpVFX test file>
git commit -m "feat(warp): queued actions play in the tunnel, which holds for them"
```

---

### Task 6: Mission change with carry-over

**Files:**
- Create: `engine/core/mission_change.py`
- Modify: `engine/core/game.py` (`Mission`/`Episode` record their module name; `Episode.LoadMission` and `Game.LoadEpisode` set it; add `_load_mission_raw` / `_load_episode_raw` holding today's bodies)
- Modify: `engine/host_loop.py` (`_init_mission` sets `mission._module_name` and `episode._module_name = mission_change.episode_module_for(name)`)
- Modify: `docs/superpowers/specs/2026-09-25-warp-button-chain-and-mission-warps-design.md` (append the keep/reset table under §2)
- Test: `tests/unit/test_mission_change.py` (create)

**Interfaces:**
- Produces: `mission_change.change(*, mission=None, episode=None) -> bool` (True if a change ran); `mission_change.episode_module_for(mission_module: str) -> str | None` (`"Maelstrom.Episode7.E7M1.E7M1"` → `"Maelstrom.Episode7.Episode7"`; None for anything not `<Family>.<EpisodeN>.<M>.<M>`); `mission_change.in_progress() -> bool`; `mission_change.configure(on_changed=None)` (host callback, called with no args after a successful change); `Mission._module_name: str`, `Episode._module_name: str`.

**Behaviour** (spec §2):

1. If `in_progress()`: return False. If neither name differs from the current (`episode` differs from `game.GetCurrentEpisode()._module_name`, or `mission` differs from the current mission's `_module_name`): return False.
2. Set the in-progress flag (cleared in `finally`).
3. **Terminate:** `sys.modules[cur_mission._module_name].Terminate(cur_mission)` if the module and function exist; if the episode changes, the same for the episode module with the `Episode`. Each call wrapped: an exception is printed with traceback and the change continues.
4. **Clear** (`_clear_for_next_mission(keep_names)`): `keep_names = {"warp", <player's containing set name>, <every set whose class is BridgeSet or whose name is "bridge">}`. For every other set: call `warp._teardown_hook(pSet)` if set (drops render instances), then `App.g_kSetManager.DeleteSet(name)`. Then apply the **reset** column of the keep/reset table below. Never touch the **keep** column.
5. **Load:** episode change → `game._load_episode_raw(episode)` (its `Initialize` calls `LoadMission`, which must also go raw — `Episode.LoadMission` routes only when `not in_progress()`); mission only → `episode._load_mission_raw(mission, start_event)` with a fresh `ET_MISSION_START` `TGEvent` (as `_init_mission` builds it).
6. On an exception from step 5: print it with traceback, leave the player where it is, return False (Review Focus 2). Otherwise call `on_changed()` if configured and return True.

**Keep / reset table** (derived from `reset_sdk_globals` and `_drain_pending_swap`; append it to the spec as written here, adjusting only where reading the code proves a row wrong — and say which in the commit message):

| Item | Carry-over change | Why |
|---|---|---|
| `Game`, player ship object, its subsystems/damage/AI-free state | **keep** | BC reuses the player (`MissionLib.CreatePlayerShip` reuse branch) |
| Bridge set(s) and bridge characters | **keep** | "specifically ignored from mission to mission" (`Maelstrom.py:258-262`) |
| `"warp"` set | **keep** | the player is in it |
| Every other set | **reset** (teardown hook + `DeleteSet`) | BC's unload deletes them |
| Game/realtime timer managers | **reset except** timers whose owning action is the playing `WarpSequence` or one of its steps | the warp must finish; everything else is the old mission's |
| Game clock (`_time`) | **keep** | the warp's hold deadline and every surviving timer are on it |
| `_appc_actions` deferred-playing registry | **reset except** survivors (same rule) | as timers |
| Event manager broadcast/method handlers | **reset**, then `register_input_handlers` | the old mission's conditions must not fire |
| `crew_speech` bus | **reset** | as swap |
| `contact_index` | **reset** | keyed on deleted sets |
| `ObjectGroup._live` | **reset** | as swap |
| Tooltip throttle/owner | **reset** | as swap |
| Projectile module cache | **keep** | same SDK tree |
| `MissionLib.ResetViewscreen()`, `g_idMasterSequenceObj = NULL_ID` | **reset** | the queued dialogue finished before the change point |
| `system_loader.reset()`, `_mapped_body_warned` | **reset** | new mission, new systems |
| Waypoint registry | **reset** entries whose set was deleted | names repeat across sets |
| `App._next_event_type_id` | **keep** | kept objects may hold allocated types |
| Target menu singleton, TCW singleton, `st_widgets._reset_module_state`, ShipDisplay slots, TacticalInterfaceHandlers/manual_aim/crew hotkeys re-wire | **reset** (same code path as `reset_sdk_globals`) | the next mission's `LoadBridge.Load` rebuilds menus per load |
| `top_window` shim | **keep** | the warp's cinematic/control state is live |
| Nebula trackers, concealment latches, `_last_identify_gt` | **reset** | as swap |
| `g_kTGActionManager._registered` | **reset except** survivors | as timers |
| dev tutorial flag | **re-apply** | as swap |
| Render origin | **keep** | the camera is mid-flight |
| Per-ship engine modules (`ship_lifecycle`, `ship_death`, `visible_damage`, `registry_texture`, `hit_feedback` throttles, …) | **keep** | keyed per ship; the player's entries must survive; deleted ships' entries go with `DeleteSet` |

Factor the shared resets out of `reset_sdk_globals` into small named helpers in `host_loop.py` (e.g. `_reset_event_handlers()`, `_reset_tactical_window()`), called by both `reset_sdk_globals` and the carry-over path, so the two lists cannot drift. Import them into `mission_change` lazily inside the function (host_loop imports engine.core; the reverse import must stay lazy).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_mission_change.py
"""Mission change with carry-over (spec §2)."""
import sys, types
import App
from engine.core import mission_change
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.appc.sets import SetClass_Create

log = []


def _install(name, **fns):
    m = types.ModuleType(name)
    for k, v in fns.items():
        setattr(m, k, v)
    sys.modules[name] = m


def _world():
    App.g_kSetManager._sets.clear()
    log.clear()
    game = Game(); ep = Episode(); mis = Mission()
    ep.SetCurrentMission(mis); game.SetCurrentEpisode(ep); _set_current_game(game)
    mis._module_name = "_t.Old"; ep._module_name = "_t.EpOld"
    ws = App.WarpSequence_GetWarpSet()
    player = App.ShipClass_Create(); player.SetName("player")
    ws.AddObjectToSet(player, "player"); game.SetPlayer(player)
    bridge = SetClass_Create(); App.g_kSetManager.AddSet(bridge, "bridge")
    old = SetClass_Create(); App.g_kSetManager.AddSet(old, "Beol4")
    return game, player, bridge


def teardown_function(_):
    for n in ("_t.Old", "_t.New", "_t.EpOld", "_t.EpNew"):
        sys.modules.pop(n, None)
    _set_current_game(None)


def test_episode_module_for():
    f = mission_change.episode_module_for
    assert f("Maelstrom.Episode7.E7M1.E7M1") == "Maelstrom.Episode7.Episode7"
    assert f("QuickBattle.QuickBattle") is None


def test_change_terminates_clears_and_loads_carrying_the_player():
    game, player, bridge = _world()
    _install("_t.Old", Terminate=lambda m: log.append("Old.Terminate"))
    def _init(m):
        log.append("New.Initialize")
        s = SetClass_Create(); App.g_kSetManager.AddSet(s, "Starbase12")
    _install("_t.New", Initialize=_init)
    assert mission_change.change(mission="_t.New") is True
    assert log == ["Old.Terminate", "New.Initialize"]
    assert App.g_kSetManager.GetSet("Beol4") is None
    assert App.g_kSetManager.GetSet("bridge") is bridge
    assert App.g_kSetManager.GetSet("warp").GetObject("player") is player
    assert App.Game_GetCurrentGame() is game and game.GetPlayer() is player
    assert App.g_kSetManager.GetSet("Starbase12") is not None
    cur = game.GetCurrentEpisode().GetCurrentMission()
    assert cur._module_name == "_t.New"


def test_same_mission_is_not_a_change():
    _world()
    assert mission_change.change(mission="_t.Old") is False


def test_a_failing_next_mission_leaves_the_player_parked():
    """Review Focus 2."""
    game, player, _ = _world()
    _install("_t.Old", Terminate=lambda m: None)
    def _boom(m): raise RuntimeError("bad mission")
    _install("_t.New", Initialize=_boom)
    assert mission_change.change(mission="_t.New") is False
    assert App.g_kSetManager.GetSet("warp").GetObject("player") is player
    assert not mission_change.in_progress()


def test_a_change_inside_a_change_is_refused():
    _world()
    _install("_t.Old", Terminate=lambda m: None)
    def _init(m):
        log.append(mission_change.change(mission="_t.Other"))
    _install("_t.New", Initialize=_init)
    mission_change.change(mission="_t.New")
    assert log == [False]
```

Add one test per **keep** row that is not already covered above and is cheap to observe headlessly: a timer owned by a playing `WarpSequence` survives while an unrelated timer does not; the game clock is unchanged; a broadcast handler registered by the old mission is gone and the input handlers are registered.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_mission_change.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** `engine/core/mission_change.py` per **Behaviour** and the table; the `game.py` changes (`_module_name` fields default `""`; `LoadMission` → `_load_mission_raw` holds today's body and sets `mission._module_name = name`; `LoadEpisode` → `_load_episode_raw` holds today's body and sets `episode._module_name = name`; the public methods call the raw ones for now — Task 7 adds routing); `_init_mission`'s two `_module_name` assignments; the shared reset helpers in `host_loop.py`. Append the table to the spec.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_mission_change.py tests/unit -q -k "mission or reset or swap or game" ` then `uv run pytest tests/host -q -k "swap or mission"`.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/core/mission_change.py engine/core/game.py engine/host_loop.py docs/superpowers/specs/2026-09-25-warp-button-chain-and-mission-warps-design.md tests/unit/test_mission_change.py
git commit -m "feat(missions): mission change with carry-over of ship, bridge and warp set"
```

---

### Task 7: The warp changes mission; direct loads route through the change

**Files:**
- Modify: `engine/appc/warp.py` (`_MissionChangePoint._do_play`)
- Modify: `engine/core/game.py` (`Game.LoadEpisode`, `Episode.LoadMission` routing)
- Modify: `engine/host_loop.py` (`run()`: `mission_change.configure(on_changed=...)` updating `controller.session.mission_name` — read `MissionSession` for the field name — and `controller.panel_registry.invalidate_all()`)
- Test: `tests/unit/test_warp_mission_change.py` (create)

**Interfaces:**
- Consumes: Task 5's `_MissionChangePoint(seq)`; Task 6's `mission_change.change`.
- Produces: `_MissionChangePoint` calls `mission_change.change(mission=seq.GetDestinationMission(), episode=seq.GetDestinationEpisode())` when either is set; `Game.LoadEpisode(name)` → `mission_change.change(episode=name)` when a mission is running (`self.GetCurrentEpisode()` has a current mission with a non-empty `_module_name`) and no change is in progress, else raw; `Episode.LoadMission(name, ev)` likewise with `mission=name`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_warp_mission_change.py
"""The change runs at the after-during point of the tunnel; direct loads route
through it; a load that names the episode already current is a no-op (E5M4:
MissionWin -> LoadEpisode(Episode6), then the warp names Episode6 too)."""
```

Cover, reusing Task 6's `_world()` / `_install` helpers (move them to `tests/helpers/mission_change_fixtures.py` so both files import them):

1. A warp built with `mission="_t.New"` and a during-queue action: log order is during-action → `_t.Old` Terminate → `_t.New` Initialize → the player placed in the new mission's destination set.
2. `Game.LoadEpisode("_t.EpNew")` while `_t.Old` runs: `_t.Old.Terminate` ran, `_t.EpNew.Initialize` ran exactly once, `Beol4` gone.
3. `Game.LoadEpisode` with no mission running (boot): raw load, no Terminate.
4. Double load: a before-during action calls `Game.LoadEpisode("_t.EpNew")`; the warp also names `episode="_t.EpNew"`; `_t.EpNew.Initialize` ran exactly once.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_warp_mission_change.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement** the three routing points and the host callback (the host's `on_changed` must also `director.snap()` and `_xform_buf.reset_all()` the way `had_pending_swap` does — read that block ~9796-9827 and reuse it through a small function rather than duplicating it).

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_warp_mission_change.py tests/unit/test_mission_change.py tests/unit/test_warp_queued_actions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/warp.py engine/core/game.py engine/host_loop.py tests/unit/test_warp_mission_change.py tests/unit/test_mission_change.py tests/helpers/mission_change_fixtures.py
git commit -m "feat(missions): the warp changes mission in transit; direct loads route through it"
```

---

### Task 8: Campaign transitions end to end, the handler sweep, docs

**Files:**
- Test: `tests/integration/test_campaign_warp_transitions.py` (create)
- Test: `tests/integration/test_warp_button_handler_sweep.py` (create)
- Modify: `CLAUDE.md` (one row in the reference table: the warp button chain + mission change, pointing at the spec and `engine/appc/warp_button.py`, `engine/core/mission_change.py`)
- Modify: `docs/stub_heatmap.md` only if `tools/stub_heatmap.py` regenerates it as part of the gate — otherwise leave it

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the end-to-end tests** — load real missions headlessly through `engine.host_loop._init_mission(name)` (it builds Game/Episode/Mission and runs `Initialize`; read `tests/integration/test_dev_mission_arrival.py` for the established way to call it headless and to tick `engine.core.loop.GameLoop`). For each case: make the player's ship identifiable (`id(player)`), apply one visible damage marker (`player.GetHull().SetCondition(...)` — read `engine/appc/subsystems.py` for the setter), set the mission's own preconditions through its module globals, set the course with `record_course_selection`-equivalent calls (`btn.set_player_destination(dest)` + `warp.set_course_placement(btn, dest)`), `warp_button.press(btn)`, then tick until the warp sequence detaches (bounded: 120 s of game time).

| Case | Start | Preconditions | Course | Expect |
|---|---|---|---|---|
| E6M5 → Episode 7 | `Maelstrom.Episode6.E6M5.E6M5` | player not in Tezle1 (or both `g_bShuttlesInBeol`/`g_bStrikeForceInTezle1` FALSE) | `Systems.Beol.Beol4` | current mission `_module_name == "Maelstrom.Episode7.E7M1.E7M1"`; player in `Starbase12` at `"Player Start"`; same `id`; hull condition kept |
| E7M6 → Episode 8 | `Maelstrom.Episode7.E7M6.E7M6` | `g_bDataRescued = TRUE`, player not in Alioth6 | `Systems.Starbase12.Starbase12` | mission `E8M1`; same ship |
| E6M1 → E6M2 | `Maelstrom.Episode6.E6M1.E6M1` | whatever makes `E6M1.py:3694`'s `SetMissionName` run (read it) | the menu's region | mission `E6M2` |
| E2M6 → Episode 3 (direct) | `Maelstrom.Episode2.E2M6.E2M6` | — | none: call `E2M6.StartEpisode3(None)` directly with `g_bMissionTerminate` false | episode `Maelstrom.Episode3.Episode3`, its first mission `E3M1`; E2M6's `Terminate` ran; no set from E2M6 survives but `bridge`/`warp` |
| E6M1 in-tunnel ships | `Maelstrom.Episode6.E6M1.E6M1` | the destination `PlayerEntersWarpSet` expects (read `E6M1.py`) | that destination | the Artrus ships exist when `GiveArtrusShipsAI` runs; no exception |

If a case cannot be driven headlessly without editing SDK files, mark only that case `pytest.mark.xfail(strict=True, reason=...)` naming the precise blocker, and report it — do not weaken the other cases.

- [ ] **Step 2: Write the sweep**

```python
# tests/integration/test_warp_button_handler_sweep.py
"""Every campaign mission loads, Warp is pressed headlessly with a plotted
course and with none, and nothing raises (spec: Testing, Sweep)."""
import pytest
from tools import mission_harness

MISSIONS = [m for m in mission_harness.discover_missions()
            if m.startswith("Maelstrom.")]


@pytest.mark.parametrize("name", MISSIONS)
def test_pressing_warp_never_raises(name):
    ...  # _init_mission(name); press once with the button's own destination,
         # once after set_player_destination(None); tick 5 s; assert no
         # exception escaped (the events.py dispatch re-raises handler errors).
```

Fill the body with the same `_init_mission` + tick helper as Step 1 (put it in `tests/helpers/headless_mission.py` and use it from both files).

- [ ] **Step 3: Run**

Run: `uv run pytest tests/integration/test_campaign_warp_transitions.py tests/integration/test_warp_button_handler_sweep.py -q`
Expected: PASS (strict xfails reported by name).

- [ ] **Step 4: Gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures.`

- [ ] **Step 5: Docs and commit** — add the CLAUDE.md row (one line in the reference table: what it is, the two modules, the spec, "⚠️ not live-verified"). Commit:

```bash
git add tests/integration/test_campaign_warp_transitions.py tests/integration/test_warp_button_handler_sweep.py tests/helpers/headless_mission.py CLAUDE.md
git commit -m "test(warp): campaign transitions end to end and the warp-button handler sweep"
```

---

## Live pass (Mark, after the plan completes)

`--developer` → Load Mission:
1. **E6M5:** finish it (or reach the point where the Beol course is open), Set Course → Beol, Warp. Expect: Saffi's log / Liu's briefing plays in transit, you arrive at Starbase 12 in **Episode 7 / E7M1**, same ship.
2. **E1M2 → Episode 2:** finish E1M2, take the course its menu marks, Warp. Expect Episode 2 begins, same ship.
3. **A refusal:** E1M1's tutorial before it allows warp. Expect the refusal line and no warp; Helm menu still usable.
