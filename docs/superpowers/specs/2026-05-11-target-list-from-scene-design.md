# Target List Panel — Driven by Scene Ships

**Status:** design  
**Date:** 2026-05-11

## Problem

The top-left "Targets" `UiPanel` in [engine/host_loop.py:824-854](../../../engine/host_loop.py#L824-L854) is filled with hardcoded demo collapsibles ("Bird of Prey-1", "USS Yamato", etc.). Now that the default mission (`M2Objects`) actually creates multiple ships at load — a player Galaxy plus `Galaxy 1` (friendly) and `Galaxy 2` (enemy) — the panel should mirror the live scene instead.

This spec covers two stages of the same upgrade:

- **Stage 1** — replace the demo content with one collapsible row per non-player ship in the scene, labelled by `ship.GetName()`, coloured by mission-group affiliation. Clicking a row calls `player.SetTarget(ship)`.
- **Stage 2** — expanding a row reveals one button per populated subsystem on that ship, drawn from the standard `ShipClass.Get*Subsystem()` getters. Clicking a subsystem button calls `player.SetTargetSubsystem(sub)`.

Both stages share the same lifecycle plumbing; stage 2 is additive on top of stage 1.

## Goals

- Target rows reflect actual ships in `App.g_kSetManager`, not a hardcoded list.
- Rows appear when ships are added to a set and disappear when ships die.
- No per-tick polling — the panel updates from lifecycle events.
- Mission swap clears and rebuilds the list cleanly.
- Stage 2 adds populated subsystems per row without restructuring stage 1 code.

## Non-goals

- Tracking ships that teleport between sets without dying (`RemoveObjectFromSet` is intentionally not a "destroyed" event).
- Sorting, filtering, or grouping rows. Insertion order is fine.
- Dynamic affiliation changes mid-mission. BC's Friendly/Enemy/Neutral groups are populated at mission init and treated as static.
- Highlighting the currently-targeted ship beyond the panel's existing radio-group visual. The radio group on `UiPanel` already handles single-selection visuals.
- Reading hardpoint files directly. Stage 2 uses the subsystems that the existing loader has already attached to each `ShipClass`.

## Architecture

Three new units, plus minor edits in three existing files.

| Unit | Where | Role |
|---|---|---|
| `ship_lifecycle` *(new)* | `engine/appc/ship_lifecycle.py` | Module-level pub/sub. Publishes `"added"` / `"destroyed"` events for ships, maintains a `_live` snapshot. Engine-side; UI-agnostic. |
| `TargetListController` *(new)* | `engine/ui/target_list.py` | Owns a `UiPanel`. Subscribes to `ship_lifecycle` and mirrors live ships into collapsible rows. Routes row clicks to `player.SetTarget(ship)`. Filters out the player ship. |
| `populated_subsystems` *(new, stage 2)* | inside `engine/ui/target_list.py` | Pure helper. Walks the canonical `Get*Subsystem()` getters and returns `[(label, subsystem), ...]` for non-`None` slots. |
| `SetClass.AddObjectToSet` *(edit)* | `engine/appc/sets.py` | After insertion, if the object is a `ShipClass`, call `ship_lifecycle.publish_added(obj)`. |
| `ShipClass.SetDead` *(edit)* | `engine/appc/ships.py` | On the `False → True` transition, call `ship_lifecycle.publish_destroyed(self)`. |
| `host_loop.run` *(edit)* | `engine/host_loop.py` | Replace the demo collapsibles with a `TargetListController` bound to the existing top-left panel. Wire mission swap to clear and rebuild. |

### Data flow

```
mission script (CreateMission)
    └─> loadspacehelper.CreateShip
            └─> App.ShipClass_Create           (no event — class-level name only)
            └─> pSet.AddObjectToSet(ship, "Galaxy 1")
                    └─> ship_lifecycle.publish_added(ship)
                            └─> TargetListController._on_event("added", ship)
                                    └─> UiPanel.collapsible(label, affiliation)

mission script (or damage system)
    └─> ship.SetDead(True)
            └─> ship_lifecycle.publish_destroyed(ship)
                    └─> TargetListController._on_event("destroyed", ship)
                            └─> row.destroy()

HostController.swap_mission(name) drained next tick
    └─> session.teardown(renderer)
    └─> ship_lifecycle.reset()                 (clears _live, NOT subscribers)
    └─> target_list.rebuild_from_snapshot()    (clears all rows from empty snapshot)
    └─> loader.load(name) runs mission init
            └─> repeats AddObjectToSet flow above for the new mission's ships
    └─> target_list.rebuild_from_snapshot()    (re-runs once player is set, so player gets excluded)
```

## Component details

### `engine/appc/ship_lifecycle.py`

```python
_subscribers: list[Callable[[str, ShipClass], None]] = []
_live: set[ShipClass] = set()

def subscribe(cb) -> Callable[[], None]:
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
    return tuple(_live)

def reset() -> None:
    _live.clear()    # subscribers persist across mission swap

def _fanout(event, ship):
    for cb in list(_subscribers):
        try: cb(event, ship)
        except Exception: pass    # one subscriber must not break others
```

Notes:
- **`_live` is a `set`**, not a list. Order doesn't matter for snapshot consumers; set semantics make `discard` cheap and idempotent.
- **`reset()` clears `_live` only.** Subscribers self-manage with the unsubscribe handle returned by `subscribe`.
- **Exception isolation** in `_fanout` is non-negotiable — UI bugs must not break event delivery.
- **No "moved between sets" event.** A ship leaving a set via `RemoveObjectFromSet` may be a teleport; only `SetDead(True)` is a real destruction signal.

### `SetClass.AddObjectToSet` edit

```python
def AddObjectToSet(self, obj, identifier: str) -> bool:
    # ... existing logic ...
    self._objects[identifier] = obj
    from engine.appc.ships import ShipClass
    if isinstance(obj, ShipClass):
        from engine.appc import ship_lifecycle
        ship_lifecycle.publish_added(obj)
    return True
```

Local imports avoid circular import risk between `sets.py` ↔ `ships.py` ↔ `ship_lifecycle.py`.

### `ShipClass.SetDead` edit

```python
def SetDead(self, v=True) -> None:
    new_dead = bool(v) if v is not True else True
    if new_dead and not self._dead:
        self._dead = True
        from engine.appc import ship_lifecycle
        ship_lifecycle.publish_destroyed(self)
    else:
        self._dead = new_dead
```

The transition guard ensures repeated `SetDead(True)` calls (common in mission scripts) fire exactly one event. `publish_destroyed` is also idempotent at the hub level (`set.discard`).

### `engine/ui/target_list.py`

```python
from typing import Callable, Optional
from engine.appc import ship_lifecycle
from engine.appc.ships import ShipClass
from engine.ui.panel import UiPanel
from engine.ui.collapsible import UiCollapsibleList

_SUBSYSTEM_GETTERS = (
    ("Hull",            "GetHull"),
    ("Sensors",         "GetSensorSubsystem"),
    ("Impulse Engines", "GetImpulseEngineSubsystem"),
    ("Warp Engines",    "GetWarpEngineSubsystem"),
    ("Phasers",         "GetPhaserSystem"),
    ("Pulse Weapons",   "GetPulseWeaponSystem"),
    ("Torpedoes",       "GetTorpedoSystem"),
    ("Tractor Beam",    "GetTractorBeamSystem"),
)

def populated_subsystems(ship) -> list[tuple[str, object]]:
    out = []
    for fallback, getter_name in _SUBSYSTEM_GETTERS:
        getter = getattr(ship, getter_name, None)
        if getter is None:
            continue
        sub = getter()
        if sub is None:
            continue
        label = (sub.GetName() if hasattr(sub, "GetName") else None) or fallback
        out.append((label, sub))
    return out

def _ship_affiliation(ship) -> str:
    """Resolve friendly/enemy/neutral via the current Mission's groups.
    Default 'unknown' when no group matches or no mission is loaded."""
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    if game is None: return "unknown"
    ep = game.GetCurrentEpisode()
    if ep is None: return "unknown"
    mission = ep.GetCurrentMission()
    if mission is None: return "unknown"
    name = ship.GetName()
    for getter, label in (
        (mission.GetFriendlyGroup, "friendly"),
        (mission.GetEnemyGroup,    "enemy"),
        (mission.GetNeutralGroup,  "neutral"),
    ):
        if getter().HasName(name):
            return label
    return "unknown"


class TargetListController:
    def __init__(self, panel: UiPanel, *,
                 player_provider: Callable[[], Optional[ShipClass]],
                 show_subsystems: bool = False):
        self._panel = panel
        self._get_player = player_provider
        self._show_subsystems = show_subsystems
        self._rows: dict[ShipClass, UiCollapsibleList] = {}
        self._unsub = ship_lifecycle.subscribe(self._on_event)
        self.rebuild_from_snapshot()

    def rebuild_from_snapshot(self) -> None:
        for ship in list(self._rows):
            self._remove_row(ship)
        for ship in ship_lifecycle.snapshot():
            self._add_row(ship)

    def _on_event(self, event: str, ship) -> None:
        if event == "added":   self._add_row(ship)
        else:                  self._remove_row(ship)

    def _add_row(self, ship) -> None:
        if ship is self._get_player(): return
        if ship in self._rows: return
        affiliation = _ship_affiliation(ship)
        row = self._panel.collapsible(
            label=ship.GetName(),
            affiliation=affiliation,
            expanded=False,
            on_click=lambda s=ship: self._select(s),
        )
        if self._show_subsystems:    # stage 2 only
            for label, sub in populated_subsystems(ship):
                row.button(label, on_click=lambda s=sub: self._select_subsystem(s))
        self._rows[ship] = row

    def _remove_row(self, ship) -> None:
        row = self._rows.pop(ship, None)
        if row is not None:
            row.destroy()

    def _select(self, ship) -> None:
        player = self._get_player()
        if player is not None:
            player.SetTarget(ship)

    def _select_subsystem(self, sub) -> None:    # stage 2 only
        player = self._get_player()
        if player is not None:
            player.SetTargetSubsystem(sub)

    def destroy(self) -> None:
        self._unsub()
        self._panel.clear()
        self._rows.clear()
```

Design choices:
- **`player_provider` is a callable.** Mission swap changes the player; we resolve lazily on every event.
- **Lambda default arg `s=ship`** captures the ship per row (closure-over-loop-variable trap mitigation).
- **`_add_row` is idempotent.** `if ship in self._rows: return` protects against duplicate events.
- **`show_subsystems` flag gates stage 2.** `ShipClass_Create` already populates 7 default subsystem instances ([engine/appc/ships.py:175-188](../../../engine/appc/ships.py#L175-L188)), so `populated_subsystems` returns non-empty results from day one. The flag — not the presence of populated slots — is what separates stages. Stage 1 constructs with `show_subsystems=False`; stage 2 flips it to `True` in `host_loop.run`.

### `host_loop.run` edits

Replace [engine/host_loop.py:824-854](../../../engine/host_loop.py#L824-L854):

```python
# Before: demo_panel = ui.UiPanel(id="demo", ..., title="Targets")
#         demo_panel.collapsible("Bird of Prey-1", affiliation="enemy", ...)
#         ... [hardcoded rows]

# After:
from engine.ui.target_list import TargetListController
import App as _App

target_panel = ui.UiPanel(id="targets", anchor="top-left",
                          width_vw=18.0, height_vh=55.0,
                          title="Targets")
target_list = TargetListController(
    target_panel,
    player_provider=lambda: _App.Game_GetCurrentPlayer(),
    show_subsystems=False,    # stage 2 flips this to True
)
```

After `controller.session = controller.loader.load(mission_name)` at [host_loop.py:863](../../../engine/host_loop.py#L863), re-run `target_list.rebuild_from_snapshot()` once. This is the "player is now set" moment that ensures the player row gets filtered out (during mission init, `AddObjectToSet` for the player fires before `Game.SetPlayer`).

In `HostController._drain_pending_swap`, after `session.teardown` and before `loader.load`:

```python
from engine.appc import ship_lifecycle
ship_lifecycle.reset()
# target_list.rebuild_from_snapshot() runs after loader.load completes,
# same as the initial-mission path.
```

`HostController` doesn't import `target_list` directly; `host_loop.run` passes a post-load hook the controller invokes after the new session is built. Concretely: extend `HostController` with an optional `post_load_hook: Callable[[], None]` set by `host_loop.run` to `target_list.rebuild_from_snapshot`.

## Affiliation colors

Existing tokens in [engine/ui/theme.py](../../../engine/ui/theme.py): `friendly`, `enemy`, `neutral`, `unknown`. `UiPanel.collapsible(affiliation=...)` already routes these through `_AFFILIATION_DEFAULTS`. No theme changes required.

## Edge cases

- **First mission load racing player resolution.** `AddObjectToSet("player", player_ship)` fires `publish_added` before `Game.SetPlayer(player_ship)`. The first `_add_row` call for the player therefore can't filter itself out. Mitigation: post-load `rebuild_from_snapshot` runs after `Game.SetPlayer` and excludes the player.
- **Ship added under multiple names** (re-`AddObjectToSet` with a new identifier). `_live` is keyed by object identity, not name, so it's a no-op. The row keeps its original name.
- **`SetDead(True)` called on an object not in `_live`** (e.g. created before the controller existed). `_live.discard` is a no-op; `_fanout` runs anyway, and `_remove_row` no-ops because the ship isn't in `self._rows`.
- **Subscriber raises during fan-out.** Caught and swallowed in `_fanout`. We accept silent loss; logging would require pulling in an import chain we don't want at the event hub. Tests cover the catch.
- **Stage 2 with mid-life subsystem changes.** A subsystem destroyed mid-mission won't update its row. Acceptable for stage 2 (the SDK's hardpoints are immutable across a mission); add a separate signal if a future stage needs reactivity.

## Testing

Stage 1 — new tests:

- `tests/unit/test_ship_lifecycle.py` — subscribe/publish/snapshot/reset, idempotent destroy, exception isolation in fan-out.
- `tests/unit/test_sets_publish_lifecycle.py` — `AddObjectToSet` of a `ShipClass` publishes; non-ship objects do not publish; multiple-set membership does not double-publish (because `_live` is a set).
- `tests/unit/test_ships_set_dead_publishes.py` — `SetDead(True)` publishes exactly once; `SetDead(False)` does not; repeated `SetDead(True)` publishes only on the first transition.
- `tests/ui/test_target_list_controller.py` — given a fake panel + fake ship registry: rows appear/disappear with events, player is excluded, affiliation is resolved from a stub mission, click routes to `player.SetTarget`.
- `tests/host/test_target_panel_integration.py` — load `M2Objects` headless, walk the bindings DOM, assert rows for `Galaxy 1` (friendly) and `Galaxy 2` (enemy), and **no** row for `player`. Mission swap clears + rebuilds.

Stage 2 — additional tests:

- `tests/ui/test_populated_subsystems.py` — `populated_subsystems` skips `None` slots, prefers `sub.GetName()`, falls back to canonical label, ignores missing getters.
- `tests/ui/test_target_list_subsystem_rows.py` — given a ship with two populated subsystems, the row contains two child buttons; clicking calls `player.SetTargetSubsystem(sub)`.

The headless harness already covers UI bindings ([tests/ui/test_panel.py](../../../tests/ui/test_panel.py), [tests/ui/test_bindings.py](../../../tests/ui/test_bindings.py)) so DOM walks are straightforward. macOS pixel-readback flakiness does not apply — these are DOM and event-routing assertions.

## Implementation order

1. `engine/appc/ship_lifecycle.py` + unit tests.
2. `SetClass.AddObjectToSet` edit + unit test.
3. `ShipClass.SetDead` edit + unit test.
4. `engine/ui/target_list.py` (full controller, including `populated_subsystems` and `_select_subsystem`, gated by `show_subsystems=False` default) + UI tests for both gate states.
5. `host_loop.run` rewire with `show_subsystems=False` + integration test asserting no subsystem buttons render.
6. Stage 2: flip `show_subsystems=True` in `host_loop.run` + integration test asserting populated subsystem buttons appear and click routes to `SetTargetSubsystem`.

Steps 1–5 are stage 1. Step 6 is stage 2 and may land in a separate plan/PR.

## Files touched

- *Added:* `engine/appc/ship_lifecycle.py`, `engine/ui/target_list.py`
- *Edited:* `engine/appc/sets.py`, `engine/appc/ships.py`, `engine/host_loop.py`
- *Removed code:* demo collapsibles in `host_loop.run` ([host_loop.py:824-854](../../../engine/host_loop.py#L824-L854))
- *Tests:* see Testing section
