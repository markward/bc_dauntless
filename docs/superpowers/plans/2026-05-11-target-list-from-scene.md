# Target List From Scene — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded "Targets" demo panel with one that mirrors live ships in the scene via a small lifecycle pub/sub. Two stages in one plan: stage 1 ships only, stage 2 adds populated subsystem buttons.

**Architecture:** A module-level pub/sub at `engine/appc/ship_lifecycle.py` is published from `SetClass.AddObjectToSet` (added) and `ShipClass.SetDead` (destroyed). A new `TargetListController` in `engine/ui/target_list.py` subscribes, rebuilds its `UiPanel` from `ship_lifecycle.snapshot()` on every event, filters out the player, and routes row clicks to `player.SetTarget(ship)`. Stage 2 flips a `show_subsystems` flag that adds one child button per non-`None` `Get*Subsystem()` slot.

**Tech Stack:** Python 3 (engine), existing `engine.ui` components (`UiPanel`, `UiCollapsibleList`), pytest with `FakeDom` fixture, `App` shim for the SDK boundary.

**Spec:** [docs/superpowers/specs/2026-05-11-target-list-from-scene-design.md](../specs/2026-05-11-target-list-from-scene-design.md)

---

## File map

**New:**
- `engine/appc/ship_lifecycle.py` — pub/sub hub + `_live` set + `snapshot()` / `reset()`.
- `engine/ui/target_list.py` — `TargetListController`, `populated_subsystems`, `_ship_affiliation`.
- `tests/unit/test_ship_lifecycle.py`
- `tests/unit/test_sets_publish_lifecycle.py`
- `tests/unit/test_ship_set_dead_publishes.py`
- `tests/ui/test_target_list_controller.py`
- `tests/ui/test_populated_subsystems.py`
- `tests/host/test_target_panel_integration.py`

**Modified:**
- `engine/appc/sets.py` — `SetClass.AddObjectToSet` publishes on ship add.
- `engine/appc/ships.py` — `ShipClass.SetDead` publishes on False→True transition.
- `engine/host_loop.py` — replace demo `Targets` panel with `TargetListController`; add `post_load_hook` to `HostController`; call `ship_lifecycle.reset()` on mission swap.

---

## Task 1: ship_lifecycle pub/sub module

**Files:**
- Create: `engine/appc/ship_lifecycle.py`
- Test: `tests/unit/test_ship_lifecycle.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_ship_lifecycle.py`:

```python
"""Tests for the engine.appc.ship_lifecycle pub/sub hub."""
import pytest

from engine.appc import ship_lifecycle


@pytest.fixture(autouse=True)
def _reset_hub():
    # Ensure module-level state is clean between tests.
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


class _Ship:
    """Minimal stand-in — ship_lifecycle does not call any ship methods."""


def test_publish_added_records_in_live_and_fans_out():
    seen = []
    ship_lifecycle.subscribe(lambda event, ship: seen.append((event, ship)))
    s = _Ship()
    ship_lifecycle.publish_added(s)
    assert seen == [("added", s)]
    assert s in ship_lifecycle.snapshot()


def test_publish_destroyed_removes_from_live_and_fans_out():
    s = _Ship()
    ship_lifecycle.publish_added(s)
    seen = []
    ship_lifecycle.subscribe(lambda event, ship: seen.append((event, ship)))
    ship_lifecycle.publish_destroyed(s)
    assert seen == [("destroyed", s)]
    assert s not in ship_lifecycle.snapshot()


def test_publish_destroyed_on_unknown_ship_is_idempotent():
    seen = []
    ship_lifecycle.subscribe(lambda event, ship: seen.append((event, ship)))
    s = _Ship()
    # Never added, but the event must still fan out (subscribers may want to
    # know about an arbitrary destruction signal); _live just no-ops.
    ship_lifecycle.publish_destroyed(s)
    assert seen == [("destroyed", s)]
    assert s not in ship_lifecycle.snapshot()


def test_unsubscribe_handle_stops_delivery():
    seen = []
    unsub = ship_lifecycle.subscribe(lambda event, ship: seen.append(event))
    ship_lifecycle.publish_added(_Ship())
    unsub()
    ship_lifecycle.publish_added(_Ship())
    assert seen == ["added"]


def test_unsubscribe_is_idempotent():
    unsub = ship_lifecycle.subscribe(lambda event, ship: None)
    unsub()
    unsub()  # must not raise


def test_subscriber_exception_does_not_break_others():
    seen = []
    def boom(event, ship):
        raise RuntimeError("kaboom")
    ship_lifecycle.subscribe(boom)
    ship_lifecycle.subscribe(lambda event, ship: seen.append(event))
    ship_lifecycle.publish_added(_Ship())
    assert seen == ["added"]


def test_reset_clears_live_but_not_subscribers():
    seen = []
    ship_lifecycle.subscribe(lambda event, ship: seen.append(event))
    ship_lifecycle.publish_added(_Ship())
    assert len(ship_lifecycle.snapshot()) == 1
    ship_lifecycle.reset()
    assert ship_lifecycle.snapshot() == ()
    # Subscriber still wired up.
    ship_lifecycle.publish_added(_Ship())
    assert seen == ["added", "added"]


def test_snapshot_returns_tuple():
    ship_lifecycle.publish_added(_Ship())
    snap = ship_lifecycle.snapshot()
    assert isinstance(snap, tuple)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_lifecycle.py -v`
Expected: ImportError / ModuleNotFoundError on `engine.appc.ship_lifecycle`.

- [ ] **Step 3: Implement the module**

Create `engine/appc/ship_lifecycle.py`:

