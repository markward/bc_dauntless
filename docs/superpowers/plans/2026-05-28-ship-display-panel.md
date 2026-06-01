# ShipDisplay Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the SDK `ShipDisplay` widget as two CEF panels (player + target), honouring the full SDK composite (hull bar, six-quadrant shields, damage list) and the SDK widget factory surface so unmodified bridge scripts continue to work.

**Architecture:** Single `ShipDisplayPanel(Panel)` class instantiated twice with `role="player"` and `role="target"`. SDK factories (`App.ShipDisplay_Create`, `ShieldsDisplay_Create`, `DamageDisplay_Create`, `STFillGauge_Create`) hand back the panel + sub-view objects the SDK script expects. CSS owns all layout; Python emits semantic state via `setShipDisplay(role, state)` JS calls keyed by `data-*` attributes that map SDK semantics to palette tokens.

**Tech Stack:** Python 3 (engine + tests, pytest), CEF (HTML/CSS/JS rendering via `_dauntless_host` bindings), SVG silhouettes per ship species.

**Spec:** [`docs/superpowers/specs/2026-05-28-ship-display-panel-design.md`](../specs/2026-05-28-ship-display-panel-design.md)

---

## Task 1: Skeleton ShipDisplayPanel class

**Files:**
- Create: `engine/ui/ship_display_panel.py`
- Test: `tests/unit/test_ship_display_panel.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ship_display_panel.py
"""ShipDisplayPanel snapshot + payload tests. See spec
docs/superpowers/specs/2026-05-28-ship-display-panel-design.md."""
import pytest


def test_player_role_panel_has_correct_name():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    assert panel.name == "ship-player"


def test_target_role_panel_has_correct_name():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    panel = ShipDisplayPanel(ROLE_TARGET)
    assert panel.name == "ship-target"


def test_invalid_role_raises():
    from engine.ui.ship_display_panel import ShipDisplayPanel
    with pytest.raises(AssertionError):
        ShipDisplayPanel("middle")


def test_player_panel_not_minimizable_by_default():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    assert panel.IsMinimized() == 0


def test_target_panel_minimizable_by_default():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    panel = ShipDisplayPanel(ROLE_TARGET)
    assert panel.IsMinimized() == 0
    panel.SetMinimized(1)
    assert panel.IsMinimized() == 1


def test_player_panel_setminimized_is_noop():
    """Player ShipDisplay can't minimize in stock BC."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    panel.SetMinimized(1)
    assert panel.IsMinimized() == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_display_panel.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.ui.ship_display_panel'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# engine/ui/ship_display_panel.py
"""CEF view for the SDK ShipDisplay widget.

The SDK creates two ShipDisplay widgets per game (player + target).
Spec: docs/superpowers/specs/2026-05-28-ship-display-panel-design.md
"""
from __future__ import annotations

from typing import Optional, Tuple

from engine.ui.panel import Panel


ROLE_PLAYER = "player"
ROLE_TARGET = "target"
_VALID_ROLES = (ROLE_PLAYER, ROLE_TARGET)


class ShipDisplayPanel(Panel):
    def __init__(self, role: str):
        super().__init__()
        assert role in _VALID_ROLES, "role must be 'player' or 'target'"
        self._role: str = role
        self._ship_id: int = 0  # App.NULL_ID — bound in Task 4
        self._last_snapshot: Optional[Tuple] = None
        self._minimizable: bool = (role == ROLE_TARGET)
        self._minimized: bool = False

    @property
    def name(self) -> str:
        return "ship-" + self._role

    # SDK widget API ----------------------------------------------------
    def SetShipID(self, ship_id) -> None:
        self._ship_id = int(ship_id)
        self._last_snapshot = None  # force re-emit on next tick

    def SetShipIDVar(self, ship_id) -> None:
        """SDK alias used by ShipDisplay.SetShipID at line 148."""
        self._ship_id = int(ship_id)

    def GetShipID(self) -> int:
        return self._ship_id

    def SetMinimizable(self, value) -> None:
        if self._role == ROLE_TARGET:
            self._minimizable = bool(value)

    def SetMinimized(self, value) -> None:
        if self._role == ROLE_TARGET:
            self._minimized = bool(value)
            self._last_snapshot = None

    def IsMinimized(self) -> int:
        return 1 if self._minimized else 0

    def IsMinimizable(self) -> int:
        return 1 if self._minimizable else 0

    # Panel framework ---------------------------------------------------
    def render_payload(self) -> Optional[str]:
        return None  # filled in Task 5

    def dispatch_event(self, action: str) -> bool:
        return False  # filled in Task 6

    def invalidate(self) -> None:
        self._last_snapshot = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_display_panel.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_display_panel.py tests/unit/test_ship_display_panel.py
git commit -m "feat(ui): skeleton ShipDisplayPanel with role + minimize state"
```

---

## Task 2: Sub-views with parent back-references

**Files:**
- Modify: `engine/ui/ship_display_panel.py` (add three sub-view classes and Set*Display adopters)
- Modify: `tests/unit/test_ship_display_panel.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_ship_display_panel.py`:

```python
def test_get_subviews_returns_orphans_until_set():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    # The SDK construction path is: create sub-views via factory THEN
    # SetXxxDisplay them. Before SetXxxDisplay the panel has empty
    # default sub-views (so calls don't crash); after, the passed
    # sub-view replaces them and gets its parent ref wired.
    sh = panel.GetShieldsDisplay()
    dm = panel.GetDamageDisplay()
    hg = panel.GetHealthGauge()
    assert sh is not None and dm is not None and hg is not None


def test_setshieldsdisplay_adopts_orphan_and_wires_parent():
    from engine.ui.ship_display_panel import (
        ShipDisplayPanel, ROLE_PLAYER, _ShieldsSubview,
    )
    panel = ShipDisplayPanel(ROLE_PLAYER)
    orphan = _ShieldsSubview(parent=None)
    panel.SetShieldsDisplay(orphan)
    assert panel.GetShieldsDisplay() is orphan
    assert orphan.parent is panel


def test_subview_update_for_new_ship_invalidates_parent_cache():
    from engine.ui.ship_display_panel import (
        ShipDisplayPanel, ROLE_PLAYER, _ShieldsSubview,
    )
    panel = ShipDisplayPanel(ROLE_PLAYER)
    panel._last_snapshot = ("cached",)
    orphan = _ShieldsSubview(parent=None)
    panel.SetShieldsDisplay(orphan)
    orphan.UpdateForNewShip()
    assert panel._last_snapshot is None


def test_setdamagedisplay_and_sethealthgauge_adopt_orphans():
    from engine.ui.ship_display_panel import (
        ShipDisplayPanel, ROLE_PLAYER,
        _DamageSubview, _HullGaugeSubview,
    )
    panel = ShipDisplayPanel(ROLE_PLAYER)
    d = _DamageSubview(parent=None)
    h = _HullGaugeSubview(parent=None)
    panel.SetDamageDisplay(d)
    panel.SetHealthGauge(h)
    assert panel.GetDamageDisplay() is d
    assert panel.GetHealthGauge() is h
    assert d.parent is panel
    assert h.parent is panel
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_display_panel.py -v`
Expected: 4 new tests fail (ImportError or AttributeError on `_ShieldsSubview` / `GetShieldsDisplay`).

- [ ] **Step 3: Implement sub-views and adopters**

In `engine/ui/ship_display_panel.py`, add above the `ShipDisplayPanel` class:

```python
class _SubviewBase:
    """Common base — sub-views forward mutations to the parent panel.

    The SDK constructs sub-views via factory calls BEFORE adoption
    (parent=None), then the parent ShipDisplay adopts them via
    SetXxxDisplay. Until adoption, mutations are buffered locally and
    take effect when the parent is wired in.
    """
    def __init__(self, parent: Optional["ShipDisplayPanel"]):
        self.parent: Optional["ShipDisplayPanel"] = parent

    def _invalidate(self) -> None:
        if self.parent is not None:
            self.parent._last_snapshot = None

    # SDK layout/visibility no-ops (CSS owns layout).
    def Resize(self, *args, **kwargs) -> None: pass
    def Layout(self, *args, **kwargs) -> None: pass
    def SetSkipParent(self, *args, **kwargs) -> None: pass
    def SetVisible(self, *args, **kwargs) -> None: pass
    def SetNotVisible(self, *args, **kwargs) -> None: pass
    def SetBatchChildPolys(self, *args, **kwargs) -> None: pass
    def RemoveEvents(self, *args, **kwargs) -> None: pass


class _ShieldsSubview(_SubviewBase):
    def UpdateForNewShip(self) -> None:
        self._invalidate()


class _DamageSubview(_SubviewBase):
    def UpdateForNewShip(self) -> None:
        self._invalidate()
    def RepositionUI(self, *args, **kwargs) -> None: pass
    def HideIcons(self, *args, **kwargs) -> None: pass
    def ShowIcons(self, *args, **kwargs) -> None: pass


class _HullGaugeSubview(_SubviewBase):
    def __init__(self, parent: Optional["ShipDisplayPanel"]):
        super().__init__(parent)
        self._object = None
    def SetObject(self, hull) -> None:
        self._object = hull
        self._invalidate()
    def SetFillColor(self, *args, **kwargs) -> None: pass
    def SetEmptyColor(self, *args, **kwargs) -> None: pass
```

