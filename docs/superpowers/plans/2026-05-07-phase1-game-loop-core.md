# Phase 1 Game Loop Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the timer/event/game-hierarchy core of the headless engine so that `MissionLib.CreateTimer(...)` can be called and its callback fires when the timer manager is ticked.

**Architecture:** `App.py` at the project root acts as the module game scripts `import App` — it exposes all BC API surface, with a `__getattr__` fallback for the large renderer/audio surface we aren't implementing yet. Real logic lives in `engine/core/` (IDs, game hierarchy) and `engine/appc/` (events, timers). The test suite puts the project root first in `sys.path` so our `App.py` shadows the SDK's, and adds `sdk/Build/scripts/` for importing real SDK scripts like `MissionLib`.

**Tech Stack:** Python 3.11+, pytest, stdlib only (no external deps for this milestone)

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `App.py` | CREATE (project root) | Top-level module game scripts import; exports all BC API; `__getattr__` fallback for unimplemented surface |
| `engine/core/__init__.py` | CREATE | empty |
| `engine/core/ids.py` | CREATE | `TGObject` base class with `GetObjID()`; process-global ID registry |
| `engine/core/game.py` | CREATE | `Game`, `Episode`, `Mission` classes; `Game_GetCurrentGame()` and `_set_current_game()` |
| `engine/appc/events.py` | MODIFY (currently stub comment) | `TGEvent`, `TGEvent_Create()`; `TGEventHandlerObject` with handler dispatch; `TGEventManager` |
| `engine/appc/timers.py` | MODIFY (currently stub comment) | `TGTimer`, `TGTimer_Create()`; `TGTimerManager` with `tick(delta)` |
| `pyproject.toml` | MODIFY | Add pytest as dev dependency |
| `tests/conftest.py` | CREATE | `sys.path` setup; stub modules for SDK imports we can't satisfy |
| `tests/unit/test_ids.py` | CREATE | TGObject ID uniqueness tests |
| `tests/unit/test_game.py` | CREATE | Game/Episode/Mission hierarchy tests |
| `tests/unit/test_events.py` | MODIFY (empty) | TGEvent and TGEventHandlerObject dispatch tests |
| `tests/unit/test_timers.py` | CREATE | TGTimer one-shot and repeat tests; TGTimerManager tick tests |
| `tests/integration/__init__.py` | CREATE | empty |
| `tests/integration/test_missionlib_timer.py` | CREATE | Import MissionLib, call CreateTimer, tick, assert callback fired |

---

## Task 1: Add pytest dev dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dev dependency**

Edit `pyproject.toml` to add:

```toml
[project]
name = "open-stbc"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.hatch.build.targets.wheel]
packages = ["engine"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Install dev deps**

```bash
uv sync --extra dev
```

Expected: resolves and installs pytest.

- [ ] **Step 3: Verify pytest runs**

```bash
uv run pytest tests/ -q
```

Expected: `no tests ran` or existing empty test files pass with 0 failures.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add pytest dev dependency"
```

---

## Task 2: Test infrastructure — conftest.py and sys.path

**Files:**
- Create: `tests/conftest.py`