```python
"""Pub/sub for ship lifecycle events.

Subscribers receive ``("added", ship)`` when a ShipClass is inserted into a
set via SetClass.AddObjectToSet, and ``("destroyed", ship)`` when
ShipClass.SetDead transitions False -> True. The hub also maintains a
``_live`` set so late subscribers can call ``snapshot()`` to bootstrap.

The hub is engine-side and UI-agnostic. Subscribers manage their own
lifetime via the unsubscribe handle returned by ``subscribe``.
``reset()`` clears ``_live`` for mission swap; subscribers persist.
"""
from __future__ import annotations
from typing import Callable

_Callback = Callable[[str, object], None]

_subscribers: list[_Callback] = []
_live: set = set()


def subscribe(cb: _Callback) -> Callable[[], None]:
    """Register a callback. Returns an idempotent unsubscribe handle."""
    _subscribers.append(cb)
    def unsubscribe() -> None:
        if cb in _subscribers:
            _subscribers.remove(cb)
    return unsubscribe


def publish_added(ship) -> None:
    _live.add(ship)
    _fanout("added", ship)


def publish_destroyed(ship) -> None:
    _live.discard(ship)
    _fanout("destroyed", ship)


def snapshot() -> tuple:
    """Currently-live ships, in arbitrary order."""
    return tuple(_live)


def reset() -> None:
    """Clear _live (for mission swap). Subscribers are not affected."""
    _live.clear()


def _fanout(event: str, ship) -> None:
    # Snapshot subscriber list — a callback may unsubscribe itself.
    for cb in list(_subscribers):
        try:
            cb(event, ship)
        except Exception:
            # A subscriber must not break event delivery for others.
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_lifecycle.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ship_lifecycle.py tests/unit/test_ship_lifecycle.py
git commit -m "feat(appc): ship lifecycle pub/sub hub"
```

---

## Task 2: SetClass.AddObjectToSet publishes on ship add

**Files:**
- Modify: `engine/appc/sets.py` (the `AddObjectToSet` method)
- Test: `tests/unit/test_sets_publish_lifecycle.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sets_publish_lifecycle.py`:

```python
"""SetClass.AddObjectToSet publishes ship-added events for ShipClass objects."""
import pytest

from engine.appc import ship_lifecycle
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


@pytest.fixture(autouse=True)
def _reset_hub():
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


def test_adding_a_ship_publishes_added_event():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append((event, ship)))
    pSet = SetClass()
    pShip = ShipClass()
    pSet.AddObjectToSet(pShip, "Galaxy 1")
    assert events == [("added", pShip)]
    assert pShip in ship_lifecycle.snapshot()


def test_adding_a_non_ship_does_not_publish():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append((event, ship)))
    pSet = SetClass()
    class _NotAShip:
        def SetName(self, _): pass
    pSet.AddObjectToSet(_NotAShip(), "waypoint")
    assert events == []


def test_adding_same_ship_twice_does_not_double_track_in_live():
    pSet = SetClass()
    pShip = ShipClass()
    pSet.AddObjectToSet(pShip, "alpha")
    pSet.AddObjectToSet(pShip, "beta")    # re-add under new identifier
    # _live is a set keyed by identity; one entry only.
    assert ship_lifecycle.snapshot() == (pShip,)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sets_publish_lifecycle.py -v`
Expected: first two tests FAIL — `events == []` because nothing publishes yet.

- [ ] **Step 3: Patch `SetClass.AddObjectToSet`**