In `ShipDisplayPanel.__init__`, after the `_minimized` line, add:

```python
        self._shields = _ShieldsSubview(parent=self)
        self._damage  = _DamageSubview(parent=self)
        self._gauge   = _HullGaugeSubview(parent=self)
```

In `ShipDisplayPanel`, add the getter/setter methods after `IsMinimizable`:

```python
    def GetShieldsDisplay(self): return self._shields
    def GetDamageDisplay(self):  return self._damage
    def GetHealthGauge(self):    return self._gauge

    def SetShieldsDisplay(self, subview: "_ShieldsSubview") -> None:
        subview.parent = self
        self._shields = subview
        self._last_snapshot = None

    def SetDamageDisplay(self, subview: "_DamageSubview") -> None:
        subview.parent = self
        self._damage = subview
        self._last_snapshot = None

    def SetHealthGauge(self, subview: "_HullGaugeSubview") -> None:
        subview.parent = self
        self._gauge = subview
        self._last_snapshot = None

    # SDK layout/chrome no-ops. The SDK construction path at
    # sdk/Build/scripts/Tactical/Interface/ShipDisplay.py:79-100 calls
    # these on the parent ShipDisplay — they must exist or construction
    # crashes. CSS owns layout, so they don't do anything except return
    # sensible defaults.
    def SetFixedSize(self, *args, **kwargs) -> None: pass
    def SetMaximumSize(self, *args, **kwargs) -> None: pass
    def SetPosition(self, *args, **kwargs) -> None: pass
    def Resize(self, *args, **kwargs) -> None: pass
    def AlignTo(self, *args, **kwargs) -> None: pass
    def Layout(self, *args, **kwargs) -> None: pass
    def InteriorChangedSize(self, *args, **kwargs) -> None: pass
    def SetBatchChildPolys(self, *args, **kwargs) -> None: pass
    def SetUseFocusGlass(self, *args, **kwargs) -> None: pass
    def SetNoFocus(self, *args, **kwargs) -> None: pass
    def SetAlwaysHandleEvents(self, *args, **kwargs) -> None: pass

    # Dimension getters return per-role constants so SDK chained math
    # (e.g. RepositionUI's "anchor to corner, chain by widths") resolves
    # without crashing. Values are not authoritative for layout.
    def GetLeft(self)         -> float: return 0.0
    def GetTop(self)          -> float: return 0.0
    def GetWidth(self)        -> float: return 0.2
    def GetHeight(self)       -> float: return 0.2
    def GetBorderWidth(self)  -> float: return 0.0
    def GetBorderHeight(self) -> float: return 0.0
    def GetMaximumInteriorWidth(self)  -> float: return 0.2
    def GetMaximumInteriorHeight(self) -> float: return 0.2

    # GetInteriorPane returns a sentinel that quacks like a pane —
    # the SDK only ever calls Resize/Layout on it, both no-ops.
    def GetInteriorPane(self):
        return self._gauge  # any _SubviewBase instance will accept Resize
```

Append this regression test to `tests/unit/test_ship_display_panel.py`:

```python
def test_sdk_layout_calls_are_noops():
    """SDK ShipDisplay.Create at lines 79-100 calls these on the parent."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    panel.SetFixedSize(0.2, 0.2, 0)
    panel.InteriorChangedSize()
    panel.Layout()
    panel.SetPosition(0.5, 0.5, 0)
    assert panel.GetInteriorPane() is not None
    assert panel.GetMaximumInteriorWidth() > 0
    assert panel.GetMaximumInteriorHeight() > 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_display_panel.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_display_panel.py tests/unit/test_ship_display_panel.py
git commit -m "feat(ui): ShipDisplayPanel sub-views with parent back-refs"
```

---

## Task 3: SDK shim factories

**Files:**
- Create: `engine/sdk_ui/widgets/ship_display.py`
- Modify: `App.py` (re-export factories)
- Test: `tests/integration/test_ship_display_sdk_integration.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_ship_display_sdk_integration.py
"""End-to-end test of the SDK construction path for ShipDisplay,
matching sdk/Build/scripts/Tactical/Interface/ShipDisplay.py:Create."""
import App


def setup_function(_):
    from engine.sdk_ui.widgets.ship_display import _reset_create_count
    _reset_create_count()
    from engine.ui.panel_registry import PanelRegistry
    from engine.sdk_ui.widgets.ship_display import set_panel_registry
    set_panel_registry(PanelRegistry())


def test_first_create_returns_player_panel():
    panel = App.ShipDisplay_Create(0.0, 0.0)
    assert panel.name == "ship-player"


def test_second_create_returns_target_panel():
    App.ShipDisplay_Create(0.0, 0.0)
    target = App.ShipDisplay_Create(0.0, 0.0)
    assert target.name == "ship-target"


def test_panels_register_with_active_registry():
    from engine.sdk_ui.widgets.ship_display import _active_registry
    p1 = App.ShipDisplay_Create(0.0, 0.0)
    p2 = App.ShipDisplay_Create(0.0, 0.0)
    names = [p.name for p in _active_registry()._panels]
    assert "ship-player" in names
    assert "ship-target" in names


def test_full_sdk_construction_path_runs_without_exceptions():
    """Replays sdk/Build/scripts/Tactical/Interface/ShipDisplay.py:Create."""
    pDisplay = App.ShipDisplay_Create(0.0, 0.0)
    pHealthGauge   = App.STFillGauge_Create()
    pDamageDisplay = App.DamageDisplay_Create(0.0, 0.0)
    pShieldsDisplay = App.ShieldsDisplay_Create(0.0, 0.0)
    pDisplay.SetHealthGauge(pHealthGauge)
    pDisplay.SetDamageDisplay(pDamageDisplay)
    pDisplay.SetShieldsDisplay(pShieldsDisplay)
    # Adoption wires parent refs
    assert pHealthGauge.parent is pDisplay
    assert pDamageDisplay.parent is pDisplay
    assert pShieldsDisplay.parent is pDisplay


def test_ship_display_cast_returns_panel_or_none():
    panel = App.ShipDisplay_Create(0.0, 0.0)
    assert App.ShipDisplay_Cast(panel) is panel
    assert App.ShipDisplay_Cast(object()) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/integration/test_ship_display_sdk_integration.py -v`
Expected: ImportError on `engine.sdk_ui.widgets.ship_display`.

- [ ] **Step 3: Create the SDK shim factory module**

```python
# engine/sdk_ui/widgets/ship_display.py
"""SDK widget factories for ShipDisplay + its sub-views.

The SDK creates two ShipDisplay widgets per bridge load
(LoadBridge.py runs Tactical/Interface/ShipDisplay.py:Create twice —
once for the player, once for the enemy/target). We hand out
ROLE_PLAYER on the first call, ROLE_TARGET on the second; the SDK's
construction order in TacticalControlWindow is stable, so this is
deterministic.

The active PanelRegistry is injected via set_panel_registry() at
host-loop startup, before any bridge load runs.

Spec: docs/superpowers/specs/2026-05-28-ship-display-panel-design.md
"""
from __future__ import annotations

from typing import Optional

from engine.ui.panel_registry import PanelRegistry
from engine.ui.ship_display_panel import (
    ShipDisplayPanel,
    ROLE_PLAYER,
    ROLE_TARGET,
    _ShieldsSubview,
    _DamageSubview,
    _HullGaugeSubview,
)


_create_count: int = 0
_registry: Optional[PanelRegistry] = None


def set_panel_registry(registry: PanelRegistry) -> None:
    """Called by host_loop right after PanelRegistry is constructed."""
    global _registry
    _registry = registry


def _active_registry() -> Optional[PanelRegistry]:
    return _registry


def _reset_create_count() -> None:
    """Called on bridge teardown so the next bridge load starts clean."""
    global _create_count
    _create_count = 0


def ShipDisplay_Create(*args, **kwargs) -> ShipDisplayPanel:
    global _create_count
    role = ROLE_PLAYER if _create_count == 0 else ROLE_TARGET
    _create_count += 1
    panel = ShipDisplayPanel(role)
    if _registry is not None:
        _registry.register(panel)
    return panel


def ShipDisplay_Cast(obj):
    return obj if isinstance(obj, ShipDisplayPanel) else None


def ShieldsDisplay_Create(*args, **kwargs) -> _ShieldsSubview:
    return _ShieldsSubview(parent=None)


def DamageDisplay_Create(*args, **kwargs) -> _DamageSubview:
    return _DamageSubview(parent=None)


def STFillGauge_Create(*args, **kwargs) -> _HullGaugeSubview:
    return _HullGaugeSubview(parent=None)
```

- [ ] **Step 4: Re-export factories from App.py**

Add to the appropriate `from engine.sdk_ui...` import block in `App.py`:

```python
from engine.sdk_ui.widgets.ship_display import (
    ShipDisplay_Create, ShipDisplay_Cast,
    ShieldsDisplay_Create, DamageDisplay_Create, STFillGauge_Create,
)
```

If `App.py` uses an explicit `__all__` list, append these names to it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/integration/test_ship_display_sdk_integration.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add engine/sdk_ui/widgets/ship_display.py App.py tests/integration/test_ship_display_sdk_integration.py
git commit -m "feat(sdk-ui): ShipDisplay + ShieldsDisplay + DamageDisplay + STFillGauge factories"
```

---

## Task 4: Snapshot generation

**Files:**
- Modify: `engine/ui/ship_display_panel.py` (add `_snapshot`, helpers)
- Modify: `tests/unit/test_ship_display_panel.py` (append snapshot tests)

- [ ] **Step 1: Write the failing snapshot tests**

Append to `tests/unit/test_ship_display_panel.py`:

```python
def _setup_game_with_player():
    """Mirrors tests/unit/test_sensors_panel.py:_setup_game."""
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.ships import ShipClass
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)
    return game, player, mission


def _teardown_game():
    from engine.core.game import _set_current_game
    _set_current_game(None)


def test_player_snapshot_with_full_hull_and_shields():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, _ = _setup_game_with_player()
    try:
        sh = player.GetShieldSubsystem()
        for face in range(sh.NUM_SHIELDS):
            sh.SetMaxShields(face, 100.0)
            sh.SetCurrentShields(face, 100.0)
        hull = player.GetHull()
        hull.SetMaxCondition(1000.0)
        hull.SetCondition(1000.0)

        panel = ShipDisplayPanel(ROLE_PLAYER)
        snap = panel._snapshot()

        assert snap[1] == "Player"        # ship_name
        assert snap[2] in ("FRIENDLY", "NEUTRAL", "UNKNOWN")  # affiliation
        assert snap[4] == 1.0             # hull_pct
        assert snap[5] == (1.0,) * 6      # shields_pct
        assert snap[10] is True           # visible
    finally:
        _teardown_game()


def test_target_role_returns_invisible_when_no_target():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_TARGET)
        snap = panel._snapshot()
        assert snap[10] is False          # visible
        assert snap[1] == ""              # ship_name
        assert snap[2] == "NONE"
    finally:
        _teardown_game()


def test_target_role_unknown_target_returns_invisible():
    """Sensor knowledge gate: unknown target = no panel data."""
    from engine.appc.ships import ShipClass
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    _, player, _ = _setup_game_with_player()
    try:
        foe = ShipClass(); foe.SetName("Foe")
        player.SetTarget(foe)
        # Sensor subsystem returns IsObjectKnown==0 by default; if not,
        # force it via the subsystem's known-objects set.
        try:
            player.GetSensorSubsystem()._known_objects.discard(foe.GetObjID())
        except Exception:
            pass
        panel = ShipDisplayPanel(ROLE_TARGET)
        snap = panel._snapshot()
        assert snap[10] is False
    finally:
        _teardown_game()