The test suite needs two things on `sys.path`:
1. The project root — so `import App` finds our `App.py` (not the SDK's)
2. `sdk/Build/scripts/` — so integration tests can import `MissionLib` and other SDK scripts

MissionLib also imports `loadspacehelper` and five `Bridge.*` modules at the top level. We register empty stub modules for these so `import MissionLib` doesn't fail before we get to the timer logic.

- [ ] **Step 1: Write conftest.py**

```python
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SDK_SCRIPTS = PROJECT_ROOT / "sdk" / "Build" / "scripts"

def pytest_configure(config):
    # Our App.py must shadow sdk/Build/scripts/App.py
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    if str(SDK_SCRIPTS) not in sys.path:
        sys.path.append(str(SDK_SCRIPTS))

    # Stub out SDK modules that MissionLib imports but we don't implement yet
    _stub_modules = [
        "loadspacehelper",
        "Bridge",
        "Bridge.TacticalCharacterHandlers",
        "Bridge.HelmCharacterHandlers",
        "Bridge.XOCharacterHandlers",
        "Bridge.ScienceCharacterHandlers",
        "Bridge.EngineerCharacterHandlers",
        "BridgeHandlers",
        "Actions",
        "Actions.MissionScriptActions",
    ]
    for name in _stub_modules:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
```

- [ ] **Step 2: Create placeholder App.py so the import check works**

Create `App.py` at project root with just enough to import:

```python
NULL_ID = 0
```

- [ ] **Step 3: Write a smoke test**

Create `tests/unit/test_ids.py` with just the import check for now:

```python
def test_import_app():
    import App
    assert App.NULL_ID == 0
```

- [ ] **Step 4: Run it**

```bash
uv run pytest tests/unit/test_ids.py -v
```

Expected:
```
tests/unit/test_ids.py::test_import_app PASSED
```

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py App.py tests/unit/test_ids.py
git commit -m "test: add test infrastructure and App.py placeholder"
```

---

## Task 3: TGObject and ID registry

**Files:**
- Create: `engine/core/__init__.py`
- Create: `engine/core/ids.py`
- Modify: `tests/unit/test_ids.py`

Every BC object has a unique integer ID (`GetObjID()`). The ID registry is process-global. Objects auto-register on construction. `NULL_ID = 0` is the sentinel for "no object".

- [ ] **Step 1: Write the failing tests**

Replace `tests/unit/test_ids.py`:

```python
import pytest
from engine.core.ids import TGObject, get_object_by_id

def test_unique_ids():
    a = TGObject()
    b = TGObject()
    assert a.GetObjID() != b.GetObjID()

def test_id_nonzero():
    obj = TGObject()
    assert obj.GetObjID() != 0

def test_registry_lookup():
    obj = TGObject()
    assert get_object_by_id(obj.GetObjID()) is obj

def test_registry_miss_returns_none():
    assert get_object_by_id(999999) is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_ids.py -v
```

Expected: `ImportError: No module named 'engine.core.ids'`

- [ ] **Step 3: Create engine/core/__init__.py**

```python
```
(empty file)

- [ ] **Step 4: Implement engine/core/ids.py**

```python
import itertools

_counter = itertools.count(1)
_registry: dict[int, "TGObject"] = {}


def get_object_by_id(obj_id: int) -> "TGObject | None":
    return _registry.get(obj_id)


class TGObject:
    def __init__(self):
        self._obj_id = next(_counter)
        _registry[self._obj_id] = self

    def GetObjID(self) -> int:
        return self._obj_id
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_ids.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/core/__init__.py engine/core/ids.py tests/unit/test_ids.py
git commit -m "feat: add TGObject base class with process-global ID registry"
```

---

## Task 4: TGEvent and TGEventHandlerObject

**Files:**
- Modify: `engine/appc/events.py`
- Modify: `tests/unit/test_events.py`

`TGEvent` carries an event type (integer) and a destination object. `TGEventHandlerObject` is the base for anything that can receive events (Mission, action managers, etc.). It maintains a table of `{event_type: [handler_string]}` and dispatches by calling handlers by their qualified Python name (`"module.function"`).

Handler call signature (BC convention): `def my_handler(pObject, pEvent): ...`  
`pObject` is the destination object itself, `pEvent` is the event.

`TGEvent_Create()` is a factory function (mirrors the original App.py pattern where the SWIG layer wraps the C++ constructor).

- [ ] **Step 1: Write the failing tests**

Replace `tests/unit/test_events.py`:

```python
import sys
import types
import pytest
from engine.appc.events import (
    TGEvent, TGEvent_Create, TGEventHandlerObject,
)

ET_TEST = 9001  # arbitrary type constant for tests


def test_event_type_roundtrip():
    event = TGEvent_Create()
    event.SetEventType(ET_TEST)
    assert event.GetEventType() == ET_TEST


def test_event_destination_roundtrip():
    handler = TGEventHandlerObject()
    event = TGEvent_Create()
    event.SetDestination(handler)
    assert event.GetDestination() is handler


def test_event_create_returns_tgevent():
    assert isinstance(TGEvent_Create(), TGEvent)


def test_dispatch_calls_registered_handler():
    called_with = []

    # Register a real callable under a module-qualified name
    mod = types.ModuleType("_test_events_helper")
    def my_handler(pObject, pEvent):
        called_with.append((pObject, pEvent))
    mod.my_handler = my_handler
    sys.modules["_test_events_helper"] = mod

    handler_obj = TGEventHandlerObject()
    handler_obj.AddPythonFuncHandlerForInstance(ET_TEST, "_test_events_helper.my_handler")

    event = TGEvent_Create()
    event.SetEventType(ET_TEST)
    event.SetDestination(handler_obj)

    handler_obj.ProcessEvent(event)

    assert len(called_with) == 1
    assert called_with[0] == (handler_obj, event)


def test_dispatch_ignores_wrong_event_type():
    called = []
    mod = types.ModuleType("_test_events_helper2")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_test_events_helper2"] = mod

    handler_obj = TGEventHandlerObject()
    handler_obj.AddPythonFuncHandlerForInstance(ET_TEST, "_test_events_helper2.cb")

    event = TGEvent_Create()
    event.SetEventType(9002)  # different type
    handler_obj.ProcessEvent(event)

    assert called == []


def test_remove_handler():
    called = []
    mod = types.ModuleType("_test_events_helper3")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_test_events_helper3"] = mod

    handler_obj = TGEventHandlerObject()
    handler_obj.AddPythonFuncHandlerForInstance(ET_TEST, "_test_events_helper3.cb")
    handler_obj.RemoveHandlerForInstance(ET_TEST, "_test_events_helper3.cb")

    event = TGEvent_Create()
    event.SetEventType(ET_TEST)
    handler_obj.ProcessEvent(event)

    assert called == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_events.py -v
```

Expected: `ImportError` from `engine.appc.events`.

- [ ] **Step 3: Implement engine/appc/events.py**

```python
import sys
from engine.core.ids import TGObject


class TGEvent(TGObject):
    def __init__(self):
        super().__init__()
        self._event_type: int = 0
        self._destination: "TGEventHandlerObject | None" = None
        self._source: "TGObject | None" = None

    def SetEventType(self, event_type: int) -> None:
        self._event_type = event_type

    def GetEventType(self) -> int:
        return self._event_type

    def SetDestination(self, dest: "TGEventHandlerObject") -> None:
        self._destination = dest

    def GetDestination(self) -> "TGEventHandlerObject | None":
        return self._destination

    def SetSource(self, source: "TGObject") -> None:
        self._source = source

    def GetSource(self) -> "TGObject | None":
        return self._source


def TGEvent_Create() -> TGEvent:
    return TGEvent()


def _resolve_handler(qualified_name: str):
    """Resolve 'module.func' to the callable, or None if not found."""
    dot = qualified_name.rfind(".")
    if dot == -1:
        return None
    mod_name, func_name = qualified_name[:dot], qualified_name[dot + 1:]
    mod = sys.modules.get(mod_name)
    if mod is None:
        return None
    return getattr(mod, func_name, None)


class TGEventHandlerObject(TGObject):
    def __init__(self):
        super().__init__()
        # {event_type: [qualified_handler_name, ...]}
        self._handlers: dict[int, list[str]] = {}

    def AddPythonFuncHandlerForInstance(self, event_type: int, qualified_name: str) -> None:
        self._handlers.setdefault(event_type, []).append(qualified_name)

    def RemoveHandlerForInstance(self, event_type: int, qualified_name: str) -> None:
        handlers = self._handlers.get(event_type, [])
        if qualified_name in handlers:
            handlers.remove(qualified_name)

    def RemoveAllInstanceHandlers(self) -> None:
        self._handlers.clear()

    def ProcessEvent(self, event: TGEvent) -> None:
        for name in self._handlers.get(event.GetEventType(), []):
            fn = _resolve_handler(name)
            if fn is not None:
                fn(self, event)


class TGEventManager(TGObject):
    def __init__(self):
        super().__init__()

    def AddEvent(self, event: TGEvent) -> None:
        dest = event.GetDestination()
        if dest is not None:
            dest.ProcessEvent(event)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_events.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/events.py tests/unit/test_events.py
git commit -m "feat: implement TGEvent, TGEventHandlerObject, and TGEventManager"
```

---

## Task 5: Game, Episode, and Mission hierarchy

**Files:**
- Create: `engine/core/game.py`
- Create: `tests/unit/test_game.py`

`Mission` subclasses `TGEventHandlerObject` (so it can receive timer-fired events). `Episode` holds a current mission. `Game` holds a current episode. The module-level `Game_GetCurrentGame()` returns the active game singleton; `_set_current_game()` is for test setup.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_game.py`:

```python
import pytest
from engine.core.game import Game, Episode, Mission, Game_GetCurrentGame, _set_current_game
from engine.appc.events import TGEventHandlerObject


def test_game_episode_mission_chain():
    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)

    assert Game_GetCurrentGame() is game
    assert Game_GetCurrentGame().GetCurrentEpisode() is episode
    assert Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission() is mission


def test_no_game_returns_none():
    _set_current_game(None)
    assert Game_GetCurrentGame() is None


def test_mission_is_event_handler():
    mission = Mission()
    assert isinstance(mission, TGEventHandlerObject)
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_game.py -v
```

Expected: `ImportError: No module named 'engine.core.game'`

- [ ] **Step 3: Implement engine/core/game.py**

```python
from engine.core.ids import TGObject
from engine.appc.events import TGEventHandlerObject

_current_game: "Game | None" = None


def Game_GetCurrentGame() -> "Game | None":
    return _current_game


def _set_current_game(game: "Game | None") -> None:
    global _current_game
    _current_game = game


class Mission(TGEventHandlerObject):
    pass


class Episode(TGObject):
    def __init__(self):
        super().__init__()
        self._current_mission: Mission | None = None

    def GetCurrentMission(self) -> Mission | None:
        return self._current_mission

    def SetCurrentMission(self, mission: Mission) -> None:
        self._current_mission = mission


class Game(TGObject):
    def __init__(self):
        super().__init__()
        self._current_episode: Episode | None = None

    def GetCurrentEpisode(self) -> Episode | None:
        return self._current_episode

    def SetCurrentEpisode(self, episode: Episode) -> None:
        self._current_episode = episode
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_game.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/core/game.py tests/unit/test_game.py
git commit -m "feat: implement Game/Episode/Mission hierarchy"
```

---

## Task 6: TGTimer and TGTimerManager

**Files:**
- Modify: `engine/appc/timers.py`
- Create: `tests/unit/test_timers.py`

Timer semantics (from MissionLib analysis):
- `SetTimerStart(fStart)`: game-time seconds before first fire
- `SetDelay(fDelay)`: seconds between subsequent fires; 0 = one-shot (fires once at fStart, then done)
- `SetDuration(fDuration)`: total lifetime in game-time seconds; ≤ 0 = run indefinitely

Each `TGTimerManager.tick(delta)` advances all active timers by `delta` game-time seconds. When a timer fires, it calls `g_kEventManager.AddEvent(event)` — which dispatches immediately to `event.GetDestination().ProcessEvent(event)`.

`TGTimerManager` holds a reference to a `TGEventManager` so it can dispatch. The engine wires `g_kTimerManager` to `g_kEventManager` in `App.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_timers.py`:

```python
import sys
import types
import pytest
from engine.appc.events import TGEvent_Create, TGEventHandlerObject, TGEventManager
from engine.appc.timers import TGTimer, TGTimer_Create, TGTimerManager

TICK = 1.0 / 60.0  # 60 Hz game tick
ET_TEST = 8001


def _make_stack():
    """Return (event_manager, timer_manager, destination, event)."""
    em = TGEventManager()
    tm = TGTimerManager(em)
    dest = TGEventHandlerObject()
    ev = TGEvent_Create()
    ev.SetEventType(ET_TEST)
    ev.SetDestination(dest)
    return em, tm, dest, ev


def test_one_shot_fires_after_start():
    called = []
    mod = types.ModuleType("_tt1")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_tt1"] = mod

    em, tm, dest, ev = _make_stack()
    dest.AddPythonFuncHandlerForInstance(ET_TEST, "_tt1.cb")

    timer = TGTimer_Create()
    timer.SetTimerStart(3 * TICK)
    timer.SetDelay(0.0)
    timer.SetDuration(-1.0)
    timer.SetEvent(ev)
    tm.AddTimer(timer)

    # Tick twice — not yet
    tm.tick(TICK)
    tm.tick(TICK)
    assert called == []

    # Third tick crosses the 3-tick threshold
    tm.tick(TICK)
    assert called == [True]

    # One-shot: does not fire again
    tm.tick(TICK)
    tm.tick(TICK)
    assert len(called) == 1


def test_repeat_fires_multiple_times():
    called = []
    mod = types.ModuleType("_tt2")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_tt2"] = mod

    em, tm, dest, ev = _make_stack()
    dest.AddPythonFuncHandlerForInstance(ET_TEST, "_tt2.cb")

    timer = TGTimer_Create()
    timer.SetTimerStart(TICK)
    timer.SetDelay(TICK)
    timer.SetDuration(-1.0)
    timer.SetEvent(ev)
    tm.AddTimer(timer)

    for _ in range(5):
        tm.tick(TICK)

    assert len(called) == 5


def test_duration_stops_timer():
    called = []
    mod = types.ModuleType("_tt3")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_tt3"] = mod

    em, tm, dest, ev = _make_stack()
    dest.AddPythonFuncHandlerForInstance(ET_TEST, "_tt3.cb")

    timer = TGTimer_Create()
    timer.SetTimerStart(TICK)
    timer.SetDelay(TICK)
    timer.SetDuration(3 * TICK)   # stop after 3 ticks total
    timer.SetEvent(ev)
    tm.AddTimer(timer)

    for _ in range(10):
        tm.tick(TICK)

    assert len(called) == 3


def test_delete_timer_stops_firing():
    called = []
    mod = types.ModuleType("_tt4")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_tt4"] = mod

    em, tm, dest, ev = _make_stack()
    dest.AddPythonFuncHandlerForInstance(ET_TEST, "_tt4.cb")

    timer = TGTimer_Create()
    timer.SetTimerStart(TICK)
    timer.SetDelay(TICK)
    timer.SetDuration(-1.0)
    timer.SetEvent(ev)
    tm.AddTimer(timer)

    tm.tick(TICK)  # fires once
    tm.tick(TICK)  # fires twice
    assert len(called) == 2

    tm.DeleteTimer(timer.GetObjID())

    tm.tick(TICK)
    tm.tick(TICK)
    assert len(called) == 2  # no more fires
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_timers.py -v
```

Expected: `ImportError` from `engine.appc.timers`.

- [ ] **Step 3: Implement engine/appc/timers.py**

```python
from engine.core.ids import TGObject
from engine.appc.events import TGEvent, TGEventManager


class TGTimer(TGObject):
    def __init__(self):
        super().__init__()
        self._start: float = 0.0
        self._delay: float = 0.0
        self._duration: float = -1.0
        self._event: TGEvent | None = None
        self._elapsed: float = 0.0
        self._next_fire: float = 0.0
        self._done: bool = False

    def SetTimerStart(self, start: float) -> None:
        self._start = start
        self._next_fire = start

    def GetTimerStart(self) -> float:
        return self._start

    def SetDelay(self, delay: float) -> None:
        self._delay = delay

    def GetDelay(self) -> float:
        return self._delay

    def SetDuration(self, duration: float) -> None:
        self._duration = duration

    def GetDuration(self) -> float:
        return self._duration

    def SetEvent(self, event: TGEvent) -> None:
        self._event = event

    def GetEvent(self) -> TGEvent | None:
        return self._event

    def tick(self, delta: float) -> None:
        """Advance elapsed time and return whether the timer fired this tick."""
        if self._done:
            return
        self._elapsed += delta
        while self._elapsed >= self._next_fire:
            if self._event is not None:
                # Caller (TGTimerManager) handles dispatch
                self._fire_pending = True
            if self._delay <= 0:
                self._done = True
                break
            self._next_fire += self._delay
        if self._duration > 0 and self._elapsed >= self._start + self._duration:
            self._done = True


def TGTimer_Create() -> TGTimer:
    return TGTimer()


class TGTimerManager:
    def __init__(self, event_manager: TGEventManager):
        self._event_manager = event_manager
        self._timers: dict[int, TGTimer] = {}

    def AddTimer(self, timer: TGTimer) -> None:
        timer._fire_pending = False
        self._timers[timer.GetObjID()] = timer

    def RemoveTimer(self, timer: TGTimer) -> None:
        self._timers.pop(timer.GetObjID(), None)

    def DeleteTimer(self, obj_id: int) -> None:
        self._timers.pop(obj_id, None)

    def tick(self, delta: float) -> None:
        to_remove = []
        for obj_id, timer in list(self._timers.items()):
            timer._fire_pending = False
            timer.tick(delta)
            if timer._fire_pending and timer._event is not None:
                self._event_manager.AddEvent(timer._event)
            if timer._done:
                to_remove.append(obj_id)
        for obj_id in to_remove:
            self._timers.pop(obj_id, None)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_timers.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/timers.py tests/unit/test_timers.py
git commit -m "feat: implement TGTimer and TGTimerManager with tick-driven dispatch"
```

---

## Task 7: App.py — wire everything up

**Files:**
- Modify: `App.py` (project root)

Wire all implementations into the top-level `App` module. Add the `__getattr__` fallback so that any attribute not explicitly defined returns a `_Stub` — this silences `AttributeError` for the large unimplemented surface (renderer classes, audio, UI widgets, etc.) so SDK scripts can be imported without crashing.

The `_Stub` class supports: attribute access (returns another `_Stub`), calling (returns another `_Stub`), truthiness (returns `False` so `if pGame:` guards work correctly).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_app.py`:

```python
import App


def test_null_id():
    assert App.NULL_ID == 0


def test_constants():
    import math
    assert abs(App.PI - math.pi) < 1e-6
    assert abs(App.HALF_PI - math.pi / 2) < 1e-6
    assert abs(App.TWO_PI - 2 * math.pi) < 1e-6


def test_timer_manager_exists():
    assert App.g_kTimerManager is not None


def test_realtime_timer_manager_exists():
    assert App.g_kRealtimeTimerManager is not None


def test_event_manager_exists():
    assert App.g_kEventManager is not None


def test_tgevent_create():
    from engine.appc.events import TGEvent
    ev = App.TGEvent_Create()
    assert isinstance(ev, TGEvent)


def test_tgtimer_create():
    from engine.appc.timers import TGTimer
    t = App.TGTimer_Create()
    assert isinstance(t, TGTimer)


def test_stub_unknown_attribute_does_not_raise():
    thing = App.SomeClassThatDoesNotExist
    assert thing is not None


def test_stub_call_does_not_raise():
    result = App.SomeClassThatDoesNotExist()
    assert result is not None


def test_stub_is_falsy():
    # MissionLib guards: `if pGame == None` — stubs must not pass truthiness checks
    # that real objects would.  Stubs are falsy so guard patterns work.
    stub = App.SomeUnimplementedThing()
    assert not stub
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_app.py -v
```

Expected: several failures because `App.py` only has `NULL_ID = 0`.

- [ ] **Step 3: Implement App.py**

```python
import math
from engine.appc.events import (
    TGEvent, TGEvent_Create,
    TGEventHandlerObject, TGEventManager,
)
from engine.appc.timers import TGTimer, TGTimer_Create, TGTimerManager
from engine.core.game import Game, Episode, Mission, Game_GetCurrentGame, _set_current_game

# ── Numeric constants ──────────────────────────────────────────────────────────
NULL_ID = 0
PI = math.pi
HALF_PI = math.pi / 2.0
TWO_PI = math.pi * 2.0

# ── Singletons ─────────────────────────────────────────────────────────────────
g_kEventManager = TGEventManager()
g_kTimerManager = TGTimerManager(g_kEventManager)
g_kRealtimeTimerManager = TGTimerManager(g_kEventManager)

# ── Event-type constants (integers; values are arbitrary but stable) ───────────
# Only the subset needed for Phase 1.  Add more as SDK scripts demand them.
ET_AI_TIMER = 100
ET_ACTION_COMPLETED = 101
ET_MISSION_START = 102
ET_EPISODE_START = 103
ET_OBJECT_DELETED = 104


# ── Fallback stub ──────────────────────────────────────────────────────────────
class _Stub:
    """Returned for any App attribute not yet implemented.

    Falsy so that `if App.Game_GetCurrentGame():` guards behave correctly when
    the game object hasn't been set up.
    """
    def __getattr__(self, name):
        return _Stub()

    def __call__(self, *args, **kwargs):
        return _Stub()

    def __bool__(self):
        return False

    def __repr__(self):
        return "<App._Stub>"


def __getattr__(name):
    return _Stub()
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_app.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add App.py tests/unit/test_app.py
git commit -m "feat: implement App.py with singletons, constants, and __getattr__ fallback stub"
```

---

## Task 8: Integration test — MissionLib.CreateTimer fires callback

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_missionlib_timer.py`

This test imports the real `MissionLib.py` from the SDK and exercises the full path: `CreateTimer` → timer added to `g_kTimerManager` → `tick()` → event dispatched → Python callback invoked. It proves our shim is compatible with the real game scripts.

`MissionLib.CreateTimer` calls `App.Game_GetCurrentGame()` to get the current mission. We set that up via `_set_current_game`. The callback string `"tests.integration.test_missionlib_timer.on_timer"` must resolve in `sys.modules` at dispatch time — we register it via `sys.modules`.

- [ ] **Step 1: Write the integration test**

Create `tests/integration/__init__.py` (empty).

Create `tests/integration/test_missionlib_timer.py`:

```python
"""
Integration test: MissionLib.CreateTimer fires a Python callback.

Full path exercised:
  MissionLib.CreateTimer
    → App.TGEvent_Create / App.TGTimer_Create
    → App.g_kTimerManager.AddTimer
    → App.g_kTimerManager.tick(delta)
    → TGEventManager.AddEvent
    → Mission.ProcessEvent
    → registered Python callback
"""
import sys
import types
import pytest
import App
from engine.core.game import Game, Episode, Mission, _set_current_game

TICK = 1.0 / 60.0


@pytest.fixture(autouse=True)
def game_context():
    """Set up a minimal Game/Episode/Mission stack for MissionLib."""
    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield game, episode, mission
    _set_current_game(None)
    # Reset timer manager state between tests
    App.g_kTimerManager._timers.clear()


def test_create_timer_fires_callback(game_context):
    _, _, mission = game_context

    fired = []

    # Register callback under a module-qualified name MissionLib can look up
    mod = types.ModuleType("tests.integration.test_missionlib_timer_helper")
    mod.on_timer = lambda pObj, pEv: fired.append(True)
    sys.modules["tests.integration.test_missionlib_timer_helper"] = mod

    import MissionLib
    MissionLib.CreateTimer(
        App.ET_AI_TIMER,
        "tests.integration.test_missionlib_timer_helper.on_timer",
        fStart=TICK,
        fDelay=0.0,
        fDuration=-1.0,
    )

    # Should not have fired yet
    assert fired == []

    # One tick — fires
    App.g_kTimerManager.tick(TICK)
    assert fired == [True]

    # One-shot: does not fire again
    App.g_kTimerManager.tick(TICK)
    assert fired == [True]
```

- [ ] **Step 2: Run to confirm it fails (or check what the actual failure is)**

```bash
uv run pytest tests/integration/test_missionlib_timer.py -v
```

Expected: the test runs and either passes or reveals the first real gap. If `MissionLib` imports cleanly and `CreateTimer` runs, it should pass. If there's an `AttributeError` on a stub, that identifies the next real thing to implement.

- [ ] **Step 3: Fix any import-time failures**

If `import MissionLib` fails with an `AttributeError` on `App`, add the missing name to `App.py`. It should be either a constant (add it to the `ET_*` block) or remain a stub (it already falls through `__getattr__`).

If `MissionLib` raises because one of its module-level statements does more than just read `App.NULL_ID`, investigate and add the minimum needed to `App.py` to satisfy it.

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_missionlib_timer.py
git commit -m "test: integration test — MissionLib.CreateTimer fires callback via tick loop"
```

---

## Self-Review

### Spec coverage

| Requirement | Covered by |
|---|---|
| `engine/App.py` skeleton with `__getattr__` fallback | Task 7 |
| Object ID system | Task 3 |
| `TGEvent` + `TGEventHandlerObject` dispatch | Task 4 |
| Game/Episode/Mission hierarchy | Task 5 |
| `TGTimer` + `TGTimerManager` with `tick(delta)` | Task 6 |
| `g_kTimerManager`, `g_kRealtimeTimerManager`, `g_kEventManager` singletons | Task 7 |
| `MissionLib.CreateTimer` fires callback | Task 8 |
| Test infrastructure (sys.path, SDK stub modules) | Task 2 |

### Known limitations / next steps after this plan

- `g_kRealtimeTimerManager` uses the same event manager as `g_kTimerManager`. In the real engine, real-time timers tick on wall-clock time, not game-time. This is correct enough for Phase 1 (all tests use explicit `tick()` calls), but will need revisiting when a real game loop is added.
- The `_Stub.__bool__ = False` behaviour means any guard like `if pShip:` on a stubbed ship object will take the "null" branch. This is intentional — it surfaces missing implementations rather than silently proceeding with stub data.
- `ET_*` constants are arbitrary integers. They match within one process but differ from the original game's values. This is fine for Phase 1 (Python scripts only compare them to each other, never to hardcoded integers).