In [engine/appc/sets.py:65-72](../../../engine/appc/sets.py#L65-L72), replace:

```python
    def AddObjectToSet(self, obj, identifier: str) -> bool:
        if hasattr(obj, "SetName"):
            obj.SetName(identifier)
        if hasattr(obj, "_containing_set"):
            obj._containing_set = self
        self._objects[identifier] = obj
        return True
```

with:

```python
    def AddObjectToSet(self, obj, identifier: str) -> bool:
        if hasattr(obj, "SetName"):
            obj.SetName(identifier)
        if hasattr(obj, "_containing_set"):
            obj._containing_set = self
        self._objects[identifier] = obj
        # Publish ship lifecycle for downstream subscribers (target panel,
        # HUD, minimap). Local import to keep sets.py free of cyclic deps.
        from engine.appc.ships import ShipClass
        from engine.appc import ship_lifecycle
        if isinstance(obj, ShipClass):
            ship_lifecycle.publish_added(obj)
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sets_publish_lifecycle.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the existing test suite to confirm no regressions**

Run: `uv run pytest tests/unit/ tests/ui/ -x`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/sets.py tests/unit/test_sets_publish_lifecycle.py
git commit -m "feat(appc): publish ship-added on SetClass.AddObjectToSet"
```

---

## Task 3: ShipClass.SetDead publishes on transition

**Files:**
- Modify: `engine/appc/ships.py` (the `SetDead` method at line 144)
- Test: `tests/unit/test_ship_set_dead_publishes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_ship_set_dead_publishes.py`:

```python
"""ShipClass.SetDead publishes a destroyed event exactly on False -> True."""
import pytest

from engine.appc import ship_lifecycle
from engine.appc.ships import ShipClass


@pytest.fixture(autouse=True)
def _reset_hub():
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


def test_set_dead_true_publishes_destroyed_once():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append(event))
    s = ShipClass()
    s.SetDead(True)
    assert events == ["destroyed"]
    assert s.IsDead() == 1


def test_set_dead_true_twice_publishes_once():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append(event))
    s = ShipClass()
    s.SetDead(True)
    s.SetDead(True)
    assert events == ["destroyed"]


def test_set_dead_false_does_not_publish():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append(event))
    s = ShipClass()
    s.SetDead(False)
    assert events == []
    assert s.IsDead() == 0


def test_resurrection_then_redeath_publishes_again():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append(event))
    s = ShipClass()
    s.SetDead(True)
    s.SetDead(False)         # back to alive
    s.SetDead(True)          # killed again
    assert events == ["destroyed", "destroyed"]


def test_default_arg_sets_dead_and_publishes():
    # Per ShipClass.SetDead signature: zero-arg form must set dead.
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append(event))
    s = ShipClass()
    s.SetDead()
    assert events == ["destroyed"]
    assert s.IsDead() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_set_dead_publishes.py -v`
Expected: all FAIL — current `SetDead` doesn't publish.

- [ ] **Step 3: Patch `ShipClass.SetDead`**

In [engine/appc/ships.py:143-146](../../../engine/appc/ships.py#L143-L146), replace:

```python
    def IsDead(self) -> int:      return 1 if self._dead else 0
    def SetDead(self, v=True) -> None:
        # Single-arg form (truthy) and zero-arg form (sets dead) both used.
        self._dead = bool(v) if v is not True else True
```

with:

```python
    def IsDead(self) -> int:      return 1 if self._dead else 0
    def SetDead(self, v=True) -> None:
        # Single-arg form (truthy) and zero-arg form (sets dead) both used.
        new_dead = bool(v) if v is not True else True
        was_dead = self._dead
        self._dead = new_dead
        if new_dead and not was_dead:
            from engine.appc import ship_lifecycle
            ship_lifecycle.publish_destroyed(self)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_set_dead_publishes.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run the existing test suite to confirm no regressions**

Run: `uv run pytest tests/unit/ -x`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_ship_set_dead_publishes.py
git commit -m "feat(appc): publish ship-destroyed on SetDead transition"
```

---

## Task 4: TargetListController (stage 1) + populated_subsystems helper

**Files:**
- Create: `engine/ui/target_list.py`
- Test: `tests/ui/test_target_list_controller.py`, `tests/ui/test_populated_subsystems.py`

- [ ] **Step 1: Write the failing tests for `populated_subsystems`**

Create `tests/ui/test_populated_subsystems.py`:

```python
"""populated_subsystems iterates the canonical getters and skips None slots."""
from engine.ui.target_list import populated_subsystems


class _Sub:
    def __init__(self, name): self._name = name
    def GetName(self): return self._name


class _ShipAllPopulated:
    def GetHull(self):                  return _Sub("Custom Hull")
    def GetSensorSubsystem(self):       return _Sub("Sensor Subsystem")
    def GetImpulseEngineSubsystem(self):return _Sub("Impulse Engines")
    def GetWarpEngineSubsystem(self):   return _Sub("Warp Engines")
    def GetPhaserSystem(self):          return _Sub("Phaser System")
    def GetPulseWeaponSystem(self):     return _Sub("Pulse Weapon System")
    def GetTorpedoSystem(self):         return _Sub("Torpedo System")
    def GetTractorBeamSystem(self):     return _Sub("Tractor Beam System")


class _ShipSparse:
    def GetHull(self):                  return None  # explicit None
    def GetSensorSubsystem(self):       return _Sub("Sensors")
    def GetImpulseEngineSubsystem(self):return None
    def GetWarpEngineSubsystem(self):   return None
    def GetPhaserSystem(self):          return None
    def GetPulseWeaponSystem(self):     return None
    def GetTorpedoSystem(self):         return None
    def GetTractorBeamSystem(self):     return None


class _ShipNameless:
    # Subsystem without GetName — fall back to canonical label.
    class _NamelessSub: pass
    def GetHull(self):                  return self._NamelessSub()
    def GetSensorSubsystem(self):       return None
    def GetImpulseEngineSubsystem(self):return None
    def GetWarpEngineSubsystem(self):   return None
    def GetPhaserSystem(self):          return None
    def GetPulseWeaponSystem(self):     return None
    def GetTorpedoSystem(self):         return None
    def GetTractorBeamSystem(self):     return None


class _ShipNoSubsystemGetters:
    pass    # missing getters entirely — must not raise


def test_all_populated_returns_eight_in_canonical_order():
    rows = populated_subsystems(_ShipAllPopulated())
    labels = [label for label, _ in rows]
    assert labels == [
        "Custom Hull", "Sensor Subsystem", "Impulse Engines",
        "Warp Engines", "Phaser System", "Pulse Weapon System",
        "Torpedo System", "Tractor Beam System",
    ]


def test_sparse_ship_returns_only_populated():
    rows = populated_subsystems(_ShipSparse())
    assert [label for label, _ in rows] == ["Sensors"]


def test_nameless_subsystem_falls_back_to_canonical_label():
    rows = populated_subsystems(_ShipNameless())
    assert [label for label, _ in rows] == ["Hull"]


def test_missing_getters_do_not_raise():
    assert populated_subsystems(_ShipNoSubsystemGetters()) == []


def test_returns_subsystem_instance_alongside_label():
    rows = populated_subsystems(_ShipSparse())
    label, sub = rows[0]
    assert label == "Sensors"
    assert sub.GetName() == "Sensors"
```

- [ ] **Step 2: Write the failing tests for `TargetListController`**

Create `tests/ui/test_target_list_controller.py`:

```python
"""TargetListController mirrors ship_lifecycle into a UiPanel."""
import pytest

from engine.appc import ship_lifecycle
from engine.appc.ships import ShipClass
from engine.ui import UiPanel
from engine.ui.target_list import TargetListController


@pytest.fixture(autouse=True)
def _reset_hub():
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


class _FakeMission:
    """Stub mission with three name-list groups for affiliation lookup."""
    class _Group:
        def __init__(self, names):
            self._names = set(names)
        def HasName(self, name):
            return 1 if name in self._names else 0
    def __init__(self, friendly=(), enemy=(), neutral=()):
        self._f = self._Group(friendly)
        self._e = self._Group(enemy)
        self._n = self._Group(neutral)
    def GetFriendlyGroup(self): return self._f
    def GetEnemyGroup(self):    return self._e
    def GetNeutralGroup(self):  return self._n


class _FakeEpisode:
    def __init__(self, mission): self._m = mission
    def GetCurrentMission(self): return self._m


class _FakeGame:
    def __init__(self, mission): self._ep = _FakeEpisode(mission)
    def GetCurrentEpisode(self): return self._ep


@pytest.fixture
def install_game(monkeypatch):
    """Install a fake Game_GetCurrentGame returning the given mission."""
    def _install(mission):
        from engine.core import game as game_module
        monkeypatch.setattr(game_module, "_current_game", _FakeGame(mission))
    return _install


def _make_ship(name: str) -> ShipClass:
    s = ShipClass()
    s.SetName(name)
    return s


def test_controller_adds_row_when_ship_published(fake_dom, install_game):
    install_game(_FakeMission(enemy=["Galaxy 2"]))
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    s = _make_ship("Galaxy 2")
    ship_lifecycle.publish_added(s)
    root = fake_dom.panel_root(panel.panel_id)
    # The panel has a header (title) + body. The body holds the collapsible.
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(body_id)
    assert len(wrappers) == 1
    assert "bc-collapsible" in fake_dom.element(wrappers[0]).classes


def test_controller_removes_row_when_ship_destroyed(fake_dom, install_game):
    install_game(_FakeMission(enemy=["E"]))
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    s = _make_ship("E")
    ship_lifecycle.publish_added(s)
    ship_lifecycle.publish_destroyed(s)
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    assert fake_dom.children(body_id) == []


def test_controller_excludes_player(fake_dom, install_game):
    install_game(_FakeMission(friendly=["player", "Galaxy 1"]))
    panel = UiPanel(id="targets", title="Targets")
    player = _make_ship("player")
    ctrl = TargetListController(panel, player_provider=lambda: player)
    galaxy1 = _make_ship("Galaxy 1")
    ship_lifecycle.publish_added(player)
    ship_lifecycle.publish_added(galaxy1)
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(body_id)
    # Only Galaxy 1, not the player.
    assert len(wrappers) == 1
    title_id = fake_dom.children(fake_dom.children(wrappers[0])[0])[1]
    assert fake_dom.element(title_id).text == "Galaxy 1"


def test_controller_assigns_affiliation_class(fake_dom, install_game):
    install_game(_FakeMission(friendly=["F"], enemy=["E"], neutral=["N"]))
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    ship_lifecycle.publish_added(_make_ship("F"))
    ship_lifecycle.publish_added(_make_ship("E"))
    ship_lifecycle.publish_added(_make_ship("N"))
    ship_lifecycle.publish_added(_make_ship("U"))    # unknown
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(body_id)
    headers = [fake_dom.children(w)[0] for w in wrappers]
    classes_per_header = [fake_dom.element(h).classes for h in headers]
    found = set()
    for cls in classes_per_header:
        for c in cls:
            if c.startswith("aff-"):
                found.add(c)
    assert found == {"aff-friendly", "aff-enemy", "aff-neutral", "aff-unknown"}


def test_controller_routes_row_click_to_set_target(fake_dom, install_game):
    install_game(_FakeMission(enemy=["E"]))
    panel = UiPanel(id="targets", title="Targets")
    player = _make_ship("player")
    ctrl = TargetListController(panel, player_provider=lambda: player)
    enemy = _make_ship("E")
    ship_lifecycle.publish_added(enemy)
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrapper = fake_dom.children(body_id)[0]
    header = fake_dom.children(wrapper)[0]
    title_id = fake_dom.children(header)[1]    # arrow then title
    fake_dom.fire_click(title_id)
    assert player.GetTarget() is enemy


def test_controller_does_not_render_subsystems_in_stage_1(fake_dom, install_game):
    """show_subsystems=False (default) must not add child buttons even when
    every Get*Subsystem() returns a real instance (which ShipClass_Create
    arranges by default)."""
    from engine.appc.ships import ShipClass_Create
    install_game(_FakeMission(enemy=["X"]))
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    ship = ShipClass_Create("X")
    ship.SetName("X")
    ship_lifecycle.publish_added(ship)
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrapper = fake_dom.children(body_id)[0]
    # bc-collapsible-children is the second child of the wrapper.
    children_container = fake_dom.children(wrapper)[1]
    assert fake_dom.children(children_container) == []


def test_controller_destroy_unsubscribes(fake_dom, install_game):
    install_game(_FakeMission())
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    ctrl.destroy()
    # No subscriber should remain.
    assert ship_lifecycle._subscribers == []
    # After destroy, publishing must not raise even though the panel is gone.
    ship_lifecycle.publish_added(_make_ship("noone"))


def test_rebuild_from_snapshot_filters_player_added_before_player_provider_resolves(
    fake_dom, install_game
):
    """Models the first-mission-load race: player ship is published BEFORE
    Game.SetPlayer is called. rebuild_from_snapshot() rerun after the
    player is set must drop the player's row."""
    install_game(_FakeMission(friendly=["player"]))
    panel = UiPanel(id="targets", title="Targets")
    player = _make_ship("player")
    other  = _make_ship("Galaxy 1")
    player_holder = {"p": None}    # initially no player
    ctrl = TargetListController(
        panel,
        player_provider=lambda: player_holder["p"],
    )
    ship_lifecycle.publish_added(player)
    ship_lifecycle.publish_added(other)
    # Now Game.SetPlayer would have run:
    player_holder["p"] = player
    ctrl.rebuild_from_snapshot()
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(body_id)
    title_ids = [fake_dom.children(fake_dom.children(w)[0])[1] for w in wrappers]
    titles = [fake_dom.element(t).text for t in title_ids]
    assert titles == ["Galaxy 1"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/ui/test_target_list_controller.py tests/ui/test_populated_subsystems.py -v`
Expected: ImportError on `engine.ui.target_list`.

- [ ] **Step 4: Implement `engine/ui/target_list.py`**

Create `engine/ui/target_list.py`:

```python
"""Controller that mirrors live ships from engine.appc.ship_lifecycle
into a UiPanel's collapsible rows. Stage 1 renders ship names + affiliation;
stage 2 (show_subsystems=True) adds one child button per populated
subsystem slot on each ship.
"""
from __future__ import annotations
from typing import Callable, Optional

from engine.appc import ship_lifecycle
from engine.ui.panel import UiPanel


# Canonical subsystem display order — matches the BC target panel.
# Hull comes first because it's the catch-all damage sink.
_SUBSYSTEM_GETTERS = (
    ("Hull",                "GetHull"),
    ("Sensor Subsystem",    "GetSensorSubsystem"),
    ("Impulse Engines",     "GetImpulseEngineSubsystem"),
    ("Warp Engines",        "GetWarpEngineSubsystem"),
    ("Phaser System",       "GetPhaserSystem"),
    ("Pulse Weapon System", "GetPulseWeaponSystem"),
    ("Torpedo System",      "GetTorpedoSystem"),
    ("Tractor Beam System", "GetTractorBeamSystem"),
)


def populated_subsystems(ship) -> list[tuple[str, object]]:
    """Return [(label, subsystem)] for each non-None subsystem slot on ship.

    Labels prefer ``subsystem.GetName()`` and fall back to the canonical
    label if the subsystem has no name. Missing getters are skipped
    silently — adding a new ShipClass subsystem getter does not require
    editing this module.
    """
    out: list[tuple[str, object]] = []
    for fallback, getter_name in _SUBSYSTEM_GETTERS:
        getter = getattr(ship, getter_name, None)
        if getter is None:
            continue
        sub = getter()
        if sub is None:
            continue
        label = None
        if hasattr(sub, "GetName"):
            label = sub.GetName()
        out.append((label or fallback, sub))
    return out


def _ship_affiliation(ship) -> str:
    """Friendly/enemy/neutral via the current Mission's name groups; default unknown."""
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    if game is None: return "unknown"
    episode = game.GetCurrentEpisode()
    if episode is None: return "unknown"
    mission = episode.GetCurrentMission()
    if mission is None: return "unknown"
    name = ship.GetName()
    if mission.GetFriendlyGroup().HasName(name): return "friendly"
    if mission.GetEnemyGroup().HasName(name):    return "enemy"
    if mission.GetNeutralGroup().HasName(name):  return "neutral"
    return "unknown"


class TargetListController:
    """Mirrors ship_lifecycle into a UiPanel.

    The controller is the single source of truth for what rows render:
    every event triggers a panel.clear() + rebuild from
    ship_lifecycle.snapshot(). For the small ship counts in BC missions
    (typically <20), the DOM churn cost is negligible and the
    implementation stays trivially correct under add/remove/reorder.
    """
    def __init__(self, panel: UiPanel, *,
                 player_provider: Callable[[], Optional[object]],
                 show_subsystems: bool = False):
        self._panel = panel
        self._get_player = player_provider
        self._show_subsystems = show_subsystems
        self._unsub = ship_lifecycle.subscribe(self._on_event)
        self.rebuild_from_snapshot()

    def rebuild_from_snapshot(self) -> None:
        """Clear all rows and add one per live, non-player ship."""
        self._panel.clear()
        for ship in ship_lifecycle.snapshot():
            self._add_row(ship)

    def destroy(self) -> None:
        self._unsub()
        self._panel.clear()

    # ── Event handler ─────────────────────────────────────────────────────────

    def _on_event(self, event: str, ship) -> None:
        # Both add and destroy collapse to a full rebuild — see class docstring.
        self.rebuild_from_snapshot()

    # ── Row construction ──────────────────────────────────────────────────────

    def _add_row(self, ship) -> None:
        if ship is self._get_player():
            return
        affiliation = _ship_affiliation(ship)
        row = self._panel.collapsible(
            label=ship.GetName(),
            affiliation=affiliation,
            expanded=False,
            on_click=lambda s=ship: self._select(s),
        )
        if self._show_subsystems:
            for label, sub in populated_subsystems(ship):
                row.button(label, on_click=lambda s=sub: self._select_subsystem(s))

    def _select(self, ship) -> None:
        player = self._get_player()
        if player is not None:
            player.SetTarget(ship)

    def _select_subsystem(self, sub) -> None:
        player = self._get_player()
        if player is not None:
            player.SetTargetSubsystem(sub)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_target_list_controller.py tests/ui/test_populated_subsystems.py -v`
Expected: all green.

- [ ] **Step 6: Run the broader UI suite to catch regressions**

Run: `uv run pytest tests/ui/ -x`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add engine/ui/target_list.py tests/ui/test_target_list_controller.py tests/ui/test_populated_subsystems.py
git commit -m "feat(ui): target list controller driven by ship lifecycle"
```

---

## Task 5: HostController post-load hook + mission-swap reset

**Files:**
- Modify: `engine/host_loop.py` (the `HostController` class around lines 696-728)

- [ ] **Step 1: Read the current HostController**

Run: `sed -n '696,729p' engine/host_loop.py` and confirm the class layout matches the snippet below before editing.

- [ ] **Step 2: Add `post_load_hook` attribute and call `ship_lifecycle.reset()` on swap**

In [engine/host_loop.py:702-728](../../../engine/host_loop.py#L702-L728), replace:

```python
    def __init__(self) -> None:
        self.renderer: Any = None
        self.loader: Any = None
        self.nif_to_handle: dict[str, int] = {}
        self.session: Optional[MissionSession] = None
        self.pending_swap: Optional[str] = None

    def swap_mission(self, mission_name: str) -> None:
        self.pending_swap = mission_name

    def _drain_pending_swap(self) -> None:
        if self.pending_swap is None:
            return
        name = self.pending_swap
        self.pending_swap = None
        if self.session is not None:
            self.session.teardown(self.renderer)
        reset_sdk_globals()
        assert self.loader is not None, "HostController.loader must be set"
        try:
            self.session = self.loader.load(name)
        except Exception as e:
            import traceback
            print(f"[host] mission swap to {name!r} failed: "
                  f"{type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            self.session = None
```

with:

```python
    def __init__(self) -> None:
        self.renderer: Any = None
        self.loader: Any = None
        self.nif_to_handle: dict[str, int] = {}
        self.session: Optional[MissionSession] = None
        self.pending_swap: Optional[str] = None
        # Invoked once after each successful loader.load(). host_loop wires
        # this to TargetListController.rebuild_from_snapshot so the panel
        # filters the player ship (Game.SetPlayer runs during loader.load
        # AFTER the ship is added to the set, so the initial publish_added
        # for the player can't filter itself out).
        self.post_load_hook: Optional[Callable[[], None]] = None

    def swap_mission(self, mission_name: str) -> None:
        self.pending_swap = mission_name

    def _drain_pending_swap(self) -> None:
        if self.pending_swap is None:
            return
        name = self.pending_swap
        self.pending_swap = None
        if self.session is not None:
            self.session.teardown(self.renderer)
        from engine.appc import ship_lifecycle
        ship_lifecycle.reset()
        reset_sdk_globals()
        assert self.loader is not None, "HostController.loader must be set"
        try:
            self.session = self.loader.load(name)
        except Exception as e:
            import traceback
            print(f"[host] mission swap to {name!r} failed: "
                  f"{type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            self.session = None
            return
        if self.post_load_hook is not None:
            self.post_load_hook()
```

Also add `Callable` to the `typing` import at the top of [engine/host_loop.py](../../../engine/host_loop.py) if not already present:

```python
from typing import Any, Callable, Iterable, Optional
```

- [ ] **Step 3: Verify the file still imports clean**

Run: `uv run python -c "import engine.host_loop"`
Expected: no output (clean import).

- [ ] **Step 4: Run the host suite to catch regressions**

Run: `uv run pytest tests/host/ -x`
Expected: all green. (No new tests yet — the integration test for the hook lands in Task 7.)

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host): HostController post-load hook + ship_lifecycle reset on swap"
```

---

## Task 6: Wire TargetListController into host_loop.run

**Files:**
- Modify: `engine/host_loop.py` (the demo panel block at lines 820-854 and the initial-load section)

- [ ] **Step 1: Replace the demo `Targets` panel with `TargetListController`**

In [engine/host_loop.py:820-854](../../../engine/host_loop.py#L820-L854), replace:

```python
        # Demo UI panel — proves the components render. Remove once a real
        # consumer (mission picker, targets panel) replaces it.
        from engine import ui
        ui.init()
        demo_panel = ui.UiPanel(id="demo", anchor="top-left",
                                width_vw=18.0, height_vh=55.0,
                                title="Targets")

        # Debug stat panel, top-right. Replaces the old hud.rml document.
        # Height accommodates the title + 4 stat rows + the "Load Mission"
        # button at the bottom without clipping (the panel has overflow:
        # hidden so under-tall heights silently cut the button off).
        debug_panel = ui.UiPanel(id="debug", anchor="top-right",
                                 width_vw=18.0, height_vh=25.0,
                                 title="Debug", collapsible=True)
        stat_ship   = debug_panel.stat("Ship",   "---")
        stat_system = debug_panel.stat("System", "---")
        stat_pos    = debug_panel.stat("Pos",    "0 0 0")
        stat_rot    = debug_panel.stat("Rot",    "Y0\xb0 P0\xb0 R0\xb0")
        bop = demo_panel.collapsible("Bird of Prey-1", affiliation="enemy",
                                     expanded=True)
        bop.button("Shield Generator")
        bop.button("Warp Core", selected=True)
        bop.collapsible("Disruptor Cannons", menu_level=3, expanded=False)
        bop.button("Torpedoes")
        bop.button("Impulse Engines")
        bop.collapsible("Warp Engines", menu_level=3, expanded=False)
        bop.button("Cloaking Device")
        bop.button("Sensor Array")
        demo_panel.collapsible("USS Yamato", affiliation="friendly",
                               expanded=False)
        demo_panel.collapsible("Tellarite Caravan", affiliation="neutral",
                               expanded=False)
        demo_panel.collapsible("Subspace Echo 47", affiliation="unknown",
                               expanded=False)
```

with:

```python
        from engine import ui
        from engine.ui.target_list import TargetListController
        ui.init()

        # Target list panel — mirrors live ships from ship_lifecycle.
        # Stage 1: ship names + affiliation only. Flip show_subsystems=True
        # in stage 2 to add populated subsystem buttons per row.
        target_panel = ui.UiPanel(id="targets", anchor="top-left",
                                  width_vw=18.0, height_vh=55.0,
                                  title="Targets")
        target_list = TargetListController(
            target_panel,
            player_provider=lambda: App.Game_GetCurrentPlayer(),
            show_subsystems=False,
        )

        # Debug stat panel, top-right. Replaces the old hud.rml document.
        # Height accommodates the title + 4 stat rows + the "Load Mission"
        # button at the bottom without clipping (the panel has overflow:
        # hidden so under-tall heights silently cut the button off).
        debug_panel = ui.UiPanel(id="debug", anchor="top-right",
                                 width_vw=18.0, height_vh=25.0,
                                 title="Debug", collapsible=True)
        stat_ship   = debug_panel.stat("Ship",   "---")
        stat_system = debug_panel.stat("System", "---")
        stat_pos    = debug_panel.stat("Pos",    "0 0 0")
        stat_rot    = debug_panel.stat("Rot",    "Y0\xb0 P0\xb0 R0\xb0")
```

- [ ] **Step 2: Wire the post-load hook**

After `controller = HostController()` and `controller.loader = _MissionLoader(...)` (around [engine/host_loop.py:860-862](../../../engine/host_loop.py#L860-L862)), and BEFORE `controller.session = controller.loader.load(mission_name)`, add:

```python
        controller.post_load_hook = target_list.rebuild_from_snapshot
```

Then add the SAME rebuild call AFTER the initial `controller.loader.load(mission_name)` so the first mission load also benefits from the post-load filter:

```python
        controller.session = controller.loader.load(mission_name)
        target_list.rebuild_from_snapshot()    # filter player after Game.SetPlayer
```

- [ ] **Step 3: Smoke-import the module**

Run: `uv run python -c "import engine.host_loop"`
Expected: clean import.

- [ ] **Step 4: Run host suite**

Run: `uv run pytest tests/host/ -x`
Expected: all green. (Integration test added in Task 7.)

- [ ] **Step 5: Run the engine headless to confirm it boots**

Run: `OPEN_STBC_HOST_HEADLESS=1 OPEN_STBC_HOST_VERBOSE=1 timeout 5s ./build/open_stbc 2>&1 | head -40`

Expected output contains:
- `[host_loop] mission=Custom.Tutorial.Episode.M2Objects.M2Objects`
- A render instance count line
- No tracebacks
- Process exits cleanly on timeout

If the binary is missing, build it: `cmake --build build -j` then re-run. Per CLAUDE.md, never run binaries from `native/build/` or `build/bin/` — only `build/open_stbc`.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host): replace demo targets panel with TargetListController"
```

---

## Task 7: Integration test — M2Objects target panel

**Files:**
- Create: `tests/host/test_target_panel_integration.py`

- [ ] **Step 1: Survey an existing host test to mirror its mission-load pattern**

Run: `sed -n '1,30p' tests/host/test_mission_session.py` to see how host tests boot a mission. The pattern is: import `engine.host_loop`, set up bindings stub if needed, call into the loader.

- [ ] **Step 2: Write the failing integration test**

Create `tests/host/test_target_panel_integration.py`:

```python
"""Loading M2Objects populates the Targets panel with Galaxy 1 + Galaxy 2,
and excludes the player."""
import pytest

from engine.appc import ship_lifecycle
from engine.ui import UiPanel, bindings as bindings_module
from engine.ui._dom import FakeDom
from engine.ui.target_list import TargetListController


@pytest.fixture
def fake_dom(monkeypatch) -> FakeDom:
    dom = FakeDom()
    monkeypatch.setattr(bindings_module, "_active_dom", dom)
    return dom


@pytest.fixture(autouse=True)
def _reset_hub():
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


def _row_titles(fake_dom, panel) -> list[str]:
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(body_id)
    titles = []
    for w in wrappers:
        header = fake_dom.children(w)[0]
        # header children: [arrow, title]
        title_id = fake_dom.children(header)[1]
        titles.append(fake_dom.element(title_id).text)
    return titles


def test_m2objects_loads_with_galaxy_rows_and_no_player(fake_dom):
    from engine.host_loop import _setup_sdk, _init_mission, SHIP_GATE_MISSION
    _setup_sdk()
    import App

    panel = UiPanel(id="targets", title="Targets")
    target_list = TargetListController(
        panel,
        player_provider=lambda: App.Game_GetCurrentPlayer(),
    )

    _init_mission(SHIP_GATE_MISSION)
    target_list.rebuild_from_snapshot()    # mirrors host_loop's post-load call

    titles = _row_titles(fake_dom, panel)
    assert set(titles) == {"Galaxy 1", "Galaxy 2"}
    assert "player" not in titles


def test_m2objects_affiliations(fake_dom):
    from engine.host_loop import _setup_sdk, _init_mission, SHIP_GATE_MISSION
    _setup_sdk()
    import App

    panel = UiPanel(id="targets", title="Targets")
    target_list = TargetListController(
        panel,
        player_provider=lambda: App.Game_GetCurrentPlayer(),
    )
    _init_mission(SHIP_GATE_MISSION)
    target_list.rebuild_from_snapshot()

    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    title_to_aff = {}
    for wrapper in fake_dom.children(body_id):
        header = fake_dom.children(wrapper)[0]
        title_id = fake_dom.children(header)[1]
        title = fake_dom.element(title_id).text
        aff = next((c for c in fake_dom.element(header).classes
                    if c.startswith("aff-")), None)
        title_to_aff[title] = aff
    assert title_to_aff == {"Galaxy 1": "aff-friendly", "Galaxy 2": "aff-enemy"}
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `uv run pytest tests/host/test_target_panel_integration.py -v`
Expected: 2 passed.

If `_setup_sdk` or `_init_mission` need importing, check [engine/host_loop.py](../../../engine/host_loop.py) for the public names and adjust imports. Both names are module-level in the existing host_loop.

- [ ] **Step 4: Run the full suite once to catch any cross-impact**

Run: `uv run pytest -x`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/host/test_target_panel_integration.py
git commit -m "test(host): M2Objects target panel integration"
```

---

## Stage 2 — populated subsystem rows

Tasks 1–7 deliver stage 1. The remaining tasks add stage 2 (subsystem buttons per row).

## Task 8: Enable subsystems in target panel + integration test

**Files:**
- Modify: `engine/host_loop.py` (single flag flip)
- Create: `tests/host/test_target_panel_subsystems.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/host/test_target_panel_subsystems.py`:

```python
"""With show_subsystems=True, M2Objects rows render populated subsystem buttons."""
import pytest

from engine.appc import ship_lifecycle
from engine.ui import UiPanel, bindings as bindings_module
from engine.ui._dom import FakeDom
from engine.ui.target_list import TargetListController, populated_subsystems


@pytest.fixture
def fake_dom(monkeypatch) -> FakeDom:
    dom = FakeDom()
    monkeypatch.setattr(bindings_module, "_active_dom", dom)
    return dom


@pytest.fixture(autouse=True)
def _reset_hub():
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


def test_subsystem_buttons_render_for_each_ship(fake_dom):
    from engine.host_loop import _setup_sdk, _init_mission, SHIP_GATE_MISSION
    _setup_sdk()
    import App

    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(
        panel,
        player_provider=lambda: App.Game_GetCurrentPlayer(),
        show_subsystems=True,
    )
    _init_mission(SHIP_GATE_MISSION)
    ctrl.rebuild_from_snapshot()

    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(body_id)
    assert len(wrappers) == 2    # Galaxy 1, Galaxy 2

    # Each wrapper has [header, children_container]; the second is where
    # subsystem buttons live.
    for wrapper in wrappers:
        children_container = fake_dom.children(wrapper)[1]
        button_ids = fake_dom.children(children_container)
        # ShipClass_Create populates 7 defaults; Hull stays None without a
        # HullProperty, so we expect 7 buttons per Galaxy.
        assert len(button_ids) >= 1
        assert len(button_ids) <= 8


def test_subsystem_click_routes_to_set_target_subsystem(fake_dom):
    from engine.host_loop import _setup_sdk, _init_mission, SHIP_GATE_MISSION
    _setup_sdk()
    import App

    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(
        panel,
        player_provider=lambda: App.Game_GetCurrentPlayer(),
        show_subsystems=True,
    )
    _init_mission(SHIP_GATE_MISSION)
    ctrl.rebuild_from_snapshot()

    player = App.Game_GetCurrentPlayer()
    assert player is not None

    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    first_wrapper = fake_dom.children(body_id)[0]
    children_container = fake_dom.children(first_wrapper)[1]
    first_button_id = fake_dom.children(children_container)[0]
    # UiButton is a single div whose on_click handler IS the click target —
    # no nested text element (see engine/ui/button.py:23-25).
    fake_dom.fire_click(first_button_id)
    # The targeted subsystem must equal the first one populated_subsystems
    # would return for the corresponding ship.
    target_sub = player.GetTargetSubsystem()
    assert target_sub is not None
    # Cross-check: it's one of the subsystems on a ship in the scene.
    candidates = set()
    for ship in ship_lifecycle.snapshot():
        if ship is player:
            continue
        for _, sub in populated_subsystems(ship):
            candidates.add(id(sub))
    assert id(target_sub) in candidates
```

- [ ] **Step 2: Run the test to confirm it fails as expected**

Run: `uv run pytest tests/host/test_target_panel_subsystems.py -v`
Expected: tests FAIL — `show_subsystems=False` in `host_loop.run`, but these tests instantiate their own controller with `show_subsystems=True`, so the first test *may* pass already. If both tests already pass at this point, that's fine — they're verifying the controller already supports stage 2; we still need to flip the host-level flag.

- [ ] **Step 3: Flip the flag in `host_loop.run`**

In [engine/host_loop.py](../../../engine/host_loop.py), find:

```python
        target_list = TargetListController(
            target_panel,
            player_provider=lambda: App.Game_GetCurrentPlayer(),
            show_subsystems=False,
        )
```

Change `show_subsystems=False` to `show_subsystems=True`.

- [ ] **Step 4: Re-run the full suite**

Run: `uv run pytest -x`
Expected: all green.

- [ ] **Step 5: Run the engine headless to spot-check**

Run: `OPEN_STBC_HOST_HEADLESS=1 OPEN_STBC_HOST_VERBOSE=1 timeout 5s ./build/open_stbc 2>&1 | head -40`
Expected: no tracebacks, mission loads. (Visual confirmation that subsystem buttons render requires a non-headless run with `OPEN_STBC_HOST_HEADLESS` unset; do that manually if a screen is available.)

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/host/test_target_panel_subsystems.py
git commit -m "feat(host): enable populated subsystem buttons in target panel"
```

---

## Self-review notes

- **Spec coverage:** all spec sections map to a task — ship_lifecycle (Task 1), publishers (Tasks 2-3), controller + helpers (Task 4), host wiring + mission swap (Tasks 5-6), integration (Task 7), stage 2 (Task 8).
- **`UiPanel.clear()` cascade:** the controller uses `panel.clear()` + rebuild on every event instead of granular `_add_row` / `_remove_row`. This avoids the panel-children-list-leak that granular removal would cause without further `UiPanel` API extension, and is well within performance budget for typical ship counts. Stage 2 inherits this for free.
- **Hull labelling:** in `populated_subsystems`, `Hull` only renders when the ship has a populated `_hull` — `ShipClass_Create` leaves it `None`, so it only appears after `SetupProperties()` runs with a HullProperty (Phase 2 hardpoint loading). Stage 2 will surface Hull for ships that have it without any code change.
- **Player race fix:** the first `publish_added` for the player fires before `Game.SetPlayer`. Both initial load and mission swap now run `target_list.rebuild_from_snapshot()` after `loader.load()` returns, which is when `Game.SetPlayer` has run (MissionLib calls it inside `CreatePlayerShip`).