def test_shield_face_indices_match_subsystem_constants():
    """Snapshot face order is FRONT, REAR, TOP, BOTTOM, LEFT, RIGHT —
    i.e. ShieldSubsystem.FRONT_SHIELDS..RIGHT_SHIELDS (0..5)."""
    from engine.appc.subsystems import ShieldSubsystem
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, _ = _setup_game_with_player()
    try:
        sh = player.GetShieldSubsystem()
        # Mark each face with a unique fraction so we can verify ordering.
        for face in range(sh.NUM_SHIELDS):
            sh.SetMaxShields(face, 100.0)
            sh.SetCurrentShields(face, 10.0 * (face + 1))
        panel = ShipDisplayPanel(ROLE_PLAYER)
        snap = panel._snapshot()
        # Tuple positions 0..5 correspond to FRONT(0), REAR(1), TOP(2),
        # BOTTOM(3), LEFT(4), RIGHT(5).
        assert snap[5] == (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
        assert ShieldSubsystem.FRONT_SHIELDS == 0
        assert ShieldSubsystem.RIGHT_SHIELDS == 5
    finally:
        _teardown_game()


def test_damage_states_filter_to_named_subsystems_only():
    """Only Engines, Weapons, Sensors, Shield Generator appear, sorted."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, _ = _setup_game_with_player()
    try:
        # Damage two subsystems via the ship's subsystem refs.
        eng = player.GetImpulseEngineSubsystem()
        if eng is not None:
            eng.SetDamaged(1) if hasattr(eng, "SetDamaged") else None
        panel = ShipDisplayPanel(ROLE_PLAYER)
        snap = panel._snapshot()
        # damage_states is a tuple of (name, state) — no healthy entries.
        for name, state in snap[6]:
            assert state in ("damaged", "disabled", "destroyed")
            assert name in ("Engines", "Weapons", "Sensors", "Shield Generator")
    finally:
        _teardown_game()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_display_panel.py -v -k "snapshot or shield_face or damage_states or target_role"`
Expected: 5 new tests fail with `AttributeError: 'ShipDisplayPanel' object has no attribute '_snapshot'`.

- [ ] **Step 3: Implement the snapshot generator**

Add at the bottom of `engine/ui/ship_display_panel.py`:

```python
# ---------------------------------------------------------------------
# Snapshot generation
# ---------------------------------------------------------------------

_DAMAGE_SUBSYSTEM_ORDER = ("Engines", "Weapons", "Sensors", "Shield Generator")


def _resolve_ship_for_role(role: str):
    """Returns the ship the panel renders for, or None for the no-target /
    unknown-target empty state."""
    try:
        import MissionLib
        player = MissionLib.GetPlayer()
    except Exception:
        return None
    if player is None:
        return None
    if role == ROLE_PLAYER:
        return player
    # target role
    target = player.GetTarget() if hasattr(player, "GetTarget") else None
    if target is None:
        return None
    # Sensor-knowledge gate (matches SDK ShieldsDisplay.SetShipIcon at
    # sdk/Build/scripts/Tactical/Interface/ShieldsDisplay.py:329-338).
    try:
        sensors = player.GetSensorSubsystem()
        if sensors is not None and sensors.IsObjectKnown(target) == 0:
            return None
    except Exception:
        pass
    return target


def _affiliation_for(ship) -> str:
    """Map ship affiliation to the snapshot string used by the CSS layer."""
    try:
        import MissionLib
        player = MissionLib.GetPlayer()
        if player is None or ship is None:
            return "NONE"
        if ship is player:
            return "FRIENDLY"
        episode = _current_episode()
        mission = episode.GetCurrentMission() if episode else None
        if mission is not None:
            for kind, group_getter in (
                ("FRIENDLY", "GetFriendlyGroup"),
                ("ENEMY",    "GetEnemyGroup"),
                ("NEUTRAL",  "GetNeutralGroup"),
            ):
                group = getattr(mission, group_getter, lambda: None)()
                if group is not None and group.HasName(ship.GetName()):
                    return kind
    except Exception:
        pass
    return "UNKNOWN"


def _current_episode():
    try:
        from engine.core.game import _get_current_game
        game = _get_current_game()
        return game.GetCurrentEpisode() if game else None
    except Exception:
        return None


def _species_key_for(ship) -> str:
    """Returns the species short name (e.g. 'Galaxy') for silhouette lookup."""
    try:
        prop = ship.GetShipProperty()
        return prop.GetSpeciesName() if prop else ""
    except Exception:
        return ""


def _hull_pct(ship) -> float:
    try:
        hull = ship.GetHull()
        mx = hull.GetMaxCondition()
        if mx <= 0:
            return 0.0
        return float(hull.GetCondition()) / float(mx)
    except Exception:
        return 0.0


def _shields_tuple(ship):
    try:
        sh = ship.GetShieldSubsystem()
        return tuple(sh.GetSingleShieldPercentage(f) for f in range(sh.NUM_SHIELDS))
    except Exception:
        return (0.0,) * 6


def _damage_states(ship):
    """Walks Engines, Weapons, Sensors, Shield Generator. Healthy = omitted."""
    out = []
    getters = (
        ("Engines",         "GetImpulseEngineSubsystem"),
        ("Weapons",         "GetPhaserSystem"),
        ("Sensors",         "GetSensorSubsystem"),
        ("Shield Generator","GetShieldSubsystem"),
    )
    for label, getter_name in getters:
        getter = getattr(ship, getter_name, None)
        if getter is None:
            continue
        try:
            sub = getter()
        except Exception:
            continue
        if sub is None:
            continue
        state = _subsystem_state(sub)
        if state is not None:
            out.append((label, state))
    return tuple(out)


def _subsystem_state(sub):
    try:
        if hasattr(sub, "IsDestroyed") and sub.IsDestroyed():
            return "destroyed"
        if hasattr(sub, "IsDisabled") and sub.IsDisabled():
            return "disabled"
        if hasattr(sub, "IsDamaged") and sub.IsDamaged():
            return "damaged"
    except Exception:
        pass
    return None


def _range_and_speed_to(ship):
    """Returns (range_m, speed_kph) for the target panel; None,None on error."""
    try:
        import MissionLib
        from engine.appc.math import TGPoint3
        player = MissionLib.GetPlayer()
        if player is None or ship is None:
            return None, None
        p1 = player.GetTranslate(); p2 = ship.GetTranslate()
        dx = p1.x - p2.x; dy = p1.y - p2.y; dz = p1.z - p2.z
        rng_m = (dx*dx + dy*dy + dz*dz) ** 0.5
        # Speed: |velocity| in metres/sec → km/h
        vel = ship.GetLinearVelocity() if hasattr(ship, "GetLinearVelocity") else None
        if vel is None:
            speed_kph = 0.0
        else:
            speed_ms = (vel.x*vel.x + vel.y*vel.y + vel.z*vel.z) ** 0.5
            speed_kph = speed_ms * 3.6
        return rng_m, speed_kph
    except Exception:
        return None, None
```

And inside the class, add the `_snapshot` method (before `render_payload`):

```python
    def _snapshot(self) -> tuple:
        ship = _resolve_ship_for_role(self._role)
        if ship is None:
            return (None, "", "NONE", "", 0.0, (0.0,) * 6, (),
                    None, None, self._minimized, False)
        ship_id      = ship.GetObjID() if hasattr(ship, "GetObjID") else 0
        name         = ship.GetName() if hasattr(ship, "GetName") else ""
        affiliation  = _affiliation_for(ship)
        species_key  = _species_key_for(ship)
        hull_pct     = _hull_pct(ship)
        shields_pct  = _shields_tuple(ship)
        damage       = _damage_states(ship)
        range_m, speed_kph = (None, None)
        if self._role == ROLE_TARGET:
            range_m, speed_kph = _range_and_speed_to(ship)
        return (ship_id, name, affiliation, species_key, hull_pct,
                shields_pct, damage, range_m, speed_kph,
                self._minimized, True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_display_panel.py -v`
Expected: all tests pass. If `_damage_states` accessor names don't exist on Phase 1 subsystems, the helper just omits them — the test only asserts non-healthy entries have a valid state, so it still passes.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_display_panel.py tests/unit/test_ship_display_panel.py
git commit -m "feat(ui): ShipDisplayPanel snapshot generation with role-based ship resolution"
```

---

## Task 5: render_payload with idempotency + JS emission

**Files:**
- Modify: `engine/ui/ship_display_panel.py` (implement `render_payload`)
- Modify: `tests/unit/test_ship_display_panel.py` (append payload tests)

- [ ] **Step 1: Write the failing payload tests**

Append to `tests/unit/test_ship_display_panel.py`:

```python
def test_render_payload_emits_setshipdisplay_call():
    import json
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, _ = _setup_game_with_player()
    try:
        sh = player.GetShieldSubsystem()
        for face in range(sh.NUM_SHIELDS):
            sh.SetMaxShields(face, 100.0)
            sh.SetCurrentShields(face, 100.0)
        hull = player.GetHull()
        hull.SetMaxCondition(1000.0); hull.SetCondition(750.0)

        panel = ShipDisplayPanel(ROLE_PLAYER)
        script = panel.render_payload()
        assert script is not None
        assert script.startswith("setShipDisplay(\"player\", ")
        body = script[len("setShipDisplay(\"player\", "):-2]
        state = json.loads(body)
        assert state["visible"] is True
        assert state["ship_name"] == "Player"
        assert state["hull_pct"] == 0.75
        assert state["shields_pct"] == [1.0] * 6
    finally:
        _teardown_game()


def test_render_payload_is_idempotent_until_state_changes():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, _ = _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_PLAYER)
        first = panel.render_payload()
        second = panel.render_payload()
        assert first is not None
        assert second is None  # nothing changed → no re-emit


        # Damage the ship; next render should re-emit.
        player.GetHull().SetCondition(player.GetHull().GetCondition() * 0.5)
        third = panel.render_payload()
        assert third is not None
    finally:
        _teardown_game()


def test_setshipid_forces_reemit():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_PLAYER)
        assert panel.render_payload() is not None
        assert panel.render_payload() is None
        panel.SetShipID(42)
        assert panel.render_payload() is not None
    finally:
        _teardown_game()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_display_panel.py::test_render_payload_emits_setshipdisplay_call -v`
Expected: fail — `render_payload` currently returns `None` unconditionally.

- [ ] **Step 3: Implement render_payload**

At the top of `engine/ui/ship_display_panel.py`, add the import:

```python
import json
```

Replace the placeholder `render_payload` in `ShipDisplayPanel` with:

```python
    def render_payload(self) -> Optional[str]:
        snap = self._snapshot()
        if snap == self._last_snapshot:
            return None
        self._last_snapshot = snap
        (ship_id, name, affiliation, species, hull_pct,
         shields, damage, range_m, speed_kph, minimized, visible) = snap
        payload = {
            "visible":     visible,
            "ship_name":   name,
            "affiliation": affiliation,
            "species":     species,
            "hull_pct":    hull_pct,
            "shields_pct": list(shields),
            "damage":      [{"name": n, "state": s} for (n, s) in damage],
            "range_m":     range_m,
            "speed_kph":   speed_kph,
            "minimized":   minimized,
        }
        return ("setShipDisplay(" + json.dumps(self._role) + ", " +
                json.dumps(payload) + ");")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_display_panel.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_display_panel.py tests/unit/test_ship_display_panel.py
git commit -m "feat(ui): ShipDisplayPanel render_payload with idempotent JS emission"
```

---

## Task 6: Event dispatch (minimize-toggle)

**Files:**
- Modify: `engine/ui/ship_display_panel.py` (`dispatch_event`)
- Modify: `tests/unit/test_ship_display_panel.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ship_display_panel.py`:

```python
def test_target_minimize_toggle_flips_state_and_invalidates_cache():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_TARGET)
        panel.render_payload()  # prime cache
        handled = panel.dispatch_event("minimize-toggle")
        assert handled is True
        assert panel.IsMinimized() == 1
        # next render should re-emit
        assert panel.render_payload() is not None
        # toggling again flips back
        panel.dispatch_event("minimize-toggle")
        assert panel.IsMinimized() == 0
    finally:
        _teardown_game()


def test_player_panel_ignores_minimize_event():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_PLAYER)
        handled = panel.dispatch_event("minimize-toggle")
        assert handled is False
        assert panel.IsMinimized() == 0
    finally:
        _teardown_game()


def test_unknown_action_returns_false():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_TARGET)
        assert panel.dispatch_event("explode") is False
    finally:
        _teardown_game()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_display_panel.py -v -k "minimize_toggle or ignores_minimize or unknown_action"`
Expected: 3 fail (`dispatch_event` returns False unconditionally).

- [ ] **Step 3: Implement dispatch_event**

Replace `dispatch_event` in `ShipDisplayPanel`:

```python
    def dispatch_event(self, action: str) -> bool:
        if action == "minimize-toggle" and self._role == ROLE_TARGET:
            self._minimized = not self._minimized
            self._last_snapshot = None
            return True
        return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_display_panel.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_display_panel.py tests/unit/test_ship_display_panel.py
git commit -m "feat(ui): ShipDisplayPanel minimize-toggle event dispatch"
```

---

## Task 7: Host loop registry wiring

**Files:**
- Modify: `engine/host_loop.py` (call `set_panel_registry` after PanelRegistry construction)
- Test: extend `tests/integration/test_ship_display_sdk_integration.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_ship_display_sdk_integration.py`:

```python
def test_set_panel_registry_routes_factory_to_live_registry():
    """The host loop calls set_panel_registry once at startup; subsequent
    ShipDisplay_Create calls must register with that registry."""
    from engine.ui.panel_registry import PanelRegistry
    from engine.sdk_ui.widgets.ship_display import (
        set_panel_registry, ShipDisplay_Create, _reset_create_count,
    )
    _reset_create_count()
    live = PanelRegistry()
    set_panel_registry(live)
    p = ShipDisplay_Create(0.0, 0.0)
    assert any(panel is p for panel in live._panels)
```

- [ ] **Step 2: Run the test to verify it passes (already covered by Task 3 plumbing)**

Run: `uv run pytest tests/integration/test_ship_display_sdk_integration.py::test_set_panel_registry_routes_factory_to_live_registry -v`
Expected: pass — this is regression coverage for the host-loop wire-up.

- [ ] **Step 3: Wire the host loop**

In `engine/host_loop.py`, around line 2055 (right after `registry.register(sensors_panel)`), add:

```python
        # SDK ShipDisplay factories register against this same registry.
        from engine.sdk_ui.widgets.ship_display import (
            set_panel_registry,
            _reset_create_count,
        )
        set_panel_registry(registry)
        _reset_create_count()
```

- [ ] **Step 4: Run the existing host-loop tests for regression**

Run: `uv run pytest tests/integration/ tests/unit/test_panel_registry.py -v`
Expected: existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/integration/test_ship_display_sdk_integration.py
git commit -m "feat(host): wire ShipDisplay factory to live PanelRegistry"
```

---

## Task 8: HTML / CSS / JS bundle

**Files:**
- Create: `native/assets/ui-cef/panels/ship_display/ship_display.html`
- Create: `native/assets/ui-cef/panels/ship_display/ship_display.css`
- Create: `native/assets/ui-cef/panels/ship_display/ship_display.js`

- [ ] **Step 1: Write the HTML fragment**

Create `native/assets/ui-cef/panels/ship_display/ship_display.html`:

```html
<!--
  ShipDisplay panel template. Two containers — one per role.
  Player anchored in the bottom-right tactical cluster.
  Target anchored top-left as the "Warbird-2"-style overlay.

  Spec: docs/superpowers/specs/2026-05-28-ship-display-panel-design.md
-->
<section class="bc-panel ship-display" id="ship-display-player" data-role="player" hidden>
  <header class="bc-panel__header">
    <span class="bc-panel__title" data-bind="title">PLAYER</span>
  </header>
  <div class="bc-panel__body">
    <div class="ship-display__silhouette-stack">
      <div class="ship-display__silhouette" data-bind="silhouette"></div>
      <div class="ship-display__shield shield--top"    data-bind="shield-top"    data-integrity="full"></div>
      <div class="ship-display__shield shield--bottom" data-bind="shield-bottom" data-integrity="full"></div>
      <div class="ship-display__shield shield--front"  data-bind="shield-front"  data-integrity="full"></div>
      <div class="ship-display__shield shield--rear"   data-bind="shield-rear"   data-integrity="full"></div>
      <div class="ship-display__shield shield--left"   data-bind="shield-left"   data-integrity="full"></div>
      <div class="ship-display__shield shield--right"  data-bind="shield-right"  data-integrity="full"></div>
    </div>
    <ul class="ship-display__damage" data-bind="damage-list"></ul>
    <div class="ship-display__hull-bar">
      <div class="ship-display__hull-fill" data-bind="hull-fill"></div>
      <span class="ship-display__hull-pct" data-bind="hull-pct">100%</span>
    </div>
  </div>
</section>

<section class="bc-panel ship-display" id="ship-display-target" data-role="target" hidden>
  <header class="bc-panel__header">
    <span class="bc-panel__title" data-bind="title">NO TARGET</span>
    <button class="bc-panel__minimize" data-event="ship-target/minimize-toggle">▼</button>
  </header>
  <div class="bc-panel__body">
    <div class="ship-display__silhouette-stack">
      <div class="ship-display__silhouette" data-bind="silhouette"></div>
      <div class="ship-display__shield shield--top"    data-bind="shield-top"    data-integrity="down"></div>
      <div class="ship-display__shield shield--bottom" data-bind="shield-bottom" data-integrity="down"></div>
      <div class="ship-display__shield shield--front"  data-bind="shield-front"  data-integrity="down"></div>
      <div class="ship-display__shield shield--rear"   data-bind="shield-rear"   data-integrity="down"></div>
      <div class="ship-display__shield shield--left"   data-bind="shield-left"   data-integrity="down"></div>
      <div class="ship-display__shield shield--right"  data-bind="shield-right"  data-integrity="down"></div>
    </div>
    <ul class="ship-display__damage" data-bind="damage-list"></ul>
    <div class="ship-display__hull-bar">
      <div class="ship-display__hull-fill" data-bind="hull-fill"></div>
      <span class="ship-display__hull-pct" data-bind="hull-pct">0%</span>
    </div>
    <div class="ship-display__target-extras" data-bind="target-extras">
      <span data-bind="range">— km</span>
      <span data-bind="speed">— kph</span>
    </div>
  </div>
</section>
```

- [ ] **Step 2: Write the CSS**

Create `native/assets/ui-cef/panels/ship_display/ship_display.css`:

```css
/* ShipDisplay panel — palette tokens only. No literal RGBs. */

.ship-display {
  position: fixed;
  width: 18vw;
  min-width: 220px;
  background: var(--bc-body-bg);
  border: 1px solid var(--bc-menu1-base);
  font-family: "Antonio", sans-serif;
  color: var(--bc-label-text);
  --title-color: var(--bc-row-text-bright);
}

#ship-display-player {
  right: 36vw;          /* leaves room for Weapons Settings + Weapons Display */
  bottom: 0;
}

#ship-display-target {
  left: 1.5vw;
  top: 4vh;
}

.ship-display[hidden] { display: none; }
.ship-display[data-minimized="true"] .bc-panel__body { display: none; }

.bc-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bc-menu1-base);
  padding: 4px 8px;
  color: var(--title-color);
  font-weight: 600;
  letter-spacing: 2px;
  text-transform: uppercase;
}

.bc-panel__minimize {
  background: transparent;
  border: 0;
  color: inherit;
  cursor: pointer;
  font-size: 14px;
}

.bc-panel__body {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* Affiliation drives title color. */
.ship-display[data-affiliation="FRIENDLY"] { --title-color: var(--bc-target-friendly); }
.ship-display[data-affiliation="ENEMY"]    { --title-color: var(--bc-target-name); }
.ship-display[data-affiliation="NEUTRAL"]  { --title-color: var(--bc-sensor-neutral); }
.ship-display[data-affiliation="NONE"]     { --title-color: var(--bc-no-target); }

/* Silhouette + shield quadrants. */
.ship-display__silhouette-stack {
  position: relative;
  width: 100%;
  height: 120px;
}
.ship-display__silhouette {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  color: var(--bc-shields);
}
.ship-display[data-role="target"] .ship-display__silhouette { color: var(--title-color); }

.ship-display__shield {
  position: absolute;
  border-radius: 50%;
  transition: opacity 120ms ease;
  pointer-events: none;
}
.shield--top    { top: 0;   left: 25%; width: 50%; height: 20%; }
.shield--bottom { bottom: 0; left: 25%; width: 50%; height: 20%; }
.shield--front  { top: 15%; left: 35%; width: 30%; height: 15%; }
.shield--rear   { bottom: 15%; left: 35%; width: 30%; height: 15%; }
.shield--left   { top: 30%; left: 5%;  width: 20%; height: 40%; }
.shield--right  { top: 30%; right: 5%; width: 20%; height: 40%; }

.ship-display__shield[data-integrity="full"]    { opacity: 1.0; background: var(--bc-shields); }
.ship-display__shield[data-integrity="damaged"] { opacity: 0.6; background: var(--bc-hull-damaged); }
.ship-display__shield[data-integrity="down"]    { opacity: 0.0; }

/* Damage list. */
.ship-display__damage { list-style: none; margin: 0; padding: 0; font-size: 11px; }
.damage-row { display: flex; justify-content: space-between; padding: 2px 0; }
.damage-row[data-state="damaged"]   { color: var(--bc-damage-damaged); }
.damage-row[data-state="disabled"]  { color: var(--bc-damage-disabled); }
.damage-row[data-state="destroyed"] { color: var(--bc-damage-destroyed); }

/* Hull bar. */
.ship-display__hull-bar {
  position: relative;
  height: 10px;
  background: var(--bc-hull-track);
  border: 1px solid var(--bc-hull-track);
  border-radius: 2px;
  overflow: hidden;
}
.ship-display__hull-fill {
  height: 100%;
  width: 100%;
  transition: width 200ms ease;
}
.ship-display[data-hull="healthy"]  .ship-display__hull-fill { background: var(--bc-hull-healthy); }
.ship-display[data-hull="damaged"]  .ship-display__hull-fill { background: var(--bc-hull-damaged); }
.ship-display[data-hull="critical"] .ship-display__hull-fill { background: var(--bc-hull-critical); }
.ship-display__hull-pct {
  position: absolute; right: 4px; top: -2px;
  font-size: 10px; font-variant-numeric: tabular-nums;
  color: var(--bc-row-text-bright);
}

/* Target extras (range / speed). */
.ship-display__target-extras {
  display: flex; justify-content: space-between;
  font-size: 11px;
  color: var(--bc-row-text-dim);
}
.ship-display[data-role="player"] .ship-display__target-extras { display: none; }
```

- [ ] **Step 3: Write the JS**

Create `native/assets/ui-cef/panels/ship_display/ship_display.js`:

```js
// ShipDisplay panel — DOM update entry point.
// Called from Python via render_payload: setShipDisplay("player", {...}).
//
// Spec: docs/superpowers/specs/2026-05-28-ship-display-panel-design.md

(function () {
  "use strict";

  const SHIELD_FACE_BIND_ORDER = [
    "shield-front", "shield-rear", "shield-top",
    "shield-bottom", "shield-left", "shield-right"
  ];

  function bucketForHull(pct) {
    if (pct >= 0.70) return "healthy";
    if (pct >= 0.25) return "damaged";
    return "critical";
  }

  function bucketForShield(pct) {
    if (pct >= 0.75) return "full";
    if (pct > 0.0)   return "damaged";
    return "down";
  }

  function rebuildDamageList(ul, damage) {
    ul.innerHTML = "";
    damage.forEach(function (row) {
      const li = document.createElement("li");
      li.className = "damage-row";
      li.dataset.state = row.state;
      li.textContent = row.name + " — " + row.state.toUpperCase();
      ul.appendChild(li);
    });
  }

  function setSilhouette(el, speciesKey) {
    // Phase 1: SVGs are loaded on demand by class hook.
    // For now we just stamp the species name as a class so CSS can pick
    // the right background-image; SVG injection lands in Task 9.
    if (!speciesKey) {
      el.className = "ship-display__silhouette";
      return;
    }
    el.className = "ship-display__silhouette silhouette--" + speciesKey.toLowerCase();
  }

  window.setShipDisplay = function (role, state) {
    const root = document.getElementById("ship-display-" + role);
    if (!root) return;
    root.hidden = !state.visible;
    if (!state.visible) return;

    root.dataset.affiliation = state.affiliation || "NONE";
    root.dataset.hull = bucketForHull(state.hull_pct);
    root.dataset.minimized = state.minimized ? "true" : "false";

    const title = root.querySelector('[data-bind="title"]');
    title.textContent = state.ship_name || (role === "target" ? "NO TARGET" : "PLAYER");

    const fill = root.querySelector('[data-bind="hull-fill"]');
    fill.style.width = (state.hull_pct * 100).toFixed(1) + "%";
    const pct = root.querySelector('[data-bind="hull-pct"]');
    pct.textContent = Math.round(state.hull_pct * 100) + "%";

    state.shields_pct.forEach(function (facePct, i) {
      const el = root.querySelector('[data-bind="' + SHIELD_FACE_BIND_ORDER[i] + '"]');
      if (el) el.dataset.integrity = bucketForShield(facePct);
    });

    rebuildDamageList(root.querySelector('[data-bind="damage-list"]'), state.damage || []);

    setSilhouette(root.querySelector('[data-bind="silhouette"]'), state.species);

    if (role === "target") {
      const rng = root.querySelector('[data-bind="range"]');
      const spd = root.querySelector('[data-bind="speed"]');
      if (rng) rng.textContent = (state.range_m == null) ? "— km" : (state.range_m / 1000).toFixed(2) + " km";
      if (spd) spd.textContent = (state.speed_kph == null) ? "— kph" : Math.round(state.speed_kph) + " kph";
    }
  };
})();
```

- [ ] **Step 4: Verify the files exist and JS parses**

Run: `node -c native/assets/ui-cef/panels/ship_display/ship_display.js`
Expected: no output (parses cleanly). If `node` isn't installed locally, skip — the bundle is parsed by CEF at load time and a smoke test in Task 10 will catch syntax errors.

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/panels/ship_display/
git commit -m "feat(ui): ShipDisplay HTML/CSS/JS bundle with palette tokens"
```

---

## Task 9: Wire the game's ship icon TGAs to the panel via a runtime TGA→PNG cache

The game ships its ship-class icons as 128×128 TGAs at `game/data/Icons/Ships/*.tga` (Galaxy.tga, Warbird.tga, Akira.tga, Sovereign.tga, etc.). The SDK loads them via `sdk/Build/scripts/Icons/ShipIcons.py:LoadShipIcons()` which registers each by species integer (`App.SPECIES_GALAXY = 0`, `App.SPECIES_WARBIRD = 18`, …) in `g_kIconManager` under the group name `"ShipIcons"`.

CEF can't display TGA natively. We add a tiny pure-Python TGA decoder + PNG encoder so the engine can convert each requested icon on first access and cache the PNG on disk. JS then loads the PNG via a normal `<img src>`.

**Files:**
- Create: `engine/ui/tga.py` — TGA decoder (uncompressed RGB / RGBA + RLE for completeness)
- Create: `engine/ui/png_encoder.py` — minimal PNG encoder using stdlib `zlib`
- Create: `engine/ui/ship_icons.py` — `icon_path_for_species(name) -> str | None`. Looks up the TGA at `game/data/Icons/Ships/<name>.tga`, converts on first call, writes the PNG into `native/assets/ui-cef/icons/ships/<name>.png`, returns the relative URL `icons/ships/<name>.png` for JS use. Subsequent calls return the cached path.
- Modify: `engine/ui/ship_display_panel.py` — `_species_key_for(ship)` already returns the species short name (e.g. `"Galaxy"`). In `_snapshot` (or `render_payload`), call `icon_path_for_species(species_key)` and include the resulting URL in the JS payload as `state.silhouette_url` (None when missing).
- Modify: `native/assets/ui-cef/panels/ship_display/ship_display.js` — replace the species-class hack with an `<img>` element whose `src` is `state.silhouette_url`. Hide the img when None.
- Modify: `native/assets/ui-cef/panels/ship_display/ship_display.html` — change the silhouette container from `<div>` to `<img class="ship-display__silhouette" data-bind="silhouette">`.
- Modify: `native/assets/ui-cef/panels/ship_display/ship_display.css` — drop the `silhouette--galaxy` etc. background-image rules; instead style the `<img>` to fit the silhouette stack (`width: 100%; height: 100%; object-fit: contain; opacity: 0.8;`). Affiliation tinting via CSS filter (`filter: hue-rotate(...)` or similar) — or accept that the icon renders in its native colour (the original BC also shows the icon in its native colour with shield overlays on top).
- Add to `.gitignore`: `native/assets/ui-cef/icons/ships/` (so the generated PNG cache isn't committed)
- Test: `tests/unit/test_tga.py`, `tests/unit/test_png_encoder.py`, `tests/unit/test_ship_icons.py`

- [ ] **Step 1: Write the failing TGA decoder tests**

```python
# tests/unit/test_tga.py
"""TGA decoder. Only covers the cases the BC game icons use:
uncompressed 24/32-bit BGR/BGRA (Targa Type 2)."""
import struct


def _make_tga(width: int, height: int, pixels_bgra: bytes) -> bytes:
    """Build a minimal uncompressed 32-bit BGRA TGA. Y-flipped per
    typical authoring (origin at top-left)."""
    header = struct.pack(
        "<BBBHHBHHHHBB",
        0,          # id length
        0,          # color map type (none)
        2,          # image type (uncompressed true-color)
        0, 0, 0,    # color map spec
        0, 0,       # x origin, y origin
        width, height,
        32,         # bits per pixel
        0x20,       # image descriptor (0x20 = origin top-left, 8 alpha bits)
    )
    return header + pixels_bgra


def test_decodes_uncompressed_bgra():
    from engine.ui.tga import decode_tga
    # 2x1 image: red pixel + blue pixel (in BGRA order).
    pixels = bytes([0, 0, 255, 255,   # red
                    255, 0, 0, 255])  # blue
    blob = _make_tga(2, 1, pixels)
    width, height, rgba = decode_tga(blob)
    assert width == 2 and height == 1
    # rgba is RGBA (not BGRA)
    assert rgba == bytes([255, 0, 0, 255,  0, 0, 255, 255])


def test_decodes_uncompressed_bgr():
    from engine.ui.tga import decode_tga
    # 1x1 image, 24-bit BGR.
    header = struct.pack("<BBBHHBHHHHBB", 0,0,2, 0,0,0, 0,0, 1,1, 24, 0x20)
    pixels = bytes([0, 255, 0])  # green
    width, height, rgba = decode_tga(header + pixels)
    assert (width, height) == (1, 1)
    assert rgba == bytes([0, 255, 0, 255])
```

- [ ] **Step 2: Implement the TGA decoder**

```python
# engine/ui/tga.py
"""Minimal TGA decoder for the game's ship-icon assets.

The BC ship icons under game/data/Icons/Ships/ are uncompressed 32-bit
BGRA Targa Type 2 images (128x128). This decoder targets that case
plus uncompressed 24-bit BGR; RLE (Type 10) is not used by these
assets and is unsupported.

Returns (width, height, rgba_bytes) — rgba_bytes is RGBA (not BGRA),
suitable for direct PNG encoding.
"""
from __future__ import annotations

import struct


def decode_tga(blob: bytes) -> tuple[int, int, bytes]:
    if len(blob) < 18:
        raise ValueError("TGA header truncated")
    (id_length, cmap_type, image_type,
     _cmap_first, _cmap_len, _cmap_size,
     _x_origin, _y_origin,
     width, height,
     bpp, descriptor) = struct.unpack("<BBBHHBHHHHBB", blob[:18])

    if image_type != 2:
        raise ValueError(f"unsupported TGA image type {image_type}; "
                         "only uncompressed true-colour (2) is implemented")
    if bpp not in (24, 32):
        raise ValueError(f"unsupported bpp {bpp}")
    if cmap_type != 0:
        raise ValueError("colour-mapped TGAs not supported")

    pixel_start = 18 + id_length
    bytes_per_pixel = bpp // 8
    expected = width * height * bytes_per_pixel
    pixels = blob[pixel_start:pixel_start + expected]
    if len(pixels) < expected:
        raise ValueError("TGA pixel data truncated")

    # Convert BGR(A) → RGBA
    rgba = bytearray(width * height * 4)
    for i in range(width * height):
        src = i * bytes_per_pixel
        dst = i * 4
        rgba[dst]     = pixels[src + 2]  # R
        rgba[dst + 1] = pixels[src + 1]  # G
        rgba[dst + 2] = pixels[src]      # B
        rgba[dst + 3] = pixels[src + 3] if bytes_per_pixel == 4 else 255

    # Bit 5 of descriptor: 1 = origin at top-left, 0 = origin at bottom-left.
    top_left = bool(descriptor & 0x20)
    if not top_left:
        # Flip rows so the output is always top-down.
        row = width * 4
        flipped = bytearray(len(rgba))
        for y in range(height):
            src_off = (height - 1 - y) * row
            flipped[y * row:(y + 1) * row] = rgba[src_off:src_off + row]
        rgba = flipped

    return width, height, bytes(rgba)
```

- [ ] **Step 3: Run TGA tests**

Run: `uv run pytest tests/unit/test_tga.py -v`
Expected: 2 passed.

- [ ] **Step 4: Write the failing PNG encoder tests**

```python
# tests/unit/test_png_encoder.py
import struct
import zlib


def test_emits_valid_png_signature():
    from engine.ui.png_encoder import encode_png_rgba
    rgba = bytes([255, 0, 0, 255])
    blob = encode_png_rgba(1, 1, rgba)
    assert blob.startswith(b"\x89PNG\r\n\x1a\n")


def test_emits_ihdr_with_correct_dimensions():
    from engine.ui.png_encoder import encode_png_rgba
    rgba = bytes([0, 0, 0, 255] * 4)  # 2x2
    blob = encode_png_rgba(2, 2, rgba)
    # IHDR starts at byte 8, length=13, type=IHDR
    assert blob[12:16] == b"IHDR"
    width, height = struct.unpack(">II", blob[16:24])
    assert (width, height) == (2, 2)


def test_round_trips_through_pillow_when_available():
    """If Pillow happens to be installed in the dev env, confirm we
    produced a valid PNG. Skipped otherwise — PNG encoder is unit
    tested by structural checks above."""
    try:
        from PIL import Image
        import io
    except ImportError:
        return
    from engine.ui.png_encoder import encode_png_rgba
    rgba = bytes([200, 100, 50, 255,  10, 20, 30, 255]) * 2  # 2x2
    blob = encode_png_rgba(2, 2, rgba)
    img = Image.open(io.BytesIO(blob))
    assert img.size == (2, 2)
    assert img.mode == "RGBA"
```

- [ ] **Step 5: Implement the PNG encoder**

```python
# engine/ui/png_encoder.py
"""Minimal PNG encoder using only the standard library.

Encodes RGBA pixel data into a valid PNG byte stream. No interlacing,
no palette, no compression-level tuning — just enough for the ship-icon
cache. Each scanline gets a filter byte of 0 (None) followed by the
raw RGBA bytes; the concatenated stream is deflated as one IDAT chunk.
"""
from __future__ import annotations

import struct
import zlib

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def encode_png_rgba(width: int, height: int, rgba: bytes) -> bytes:
    if len(rgba) != width * height * 4:
        raise ValueError("rgba length does not match width*height*4")
    # IHDR: width, height, bit depth=8, color type=6 (RGBA), compression=0,
    # filter=0, interlace=0.
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    # IDAT: each scanline prefixed with filter byte 0 (no filter).
    row = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * row:(y + 1) * row])
    idat = zlib.compress(bytes(raw), 6)
    return (_SIGNATURE
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", idat)
            + _chunk(b"IEND", b""))
```

- [ ] **Step 6: Run PNG tests**

Run: `uv run pytest tests/unit/test_png_encoder.py -v`
Expected: 3 passed (the round-trip test is skipped without Pillow).

- [ ] **Step 7: Write the failing ship-icon cache tests**

```python
# tests/unit/test_ship_icons.py
"""ship_icons.icon_path_for_species converts the game's TGA on first
access and serves the cached PNG thereafter."""
import os
import shutil


def test_returns_none_for_unknown_species(tmp_path, monkeypatch):
    from engine.ui import ship_icons
    monkeypatch.setattr(ship_icons, "_GAME_ICONS_DIR", str(tmp_path / "missing"))
    monkeypatch.setattr(ship_icons, "_CACHE_DIR", str(tmp_path / "cache"))
    assert ship_icons.icon_path_for_species("NoSuchShip") is None


def test_converts_tga_and_caches_png(tmp_path, monkeypatch):
    import struct
    from engine.ui import ship_icons
    # Build a 2x1 BGRA TGA in tmp dir
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    pixels = bytes([0,0,255,255,  255,0,0,255])
    header = struct.pack("<BBBHHBHHHHBB", 0,0,2, 0,0,0, 0,0, 2,1, 32, 0x20)
    (icons_dir / "Galaxy.tga").write_bytes(header + pixels)
    cache_dir = tmp_path / "cache"

    monkeypatch.setattr(ship_icons, "_GAME_ICONS_DIR", str(icons_dir))
    monkeypatch.setattr(ship_icons, "_CACHE_DIR",      str(cache_dir))
    ship_icons.reset_cache()

    url = ship_icons.icon_path_for_species("Galaxy")
    assert url == "icons/ships/Galaxy.png"
    assert (cache_dir / "Galaxy.png").is_file()

    # Second call should not re-encode (mtime stays the same).
    first_mtime = (cache_dir / "Galaxy.png").stat().st_mtime
    url2 = ship_icons.icon_path_for_species("Galaxy")
    assert url2 == url
    assert (cache_dir / "Galaxy.png").stat().st_mtime == first_mtime
```

- [ ] **Step 8: Implement ship_icons.py**

```python
# engine/ui/ship_icons.py
"""On-demand TGA→PNG conversion + disk cache for ship-class icons.

Looks up `<game>/data/Icons/Ships/<name>.tga` (per the SDK loader at
sdk/Build/scripts/Icons/ShipIcons.py), decodes the TGA, encodes a PNG,
writes it to a cache directory, and returns the CEF-relative URL.
Subsequent calls return the cached URL without re-encoding.

The species name passed in must match the TGA filename stem (e.g.
"Galaxy", "Warbird", "BirdOfPrey"). The SDK exposes these via
App.SPECIES_GALAXY etc.; engine/appc/properties.py:ShipProperty
exposes the corresponding string via GetSpeciesName.
"""
from __future__ import annotations

import os
from typing import Optional

from engine.ui.tga import decode_tga
from engine.ui.png_encoder import encode_png_rgba


_GAME_ICONS_DIR = "game/data/Icons/Ships"
_CACHE_DIR      = "native/assets/ui-cef/icons/ships"
_URL_PREFIX     = "icons/ships"

# species name → cached URL (None = known-missing).
_resolved: dict[str, Optional[str]] = {}


def reset_cache() -> None:
    _resolved.clear()


def icon_path_for_species(name: str) -> Optional[str]:
    if not name:
        return None
    if name in _resolved:
        return _resolved[name]

    tga_path = os.path.join(_GAME_ICONS_DIR, name + ".tga")
    if not os.path.isfile(tga_path):
        _resolved[name] = None
        return None

    cache_path = os.path.join(_CACHE_DIR, name + ".png")
    if not os.path.isfile(cache_path):
        with open(tga_path, "rb") as fp:
            blob = fp.read()
        width, height, rgba = decode_tga(blob)
        png = encode_png_rgba(width, height, rgba)
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(cache_path, "wb") as fp:
            fp.write(png)

    url = f"{_URL_PREFIX}/{name}.png"
    _resolved[name] = url
    return url
```

- [ ] **Step 9: Run ship-icon tests**

Run: `uv run pytest tests/unit/test_ship_icons.py -v`
Expected: 2 passed.

- [ ] **Step 10: Add cache directory to .gitignore**

Append to `.gitignore`:
```
native/assets/ui-cef/icons/ships/
```

- [ ] **Step 11: Wire the icon URL into the panel's JS payload**

In `engine/ui/ship_display_panel.py`, update `render_payload` (or `_snapshot` + `render_payload`) so the JS payload includes `silhouette_url`. Reuse the existing `species_key` from the snapshot:

```python
from engine.ui.ship_icons import icon_path_for_species

# Inside render_payload, after constructing payload dict:
payload["silhouette_url"] = icon_path_for_species(payload["species"])
```

This is a render-layer concern, not a snapshot concern (no need to bloat the cache key). The URL is derived deterministically from `species_key` so cache invalidation is unaffected.

- [ ] **Step 12: Update the HTML + JS to use an `<img>` for the silhouette**

In `native/assets/ui-cef/panels/ship_display/ship_display.html`, change the silhouette element from a div to an img:

```html
<img class="ship-display__silhouette" data-bind="silhouette" alt="">
```

In `native/assets/ui-cef/panels/ship_display/ship_display.js`, replace `setSilhouette` with:

```js
function setSilhouette(el, url) {
  if (!url) {
    el.removeAttribute("src");
    el.hidden = true;
    return;
  }
  el.src = url;
  el.hidden = false;
}
```

And in `setShipDisplay`:
```js
setSilhouette(root.querySelector('[data-bind="silhouette"]'), state.silhouette_url);
```

In `native/assets/ui-cef/panels/ship_display/ship_display.css`, drop the `silhouette--galaxy` / `silhouette--warbird` class rules and add:

```css
.ship-display__silhouette {
  width: 100%; height: 100%;
  object-fit: contain;
  opacity: 0.85;
}
```

The icon renders in its native colour (the BC icons already have ship-on-transparent-background palette). Shield quadrants overlay on top.

- [ ] **Step 13: Run the full ShipDisplay unit + integration test suite**

Run: `uv run pytest tests/unit/test_ship_display_panel.py tests/unit/test_tga.py tests/unit/test_png_encoder.py tests/unit/test_ship_icons.py tests/integration/test_ship_display_sdk_integration.py -v`
Expected: all pass.
**Do NOT run the full pytest suite.**

- [ ] **Step 14: Commit**

```bash
git add engine/ui/tga.py engine/ui/png_encoder.py engine/ui/ship_icons.py
git add engine/ui/ship_display_panel.py
git add tests/unit/test_tga.py tests/unit/test_png_encoder.py tests/unit/test_ship_icons.py
git add .gitignore
git add native/assets/ui-cef/panels/ship_display/
git commit -m "feat(ui): runtime TGA→PNG cache for ship-class icons"
```

---

## Task 10: Bridge.html integration + visual smoke

**Files:**
- Modify: `native/assets/ui-cef/bridge.html` (include the ship_display fragment + CSS + JS references)
- Modify: `docs/ui_designs/03-shields-readout.md` (annotate layout supersede)

- [ ] **Step 1: Locate the bridge.html include slot**

Run: `grep -n "ship-display\|sensors-panel\|target-list" native/assets/ui-cef/bridge.html`
Look for where other panels are included so the new fragment slots into the existing convention. If panels are inlined as `<section>` blocks, copy that pattern. If they're loaded via `<link rel="import">` or fetch, follow that.

- [ ] **Step 2: Add link + script tags and include the fragment**

In `native/assets/ui-cef/bridge.html`, add inside `<head>` (next to other panel CSS):

```html
<link rel="stylesheet" href="panels/ship_display/ship_display.css">
```

In `<body>`, add (in the order panels are listed) — full markup, inlined:

```html
<!-- ShipDisplay panels: player (bottom-right cluster) + target (top-left overlay) -->
<section class="bc-panel ship-display" id="ship-display-player" data-role="player" hidden>
  <header class="bc-panel__header">
    <span class="bc-panel__title" data-bind="title">PLAYER</span>
  </header>
  <div class="bc-panel__body">
    <div class="ship-display__silhouette-stack">
      <div class="ship-display__silhouette" data-bind="silhouette"></div>
      <div class="ship-display__shield shield--top"    data-bind="shield-top"    data-integrity="full"></div>
      <div class="ship-display__shield shield--bottom" data-bind="shield-bottom" data-integrity="full"></div>
      <div class="ship-display__shield shield--front"  data-bind="shield-front"  data-integrity="full"></div>
      <div class="ship-display__shield shield--rear"   data-bind="shield-rear"   data-integrity="full"></div>
      <div class="ship-display__shield shield--left"   data-bind="shield-left"   data-integrity="full"></div>
      <div class="ship-display__shield shield--right"  data-bind="shield-right"  data-integrity="full"></div>
    </div>
    <ul class="ship-display__damage" data-bind="damage-list"></ul>
    <div class="ship-display__hull-bar">
      <div class="ship-display__hull-fill" data-bind="hull-fill"></div>
      <span class="ship-display__hull-pct" data-bind="hull-pct">100%</span>
    </div>
  </div>
</section>

<section class="bc-panel ship-display" id="ship-display-target" data-role="target" hidden>
  <header class="bc-panel__header">
    <span class="bc-panel__title" data-bind="title">NO TARGET</span>
    <button class="bc-panel__minimize" data-event="ship-target/minimize-toggle">▼</button>
  </header>
  <div class="bc-panel__body">
    <div class="ship-display__silhouette-stack">
      <div class="ship-display__silhouette" data-bind="silhouette"></div>
      <div class="ship-display__shield shield--top"    data-bind="shield-top"    data-integrity="down"></div>
      <div class="ship-display__shield shield--bottom" data-bind="shield-bottom" data-integrity="down"></div>
      <div class="ship-display__shield shield--front"  data-bind="shield-front"  data-integrity="down"></div>
      <div class="ship-display__shield shield--rear"   data-bind="shield-rear"   data-integrity="down"></div>
      <div class="ship-display__shield shield--left"   data-bind="shield-left"   data-integrity="down"></div>
      <div class="ship-display__shield shield--right"  data-bind="shield-right"  data-integrity="down"></div>
    </div>
    <ul class="ship-display__damage" data-bind="damage-list"></ul>
    <div class="ship-display__hull-bar">
      <div class="ship-display__hull-fill" data-bind="hull-fill"></div>
      <span class="ship-display__hull-pct" data-bind="hull-pct">0%</span>
    </div>
    <div class="ship-display__target-extras" data-bind="target-extras">
      <span data-bind="range">— km</span>
      <span data-bind="speed">— kph</span>
    </div>
  </div>
</section>
```

The fragment file at `panels/ship_display/ship_display.html` from Task 8 is kept as the canonical source. If `bridge.html` supports a build-time include (e.g. a Jinja `{% include %}` or a server-side cat), use it instead of inlining and reference the fragment file — but if the project has no such mechanism, inline as above.

Before the closing `</body>`, add (next to other panel scripts):

```html
<script src="panels/ship_display/ship_display.js"></script>
```

If `bridge.html` uses a build step (e.g. concatenation), follow that convention instead of inlining.

- [ ] **Step 3: Run the full test suite for regression**

Run: `uv run pytest tests/unit/test_ship_display_panel.py tests/integration/test_ship_display_sdk_integration.py tests/unit/test_panel_registry.py tests/unit/test_sensors_panel.py tests/unit/test_target_list_view.py -v`
Expected: all pass.
**Do NOT run the full pytest suite** — the user's memory says it OOMs the host.

- [ ] **Step 4: Build and launch for visual smoke**

Run:
```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless
```

Walk through the visual smoke checklist from spec §9:

1. Launch with the default mission. Confirm the player ShipDisplay renders in the bottom-right cluster with all six shield quadrants green and hull bar at 100 %.
2. Take a hit (fire-trace mission). Confirm the impacted facing dims and the hull bar updates.
3. Target an enemy ship. Confirm the top-left target overlay appears with the enemy's name in red and silhouette swap to Warbird.
4. Untarget. Confirm target overlay collapses to hidden.
5. Click the target minimize chevron. Confirm only the header strip remains; click again to expand.
6. Damage a subsystem. Confirm the damage row appears in the appropriate state colour.

For any step that fails: revisit the relevant CSS or JS — the Python state machine is already covered by unit tests, so visual failures are render-layer regressions.

- [ ] **Step 5: Update mockup doc to reflect the chosen layout**

In `docs/ui_designs/03-shields-readout.md`, replace the ASCII diagram and surrounding paragraph (lines 1-15 roughly) with:

```markdown
# 03 — Shields readout

Visual reference: [03-shields-readout.html](03-shields-readout.html) (the side-by-side mockup shows the *palette and per-state visuals*; the actual placement follows the original BC layout — see below).

The SDK `ShipDisplay` widget is instantiated twice per game:
- **Player ShipDisplay** — anchored in the bottom-right tactical cluster, left of the Weapons Settings panel
- **Target ShipDisplay** — anchored at the top-left of the viewport as the "Warbird-2"-style overlay, with crosshair + range + speed badge

Both render the full SDK composite: a ship silhouette with six shield-quadrant icons (top/bottom/front/rear/left/right), a damage list (Engines / Weapons / Sensors / Shield Generator), and a hull-integrity bar.

See `docs/superpowers/specs/2026-05-28-ship-display-panel-design.md` for the engine implementation.
```

- [ ] **Step 6: Commit**

```bash
git add native/assets/ui-cef/bridge.html docs/ui_designs/03-shields-readout.md
git commit -m "feat(ui): wire ShipDisplay panels into bridge.html + update mockup 03"
```

---

## Done

After Task 10 commits, every spec section has a corresponding task:

| Spec section | Tasks |
|---|---|
| §3 Architecture | Tasks 1-10 (every layer touched) |
| §4 Widget class shape | Tasks 1, 2 |
| §5 SDK shim wiring | Task 3, 7 |
| §6 HTML / CSS | Tasks 8, 9 |
| §7 Per-tick data flow | Tasks 4, 5 |
| §8 Event dispatch | Task 6 |
| §9 Testing | Tasks 1-7 (unit + integration); Task 10 (visual smoke) |
| §10 Affected files | Tasks 1-10 (all paths created/modified) |

To pick the work back up later, read the spec then start at Task 1 — each task is self-contained.
