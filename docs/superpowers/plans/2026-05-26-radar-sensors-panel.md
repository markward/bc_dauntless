# Radar / Sensors Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the bottom-left Sensors / radar panel of the tactical UI from the design spec at [docs/ui_designs/05-sensors-radar.md](../../ui_designs/05-sensors-radar.md) — a perspective-tilted disc with range rings, blip triangles rotated to heading, vertical stems for altitude, and a gold corner bracket on the targeted contact. The disc itself is engine-driven; the SDK Python surface (`App.RadarDisplay_Create` etc.) is preserved so original BC scripts (`LoadBridge.py` → `Bridge/TacticalMenuHandlers.py:471-476`) keep running unchanged.

**Architecture:**
- **SDK shim layer** — `_RadarDisplay`, `_RadarScope`, `_RadarBlip` Python classes mirroring [sdk/Build/scripts/App.py:8513-8552](../../../sdk/Build/scripts/App.py) so `TacticalMenuHandlers.CreateRadarDisplay` runs without error. The shim does no rendering; it accepts the SDK calls and stores the parameters scripts might later query.
- **View layer** — `SensorsPanel` (subclass of `engine.ui.panel.Panel`) walks the player's spatial set each tick, projects ships onto a player-relative disc plane, and emits a `setRadar({range_m, contacts})` JS call. Idempotent — only re-emits when the snapshot changes (same pattern as [engine/ui/target_list_view.py](../../../engine/ui/target_list_view.py)).
- **Renderer layer** — Static HTML/CSS for panel chrome + perspective disc + range rings. JS `setRadar(state)` rebuilds the contacts overlay only (triangles, stems, brackets). Off-disc contacts are filtered out Python-side and never sent.
- **Wiring** — `host_loop.py` registers the new panel next to `TargetListView` and gates visibility on `view_mode.is_exterior` (SPACE-bar toggle), matching the target list. v1 ships only — torpedoes/projectiles are explicit follow-up work.

**Tech Stack:** Python 3.13, pytest, CEF/Chromium (HTML+CSS+JS), CMake (no native code changes — the existing CEF binding handles JS evaluation).

---

## File Structure

```
App.py                                         [modify — re-export radar factories]
engine/appc/radar.py                           [create — SDK shim classes]
engine/appc/windows.py                         [modify — TCW.SetRadarDisplay/GetRadarDisplay]
engine/ui/sensors_panel.py                     [create — Panel subclass]
engine/ui/radar_projection.py                  [create — pure projection math]
engine/host_loop.py                            [modify — register + visibility gating]
native/assets/ui-cef/hello.html                [modify — add #sensors-panel block]
native/assets/ui-cef/css/sensors.css           [create — disc + rings + blip styles]
native/assets/ui-cef/js/sensors.js             [create — setRadar(state) renderer]

tests/unit/test_radar_display_shim.py          [create]
tests/unit/test_radar_projection.py            [create]
tests/unit/test_sensors_panel.py               [create]
tests/integration/test_sensors_panel_sdk.py    [create — CreateRadarDisplay end-to-end]
```

Each task lands as its own commit. The shim (Task 1) is independently useful even if the panel isn't wired yet — it stops the SDK calls from raising.

---

## Task 1: SDK shim — `_RadarDisplay` / `_RadarScope` / `_RadarBlip`

**Files:**
- Create: `engine/appc/radar.py`
- Modify: `engine/appc/windows.py`
- Modify: `App.py` (re-exports near the bottom, after `ShipClass` imports)
- Test: `tests/unit/test_radar_display_shim.py`

The shim mirrors only the surface that `TacticalMenuHandlers.CreateRadarDisplay` and the `Tactical/Interface/RadarDisplay.py` / `RadarScope.py` modules touch. Everything else is no-op until a future task needs it.

SDK callsites driving the shim:
- [sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:471-476](../../../sdk/Build/scripts/Bridge/TacticalMenuHandlers.py) — `RadarDisplay_Create(0.0, 0.0)`, `SetUseScrolling(0)`, `pTacticalWindow.SetRadarDisplay(p)`
- [sdk/Build/scripts/Tactical/Interface/RadarDisplay.py:32-42](../../../sdk/Build/scripts/Tactical/Interface/RadarDisplay.py) — `RadarScope_Create(w, h)`, `pDisplay.AddChild(pScope, 0, 0, 0)`, `pDisplay.SetColorBasedOnFlags()`, `pDisplay.ResizeUI()`, `pDisplay.RepositionUI()`, `pDisplay.InteriorChangedSize(1)`
- [sdk/Build/scripts/Tactical/Interface/RadarScope.py:26-56](../../../sdk/Build/scripts/Tactical/Interface/RadarScope.py) — `pScope.SetNoFocus()`, `pScope.CreateShipIcon()`, `RadarBlip_Create(group, index)`, `pScope.SetTargetBracket(blip)`, `pScope.AddChild(child, 0, 0, 0)` × 7

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_radar_display_shim.py`:

```python
"""Tests for App.RadarDisplay_Create / RadarScope_Create / RadarBlip_Create
and the TacticalControlWindow.SetRadarDisplay accessor.

These cover the surface SDK scripts touch, not the per-tick rendering
(that lives on SensorsPanel)."""
import App


def test_radar_display_create_returns_object_with_sdk_methods():
    p = App.RadarDisplay_Create(0.0, 0.0)
    # All these are no-ops; the test just asserts they exist + are callable
    # without raising. SDK scripts call each of them during bridge load.
    p.SetUseScrolling(0)
    p.SetColorBasedOnFlags()
    p.ResizeUI()
    p.RepositionUI()
    p.InteriorChangedSize(1)
    # Inherits SetName / AddChild from the stylized-window stub.
    p.SetName("Sensors")
    assert p.GetName() == "Sensors"


def test_radar_scope_create_returns_object_with_sdk_methods():
    pScope = App.RadarScope_Create(0.1, 0.1)
    pScope.SetNoFocus()
    # CreateShipIcon returns a TGIcon-shaped object the SDK adds as a child.
    icon = pScope.CreateShipIcon()
    assert icon is not None
    pScope.AddChild(icon, 0.0, 0.0, 0)
    # Target bracket is the one blip the SDK constructs explicitly.
    bracket = App.RadarBlip_Create("LCARS_1024", 430)
    pScope.SetTargetBracket(bracket)
    pScope.AddChild(bracket, 0.0, 0.0, 0)
    # Resize/Reposition handed off to RadarScope.ResizeUI helper module.
    pScope.Resize(0.1, 0.1, 0)
    pScope.Layout()


def test_radar_blip_create_exposes_ship_id_methods():
    blip = App.RadarBlip_Create("LCARS_1024", 400)
    blip.SetShipID(42)
    assert blip.GetShipID() == 42


def test_tactical_control_window_set_get_radar_display():
    pTCW = App.TacticalControlWindow_GetTacticalControlWindow()
    p = App.RadarDisplay_Create(0.0, 0.0)
    pTCW.SetRadarDisplay(p)
    assert pTCW.GetRadarDisplay() is p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_radar_display_shim.py -v`
Expected: FAIL — `AttributeError: module 'App' has no attribute 'RadarDisplay_Create'`.

- [ ] **Step 3: Implement the shim**

Create `engine/appc/radar.py`:

```python
"""SDK radar shim — RadarDisplay / RadarScope / RadarBlip.

Mirrors the surface SDK scripts touch in
sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:471-476 and
sdk/Build/scripts/Tactical/Interface/RadarDisplay.py + RadarScope.py.
No rendering — the SensorsPanel view layer does that. Shim's only
job is to let bridge-load scripts run without raising.
"""
from __future__ import annotations
from typing import List, Optional


class _RadarBlip:
    """SDK App.py:8535 — extends TGIcon. SDK calls: SetShipID, GetShipID,
    plus the inherited TGIcon mutators we don't need yet."""

    def __init__(self, group_name: str = "", index: int = 0):
        self._group = str(group_name)
        self._index = int(index)
        self._ship_id: int = 0

    def SetShipID(self, ship_id) -> None:
        self._ship_id = int(ship_id)

    def GetShipID(self) -> int:
        return self._ship_id


class _RadarScope:
    """SDK App.py:8554 — extends TGPane. RadarScope.py builds a 7-slot
    child layout (ship icon, ring, bracket pane, target bracket, blip
    pane, phaser pane, background pane). The shim doesn't enforce slot
    semantics — it just accepts AddChild calls and stores them."""

    # Child-slot constants the SDK reads (RadarScope.py uses App.RadarScope.SHIP_ICON etc.)
    SHIP_ICON       = 0
    RADAR_RING      = 1
    BRACKET_PANE    = 2
    TARGET_BRACKET  = 3
    BLIP_PANE       = 4
    PHASER_LINE_PANE = 5
    BACKGROUND_PANE  = 6

    def __init__(self, w: float = 0.0, h: float = 0.0):
        self._w = float(w)
        self._h = float(h)
        self._children: List[object] = []
        self._target_bracket: Optional[_RadarBlip] = None

    # TGPane surface (the bits RadarScope.py touches).
    def SetNoFocus(self) -> None: pass
    def Layout(self) -> None: pass
    def GetWidth(self) -> float:  return self._w
    def GetHeight(self) -> float: return self._h

    def Resize(self, w: float, h: float, _flags: int = 0) -> None:
        self._w = float(w)
        self._h = float(h)

    def AddChild(self, child, _x: float = 0.0, _y: float = 0.0, _z: int = 0) -> None:
        self._children.append(child)

    def GetNthChild(self, n: int):
        if 0 <= n < len(self._children):
            return self._children[n]
        return None

    def GetNumChildren(self) -> int:
        return len(self._children)

    # RadarScope-specific.
    def CreateShipIcon(self):
        """SDK returns a TGIcon. The shim returns a generic placeholder
        object the SDK then re-adds via AddChild."""
        return _RadarBlip("ShipIcon", 0)

    def SetTargetBracket(self, blip: _RadarBlip) -> None:
        self._target_bracket = blip

    def GetTargetBracket(self) -> Optional[_RadarBlip]:
        return self._target_bracket


class _RadarDisplay:
    """SDK App.py:8513 — extends STStylizedWindow. The shim implements
    only the methods bridge-load scripts touch; the visual is rendered
    by SensorsPanel reading game state directly, not by walking this
    object's children.

    Child slot 0 (App.RadarDisplay.RADAR_SCOPE) is the one RadarScope
    instance SDK RadarDisplay.Create adds. Exposed as a class constant
    so SDK lookups via App.RadarDisplay.RADAR_SCOPE resolve."""

    RADAR_SCOPE = 0

    def __init__(self, w: float = 0.0, h: float = 0.0):
        self._w = float(w)
        self._h = float(h)
        self._name: str = ""
        self._children: List[object] = []
        self._minimized: bool = False
        self._minimizable: bool = True
        self._visible: bool = True
        self._range_m: float = 8000.0  # docs/ui_designs/05-sensors-radar.md default

    # STStylizedWindow / window-shaped surface.
    def SetName(self, name) -> None:    self._name = str(name)
    def GetName(self) -> str:           return self._name
    def GetWidth(self) -> float:        return self._w
    def GetHeight(self) -> float:       return self._h
    def SetUseScrolling(self, _flag: int) -> None: pass
    def SetColorBasedOnFlags(self) -> None: pass
    def ResizeUI(self) -> None: pass
    def RepositionUI(self) -> None: pass
    def InteriorChangedSize(self, _flag: int = 0) -> None: pass
    def SetPosition(self, _x: float, _y: float, _z: int = 0) -> None: pass
    def Layout(self) -> None: pass

    def AddChild(self, child, _x: float = 0.0, _y: float = 0.0, _z: int = 0) -> None:
        self._children.append(child)

    def GetNthChild(self, n: int):
        if 0 <= n < len(self._children):
            return self._children[n]
        return None

    # Minimizable surface (TacticalControlWindow Setup* functions call these).
    def IsMinimized(self) -> int:        return 1 if self._minimized else 0
    def SetMinimized(self, v) -> None:   self._minimized = bool(v)
    def IsMinimizable(self) -> int:      return 1 if self._minimizable else 0
    def SetMinimizable(self, v) -> None: self._minimizable = bool(v)

    def IsVisible(self) -> int:           return 1 if self._visible else 0
    def SetVisible(self, _flag: int = 0) -> None:    self._visible = True
    def SetNotVisible(self, _flag: int = 0) -> None: self._visible = False
    def GetObjID(self) -> int:            return id(self)

    # Engine-side accessor the SensorsPanel reads (not an SDK call —
    # SetRange lets mission scripts override the default if they want).
    def SetRange(self, range_m: float) -> None:
        self._range_m = float(range_m)

    def GetRange(self) -> float:
        return self._range_m


# ── Module-level factories (re-exported by App.py) ──

def RadarDisplay_Create(w: float = 0.0, h: float = 0.0) -> _RadarDisplay:
    return _RadarDisplay(w=w, h=h)


def RadarScope_Create(w: float = 0.0, h: float = 0.0) -> _RadarScope:
    return _RadarScope(w=w, h=h)


def RadarBlip_Create(group_name: str = "", index: int = 0) -> _RadarBlip:
    return _RadarBlip(group_name=group_name, index=index)


def RadarDisplay_Cast(obj):
    """Lenient cast — matches the STMenu_Cast pattern used elsewhere in
    the shim."""
    if isinstance(obj, _RadarDisplay):
        return obj
    return obj if obj is not None else None
```

Then extend `engine/appc/windows.py` so the TCW exposes the radar accessor:

```python
"""TacticalControlWindow placeholder.

Real BC TCW is a full window with menus / layout / focus.  PR 2a only
needs the event-handler-object surface so TacticalInterfaceHandlers.
RegisterHandlers(pTCW) can install fire-event handlers on it.  Future
PRs will replace this with the real window when the menu system lands.
"""
from engine.appc.events import TGEventHandlerObject


class TacticalControlWindow(TGEventHandlerObject):
    _instance: "TacticalControlWindow | None" = None

    def __init__(self):
        super().__init__()
        self._radar_display = None

    @classmethod
    def GetInstance(cls) -> "TacticalControlWindow":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def CallNextHandler(self, _evt) -> None:
        """SDK handlers call pObject.CallNextHandler(pEvent) for chain
        propagation.  Without a parent window chain we no-op."""
        return None

    # Radar display accessor — SDK TacticalMenuHandlers.CreateRadarDisplay
    # at sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:475 calls
    # pTacticalWindow.SetRadarDisplay(p); RadarDisplay.py:55 calls
    # pTCW.GetRadarDisplay() to get it back.
    def SetRadarDisplay(self, p) -> None:
        self._radar_display = p

    def GetRadarDisplay(self):
        return self._radar_display
```

Then re-export from `App.py`. Add this block immediately after the existing `from engine.appc.windows import TacticalControlWindow` line (currently line 17) — keep imports grouped by module:

```python
from engine.appc.radar import (
    RadarDisplay_Create, RadarDisplay_Cast,
    RadarScope_Create, RadarBlip_Create,
    _RadarDisplay as RadarDisplay,
    _RadarScope as RadarScope,
    _RadarBlip as RadarBlip,
)
```

`RadarDisplay`/`RadarScope`/`RadarBlip` (without leading underscore) are exposed because SDK code reads class-level constants like `App.RadarDisplay.RADAR_SCOPE` and `App.RadarScope.BLIP_PANE`. The leading-underscore originals stay so the radar module's internal type hints are self-consistent.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_radar_display_shim.py -v`
Expected: PASS — all four tests green.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/radar.py engine/appc/windows.py App.py \
        tests/unit/test_radar_display_shim.py
git commit -m "feat(radar): SDK shim for RadarDisplay/RadarScope/RadarBlip

SDK callers (LoadBridge → Bridge/TacticalMenuHandlers.CreateRadarDisplay,
Tactical/Interface/RadarDisplay.py, RadarScope.py) now run unchanged
against the headless shim. No rendering — that lands in a follow-up
SensorsPanel view layer."
```

---

## Task 2: Radar projection helper

**Files:**
- Create: `engine/ui/radar_projection.py`
- Test: `tests/unit/test_radar_projection.py`

Pure-math module — given player world position + rotation and a contact's world position + rotation, returns the disc-relative `(x, y, alt, heading)` tuple. Lives separate from the panel so the projection is testable without spinning up a full mission.

Conventions (matches `engine/appc/ships.py:153-157` and `properties.py`):
- World axes: X = right, Y = forward, Z = up
- Model forward = world column 1 of the rotation matrix (`R.GetCol(1)`)
- Model right   = world column 0 (`R.GetCol(0)`)
- Model up      = world column 2 (`R.GetCol(2)`)
- Disc coords: `(x, y)` normalised to `[-1, +1]` where `+y` = player's forward, `+x` = player's right. Off-disc when `x² + y² > 1`.
- `alt` normalised to `[-1, +1]` clipped — fraction of `range_m` of vertical (player-up) offset.
- `heading` radians, 0 = same direction as player forward, positive = clockwise looking down.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_radar_projection.py`:

```python
"""Pure-math tests for the disc projection. No SDK objects — feed in
TGPoint3 + TGMatrix3 directly so the test is fast + deterministic."""
import math
import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.ui.radar_projection import project_contact, Contact


def _identity():
    m = TGMatrix3()
    return m


def _yaw(theta):
    """Yaw matrix — rotates forward (Y) toward right (X) by +theta rad
    looking down (+Z). Columns are model right / forward / up."""
    m = TGMatrix3()
    c, s = math.cos(theta), math.sin(theta)
    # right = (cos, -sin, 0); forward = (sin, cos, 0); up = (0, 0, 1)
    m._m = [
        [ c,  s,  0.0],
        [-s,  c,  0.0],
        [0.0, 0.0, 1.0],
    ]
    return m


def test_contact_at_player_forward_within_range():
    """Contact 4000 m ahead of a player facing +Y → (x≈0, y≈+0.5)."""
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_identity(),
        target_pos=TGPoint3(0.0, 4000.0, 0.0),
        target_rot=_identity(),
        range_m=8000.0,
    )
    assert c is not None
    assert abs(c.x) < 1e-6
    assert c.y == pytest.approx(0.5, abs=1e-6)
    assert abs(c.alt) < 1e-6
    assert abs(c.heading) < 1e-6


def test_contact_to_player_right_within_range():
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_identity(),
        target_pos=TGPoint3(2000.0, 0.0, 0.0),
        target_rot=_identity(),
        range_m=8000.0,
    )
    assert c.x == pytest.approx(0.25, abs=1e-6)
    assert abs(c.y) < 1e-6


def test_contact_above_player_uses_alt():
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_identity(),
        target_pos=TGPoint3(0.0, 0.0, 4000.0),
        target_rot=_identity(),
        range_m=8000.0,
    )
    # In-plane projection is the origin; altitude carries the offset.
    assert abs(c.x) < 1e-6
    assert abs(c.y) < 1e-6
    assert c.alt == pytest.approx(0.5, abs=1e-6)


def test_off_disc_contact_returns_none():
    """Contact 10 km ahead with range = 8 km → outside disc → None."""
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_identity(),
        target_pos=TGPoint3(0.0, 10000.0, 0.0),
        target_rot=_identity(),
        range_m=8000.0,
    )
    assert c is None


def test_disc_coords_are_player_relative():
    """Player rotated 90° (yaw +π/2 — forward now along +X). A contact
    along world +X is "ahead" of the player, so y should be positive,
    x near zero."""
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_yaw(math.pi / 2.0),
        target_pos=TGPoint3(4000.0, 0.0, 0.0),
        target_rot=_identity(),
        range_m=8000.0,
    )
    assert abs(c.x) < 1e-6
    assert c.y == pytest.approx(0.5, abs=1e-6)


def test_heading_is_target_forward_relative_to_player_forward():
    """Player faces +Y; target faces -Y (i.e. directly toward the player).
    Relative heading should be π (180°)."""
    c = project_contact(
        player_pos=TGPoint3(0.0, 0.0, 0.0),
        player_rot=_identity(),
        target_pos=TGPoint3(0.0, 2000.0, 0.0),
        target_rot=_yaw(math.pi),
        range_m=8000.0,
    )
    assert abs(abs(c.heading) - math.pi) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_radar_projection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.ui.radar_projection'`.

- [ ] **Step 3: Implement the projection**

Create `engine/ui/radar_projection.py`:

```python
"""Pure projection math for the sensor disc.

Reads player + contact world-space pose, returns the disc-relative
(x, y, alt, heading) tuple, or None if the contact is outside disc
range. Lives separate from the panel so it's testable in isolation.

Convention (matches engine/appc/ships.py:153-157):
  - World axes: X = right, Y = forward, Z = up.
  - Model forward = R.GetCol(1); model right = R.GetCol(0);
    model up = R.GetCol(2).
  - Disc coords normalised to [-1, +1]: +y = player forward,
    +x = player right.
  - Altitude normalised by range_m, clipped to [-1, +1].
  - Heading in radians: 0 = same heading as player; positive = clockwise
    looking down (toward player's right).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from engine.appc.math import TGPoint3, TGMatrix3


@dataclass(frozen=True)
class Contact:
    x: float          # disc-plane x, normalised [-1, +1]
    y: float          # disc-plane y, normalised [-1, +1]
    alt: float        # altitude, normalised then clipped to [-1, +1]
    heading: float    # radians, relative to player forward


def project_contact(
    player_pos: TGPoint3,
    player_rot: TGMatrix3,
    target_pos: TGPoint3,
    target_rot: TGMatrix3,
    range_m: float,
) -> Optional[Contact]:
    if range_m <= 0.0:
        return None

    # Delta in world space.
    dx = target_pos.x - player_pos.x
    dy = target_pos.y - player_pos.y
    dz = target_pos.z - player_pos.z

    # Player basis vectors in world space (columns of the rotation matrix).
    right   = player_rot.GetCol(0)
    forward = player_rot.GetCol(1)
    up      = player_rot.GetCol(2)

    # Decompose the delta into the player frame.
    proj_right   = dx * right.x   + dy * right.y   + dz * right.z
    proj_forward = dx * forward.x + dy * forward.y + dz * forward.z
    proj_up      = dx * up.x      + dy * up.y      + dz * up.z

    # Disc-plane distance (ignores altitude — altitude is the stem).
    plane_sq = proj_right * proj_right + proj_forward * proj_forward
    if plane_sq > range_m * range_m:
        return None  # outside disc → contact hidden, matches stock BC

    inv_range = 1.0 / range_m
    x = proj_right   * inv_range
    y = proj_forward * inv_range

    # Altitude — clip to [-1, +1] so very high/low contacts don't fly
    # off the panel. The disc filter above only gates the planar
    # distance; a contact directly above the player at range_m * 2
    # should still render at the disc centre with a max-length stem.
    alt = max(-1.0, min(1.0, proj_up * inv_range))

    # Heading — target forward projected onto the player's (right, forward)
    # plane, expressed as an angle from player forward.
    tgt_fwd = target_rot.GetCol(1)
    tgt_in_right   = tgt_fwd.x * right.x   + tgt_fwd.y * right.y   + tgt_fwd.z * right.z
    tgt_in_forward = tgt_fwd.x * forward.x + tgt_fwd.y * forward.y + tgt_fwd.z * forward.z
    heading = math.atan2(tgt_in_right, tgt_in_forward)

    return Contact(x=x, y=y, alt=alt, heading=heading)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_radar_projection.py -v`
Expected: PASS — all six tests green.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/radar_projection.py tests/unit/test_radar_projection.py
git commit -m "feat(radar): pure projection math for sensor disc

Maps world-space (player pose, contact pose) to disc-relative
(x, y, alt, heading), filtering off-disc contacts. Testable in
isolation — no SDK objects, just TGPoint3 + TGMatrix3."
```

---

## Task 3: `SensorsPanel` (Panel subclass)

**Files:**
- Create: `engine/ui/sensors_panel.py`
- Test: `tests/unit/test_sensors_panel.py`

Mirrors the [target_list_view.py](../../../engine/ui/target_list_view.py) pattern: snapshot tuple → idempotent JSON emit → JS function call. Reads from the player's spatial set (NOT the bridge set — bridge set holds bridge-interior objects; spawned ships live in mission-named sets like "Biranu1"). Reuses [`resolve_affiliation`](../../../engine/appc/target_menu.py#L290-L306) from `engine.appc.target_menu`.

Visibility filter (matches [`update_target_list_visibility`](../../../engine/appc/subsystems.py#L1514) but at the panel level): only emit ships whose `STSubsystemMenu.IsVisible() == 1`. The host loop already calls `update_target_list_visibility` each tick; the radar shares that visibility state for free.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sensors_panel.py`:

```python
"""SensorsPanel snapshot + payload tests. The projection itself is
already covered by tests/unit/test_radar_projection.py — these tests
exercise the panel's read-from-game-state, filter, emit pipeline."""
import json
import App
from engine.appc.ships import ShipClass
from engine.appc.math import TGPoint3


def _setup_game():
    from engine.core.game import Game, Episode, Mission, _set_current_game
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)
    return game, player, mission


def _make_ship(name, x=0.0, y=0.0, z=0.0):
    s = ShipClass()
    s.SetName(name)
    s.SetTranslate(TGPoint3(x, y, z))
    return s


def test_payload_lists_visible_contacts_with_affiliations():
    from engine.ui.sensors_panel import SensorsPanel
    from engine.appc.sets import SetClass

    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game()
    try:
        mission.GetFriendlyGroup().AddName("Ally")
        mission.GetEnemyGroup().AddName("Foe")

        ally = _make_ship("Ally", x=0.0, y=2000.0, z=0.0)
        foe  = _make_ship("Foe",  x=3000.0, y=0.0, z=500.0)
        far  = _make_ship("Far",  x=0.0, y=99999.0, z=0.0)  # off-disc

        spatial = SetClass()
        App.g_kSetManager.AddSet(spatial, "test_set")
        spatial.AddObjectToSet(ally, "Ally")
        spatial.AddObjectToSet(foe, "Foe")
        spatial.AddObjectToSet(far, "Far")
        player._containing_set = spatial

        for s in (ally, foe, far):
            menu.RebuildShipMenu(s)
        menu.ResetAffiliationColors()
        # All three rows visible (sensor visibility runs separately).
        for child in menu._children:
            child.SetVisible()

        panel = SensorsPanel()
        script = panel.render_payload()
        assert script is not None
        assert script.startswith("setRadar(")
        body = script[len("setRadar("):-2]
        state = json.loads(body)

        assert state["visible"] is True
        names = sorted(c["name"] for c in state["contacts"])
        # "Far" is outside disc range → filtered out
        assert names == ["Ally", "Foe"]
        by_name = {c["name"]: c for c in state["contacts"]}
        assert by_name["Ally"]["affiliation"] == "FRIENDLY"
        assert by_name["Foe"]["affiliation"] == "ENEMY"
    finally:
        App.g_kSetManager.DeleteSet("test_set")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_payload_is_idempotent_until_state_changes():
    from engine.ui.sensors_panel import SensorsPanel
    from engine.appc.sets import SetClass

    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game()
    try:
        ship = _make_ship("X", x=0.0, y=1000.0, z=0.0)
        spatial = SetClass()
        App.g_kSetManager.AddSet(spatial, "test_set")
        spatial.AddObjectToSet(ship, "X")
        player._containing_set = spatial
        menu.RebuildShipMenu(ship)
        menu._children[0].SetVisible()

        panel = SensorsPanel()
        first = panel.render_payload()
        assert first is not None
        # Nothing changed → None on the next tick.
        assert panel.render_payload() is None

        # Ship moves → next call re-emits.
        ship.SetTranslate(TGPoint3(0.0, 2000.0, 0.0))
        assert panel.render_payload() is not None
    finally:
        App.g_kSetManager.DeleteSet("test_set")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_payload_marks_targeted_contact():
    from engine.ui.sensors_panel import SensorsPanel
    from engine.appc.sets import SetClass

    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game()
    try:
        ship = _make_ship("Galaxy", x=0.0, y=1500.0, z=0.0)
        spatial = SetClass()
        App.g_kSetManager.AddSet(spatial, "test_set")
        spatial.AddObjectToSet(ship, "Galaxy")
        player._containing_set = spatial
        menu.RebuildShipMenu(ship)
        menu._children[0].SetVisible()
        # Add to bridge set so player.SetTarget("Galaxy") resolves.
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            bridge = SetClass()
            App.g_kSetManager.AddSet(bridge, "bridge")
        bridge.AddObjectToSet(ship, "Galaxy")
        player.SetTarget("Galaxy")

        panel = SensorsPanel()
        script = panel.render_payload()
        body = script[len("setRadar("):-2]
        state = json.loads(body)
        assert len(state["contacts"]) == 1
        assert state["contacts"][0]["targeted"] is True
    finally:
        App.g_kSetManager.DeleteSet("test_set")
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_payload_skips_invisible_rows():
    from engine.ui.sensors_panel import SensorsPanel
    from engine.appc.sets import SetClass

    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game()
    try:
        ship = _make_ship("Cloaked", x=0.0, y=1000.0, z=0.0)
        spatial = SetClass()
        App.g_kSetManager.AddSet(spatial, "test_set")
        spatial.AddObjectToSet(ship, "Cloaked")
        player._containing_set = spatial
        menu.RebuildShipMenu(ship)
        menu._children[0].SetNotVisible()  # not picked up by sensors

        panel = SensorsPanel()
        script = panel.render_payload()
        body = script[len("setRadar("):-2]
        state = json.loads(body)
        assert state["contacts"] == []
    finally:
        App.g_kSetManager.DeleteSet("test_set")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_hidden_panel_emits_visible_false():
    from engine.ui.sensors_panel import SensorsPanel

    _setup_game()
    try:
        panel = SensorsPanel()
        panel.visible = False
        script = panel.render_payload()
        body = script[len("setRadar("):-2]
        state = json.loads(body)
        assert state["visible"] is False
        # No need to enumerate contacts when the panel is hidden.
        assert state.get("contacts", []) == []
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_sensors_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.ui.sensors_panel'`.

- [ ] **Step 3: Implement the panel**

Create `engine/ui/sensors_panel.py`:

```python
"""CEF view for the bottom-left Sensors / radar panel.

Each tick, walks the player's spatial set, runs each ship through
radar_projection.project_contact, and emits a `setRadar(...)` JS call
with the filtered contact list. Idempotent — re-emits only when the
snapshot changes.

Visibility shares state with the target list: only ships whose
STSubsystemMenu.IsVisible() == 1 are emitted. The host loop already
runs update_target_list_visibility() each tick; we read the result.

Spec: docs/ui_designs/05-sensors-radar.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel
from engine.ui.radar_projection import project_contact


# The disc's default world-space radius. Spec value
# (docs/ui_designs/05-sensors-radar.md "SDK runtime contract"). Real
# SDK code calls pRadar.SetRange(8000); for now the panel defaults to
# the spec value when no SetRange has been issued. SDK scripts that
# need a different range call _RadarDisplay.SetRange and we re-read it
# each snapshot.
DEFAULT_RANGE_M = 8000.0

_AFFILIATION_TO_KIND = {
    "FRIENDLY": "ship",
    "ENEMY":    "ship",
    "NEUTRAL":  "ship",
    "UNKNOWN":  "ship",
}


class SensorsPanel(Panel):
    @property
    def name(self) -> str:
        return "sensors"

    def __init__(self):
        super().__init__()
        self._last_snapshot: Optional[tuple] = None

    def _resolve_range_m(self) -> float:
        """Read the range from the SDK RadarDisplay if one's been
        registered with the TacticalControlWindow; else use the spec
        default. Lets SDK scripts override per-mission via SetRange."""
        import App
        tcw = App.TacticalControlWindow_GetTacticalControlWindow()
        radar = tcw.GetRadarDisplay() if tcw is not None else None
        if radar is not None and hasattr(radar, "GetRange"):
            try:
                return float(radar.GetRange())
            except Exception:
                pass
        return DEFAULT_RANGE_M

    def _snapshot(self):
        """Build a hashable snapshot of the rendered state."""
        if not self._visible:
            return (False, ())

        import App
        from engine.core.game import Game_GetCurrentGame
        from engine.appc.target_menu import STSubsystemMenu

        game = Game_GetCurrentGame()
        player = game.GetPlayer() if game is not None else None
        if player is None:
            return (True, ())

        spatial = getattr(player, "_containing_set", None)
        if spatial is None:
            return (True, ())

        menu = App.STTargetMenu_GetTargetMenu()
        if menu is None:
            return (True, ())

        target_ship = player.GetTarget() if hasattr(player, "GetTarget") else None
        range_m = self._resolve_range_m()
        player_pos = player.GetWorldLocation()
        player_rot = player.GetWorldRotation()

        rows = []
        for ship in spatial.GetObjectList():
            if ship is player:
                continue
            row = menu.GetObjectEntry(ship)
            if row is None or not isinstance(row, STSubsystemMenu):
                continue
            if row.IsVisible() != 1:
                continue
            contact = project_contact(
                player_pos=player_pos,
                player_rot=player_rot,
                target_pos=ship.GetWorldLocation(),
                target_rot=ship.GetWorldRotation(),
                range_m=range_m,
            )
            if contact is None:
                continue
            aff = row.GetAffiliation()
            kind = _AFFILIATION_TO_KIND.get(aff, "ship")
            rows.append((
                ship.GetName(),
                aff,
                kind,
                contact.x,
                contact.y,
                contact.alt,
                contact.heading,
                ship is target_ship,
            ))
        # Sort by name so the snapshot is deterministic.
        rows.sort(key=lambda r: r[0])
        return (True, tuple(rows))

    def render_payload(self) -> Optional[str]:
        snapshot = self._snapshot()
        if snapshot == self._last_snapshot:
            return None
        self._last_snapshot = snapshot
        visible, rows = snapshot
        payload = {
            "visible": visible,
            "range_m": self._resolve_range_m() if visible else 0.0,
            "contacts": [
                {
                    "name": name,
                    "affiliation": aff,
                    "kind": kind,
                    "x": x,
                    "y": y,
                    "alt": alt,
                    "heading": heading,
                    "targeted": targeted,
                }
                for (name, aff, kind, x, y, alt, heading, targeted) in rows
            ] if visible else [],
        }
        return "setRadar(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        """The radar disc is read-only in v1. No clickable contacts —
        the target list already handles target selection. Reserved for
        a future zoom-in / zoom-out gesture (SDK icons 90-102 are
        defined but unused in stock BC)."""
        return False

    def invalidate(self) -> None:
        self._last_snapshot = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_sensors_panel.py -v`
Expected: PASS — all five tests green.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/sensors_panel.py tests/unit/test_sensors_panel.py
git commit -m "feat(radar): SensorsPanel view emits setRadar(state)

Walks the player's spatial set, projects each visible contact onto
the disc, emits a JSON contact list to the CEF renderer. Idempotent,
shares sensor-visibility state with the target list."
```

---

## Task 4: HTML / CSS panel chrome

**Files:**
- Modify: `native/assets/ui-cef/hello.html`
- Create: `native/assets/ui-cef/css/sensors.css`

Static disc + rings + cardinal cross + chrome. The contacts overlay is added by JS in Task 5; this task only handles the immovable bits. Panel position is bottom-left at `bottom:24px left:24px`, mirroring the target list at `top:24px left:24px`.

Reuse the LCARS palette tokens that `target_list.css` already declares — keep both stylesheets aligned. The contacts overlay needs its own absolutely-positioned layer inside the disc so JS can clear and rebuild it without disturbing the static rings.

- [ ] **Step 1: Add the CSS**

Create `native/assets/ui-cef/css/sensors.css`:

```css
/* native/assets/ui-cef/css/sensors.css
 *
 * Sensors / radar panel — bottom-left corner of the tactical view.
 * Spec: docs/ui_designs/05-sensors-radar.html
 *
 * Static elements (panel chrome, disc background, range rings, cardinal
 * cross, player triangle) are pure CSS. The contacts overlay
 * (#sensors-contacts) is the layer JS rebuilds per state push.
 */

:root {
    /* Inherited from target_list.css; redeclared here in case sensors.css
     * loads first. Browsers de-duplicate identical :root entries. */
    --bc-menu1-base: rgb(216, 94, 86);
    --bc-menu1-accent: rgb(216, 132, 80);
    --bc-radar-friendly: rgb(80, 112, 230);
    --bc-radar-enemy: rgb(216, 43, 43);
    --bc-radar-neutral: rgb(255, 255, 175);
    --bc-radar-unknown: rgb(128, 128, 128);
    --bc-radar-target-bracket: rgb(255, 210, 90);
    --bc-radar-disc-inner: rgb(8, 12, 32);
    --bc-radar-disc-outer: rgb(2, 4, 16);
    --bc-radar-ring: rgba(216, 94, 86, 0.7);
    --bc-radar-ring-mid: rgba(216, 94, 86, 0.4);
    --bc-radar-ring-inner: rgba(216, 94, 86, 0.25);
    --bc-radar-cardinal: rgba(255, 255, 255, 0.08);
    --bc-label-text: rgb(235, 225, 255);
    --bc-body-bg: rgba(10, 10, 16, 0.97);
}

#sensors-panel {
    position: absolute;
    bottom: 24px;
    left: 24px;
    width: 240px;
    font-family: "Antonio", "Antonio-Regular", sans-serif;
    font-weight: 600;
    color: var(--bc-label-text);
    pointer-events: auto;
    -webkit-font-smoothing: antialiased;
}

#sensors-panel.sensors--hidden { display: none; }

.sensors__header {
    background: linear-gradient(90deg, var(--bc-menu1-base), var(--bc-menu1-accent));
    color: rgb(0, 0, 0);
    padding: 6px 14px 6px 18px;
    border-top-right-radius: 14px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-size: 14px;
}

.sensors__body {
    background: var(--bc-body-bg);
    border-left: 4px solid var(--bc-menu1-base);
    padding: 14px 18px 14px 14px;
    position: relative;
}

/* Disc container — fills body content area. The perspective tilt is
 * applied by transforming a child wrapper, NOT the disc itself, because
 * we need the contacts overlay to live in untransformed screen space
 * (so stems are vertical regardless of disc tilt). */
.sensors__disc {
    position: relative;
    width: 100%;
    height: 180px;
    background: radial-gradient(ellipse at center,
                                 var(--bc-radar-disc-inner) 0%,
                                 var(--bc-radar-disc-outer) 80%);
    overflow: hidden;
}

/* The tilted ellipse. Spec gives 75 px height for the 240 px-wide
 * panel — ratio ~0.4 → ~67° tilt. */
.sensors__disc-plane {
    position: absolute;
    left: 0; right: 0; top: 50%;
    height: 75px;
    transform: translateY(-50%);
}

.sensors__ring-outer,
.sensors__ring-mid,
.sensors__ring-inner {
    position: absolute;
    border-radius: 50%;
}

.sensors__ring-outer {
    inset: 0;
    border: 1px solid var(--bc-radar-ring);
}
.sensors__ring-mid {
    left: 50%; top: 50%;
    width: 65%; height: 65%;
    transform: translate(-50%, -50%);
    border: 1px dashed var(--bc-radar-ring-mid);
}
.sensors__ring-inner {
    left: 50%; top: 50%;
    width: 35%; height: 35%;
    transform: translate(-50%, -50%);
    border: 1px dashed var(--bc-radar-ring-inner);
}

.sensors__cardinal-v,
.sensors__cardinal-h {
    position: absolute;
    background: var(--bc-radar-cardinal);
}
.sensors__cardinal-v {
    left: 50%; top: 0; bottom: 0; width: 1px;
    transform: translateX(-50%);
}
.sensors__cardinal-h {
    top: 50%; left: 0; right: 0; height: 1px;
    transform: translateY(-50%);
}

/* Player triangle — fixed at the disc plane centre, fore=up. */
.sensors__player {
    position: absolute;
    left: 50%; top: 50%;
    transform: translate(-50%, -50%);
    width: 0; height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-bottom: 8px solid white;
    filter: drop-shadow(0 0 3px rgba(255, 255, 255, 0.6));
    pointer-events: none;
}

/* Contacts overlay — covers the disc; JS rebuilds children on each
 * setRadar() call. Contacts live in untransformed screen space so
 * altitude stems are vertical regardless of disc-plane tilt. */
.sensors__contacts {
    position: absolute;
    inset: 0;
    pointer-events: none;
}

/* Each contact: positioned absolute via inline style left/top. JS sets
 * --heading-deg via a CSS custom property so triangles rotate without
 * the JS having to know about transform syntax. */
.sensors__contact {
    position: absolute;
    width: 0; height: 0;
    transform: translate(-50%, -50%);
}

.sensors__triangle {
    position: absolute;
    left: 0; top: 0;
    transform: translate(-50%, -50%) rotate(var(--heading-deg, 0deg));
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 7px solid currentColor;
    filter: drop-shadow(0 0 3px currentColor);
}

.sensors__square {
    /* Torpedoes — no heading triangle. */
    position: absolute;
    left: 0; top: 0;
    transform: translate(-50%, -50%);
    width: 4px; height: 4px;
    background: currentColor;
    filter: drop-shadow(0 0 3px currentColor);
}

/* Stem — drawn via a thin vertical bar. JS sets --stem-px (px) and
 * --stem-sign (1 or -1) to pick up vs down. Stem origin is the disc
 * anchor; the triangle/square is offset along the stem by --stem-px. */
.sensors__stem {
    position: absolute;
    left: 0; top: 0;
    width: 1px;
    height: calc(abs(var(--stem-px, 0)) * 1px);
    transform: translateX(-50%)
               translateY(calc(var(--stem-sign, 1) * -50%));
    background: linear-gradient(
        to top,
        color-mix(in srgb, currentColor 30%, transparent),
        currentColor
    );
}

/* Affiliation colours — applied to the container, inherited by triangle
 * (via currentColor) and stem. */
.sensors__contact--FRIENDLY { color: var(--bc-radar-friendly); }
.sensors__contact--ENEMY    { color: var(--bc-radar-enemy); }
.sensors__contact--NEUTRAL  { color: var(--bc-radar-neutral); }
.sensors__contact--UNKNOWN  { color: var(--bc-radar-unknown); }

/* Disc anchor dot at the projection point — opacity 0.6 so it stays
 * subtle next to the bigger triangle glyph. */
.sensors__anchor {
    position: absolute;
    left: 0; top: 0;
    transform: translate(-50%, -50%);
    width: 4px; height: 4px;
    border-radius: 50%;
    background: currentColor;
    opacity: 0.6;
}

/* Gold corner bracket on the targeted contact. Four absolutely-
 * positioned L-corners surrounding the anchor point. */
.sensors__bracket {
    position: absolute;
    left: 0; top: 0;
    transform: translate(-50%, -50%);
    width: 18px; height: 18px;
    pointer-events: none;
}
.sensors__bracket-corner {
    position: absolute;
    width: 4px; height: 4px;
}
.sensors__bracket-corner--tl {
    left: 0; top: 0;
    border-left: 1.5px solid var(--bc-radar-target-bracket);
    border-top:  1.5px solid var(--bc-radar-target-bracket);
}
.sensors__bracket-corner--tr {
    right: 0; top: 0;
    border-right: 1.5px solid var(--bc-radar-target-bracket);
    border-top:   1.5px solid var(--bc-radar-target-bracket);
}
.sensors__bracket-corner--bl {
    left: 0; bottom: 0;
    border-left:   1.5px solid var(--bc-radar-target-bracket);
    border-bottom: 1.5px solid var(--bc-radar-target-bracket);
}
.sensors__bracket-corner--br {
    right: 0; bottom: 0;
    border-right:  1.5px solid var(--bc-radar-target-bracket);
    border-bottom: 1.5px solid var(--bc-radar-target-bracket);
}
```

- [ ] **Step 2: Add the panel block to hello.html**

Edit `native/assets/ui-cef/hello.html`. Add the stylesheet link in `<head>` after the existing `target_list.css` link:

```html
    <link rel="stylesheet" href="css/sensors.css">
```

Then add the panel block inside `<body>`, after the target-list-panel div and before the script tags:

```html
    <!-- Sensors / radar panel.
         Static disc + range rings rendered in HTML/CSS; per-tick contacts
         pushed via setRadar({visible, range_m, contacts:[...]}).
         No click events — radar is read-only in v1.
         Spec: docs/ui_designs/05-sensors-radar.md -->
    <div id="sensors-panel" class="sensors--hidden">
        <div class="sensors__header">Sensors</div>
        <div class="sensors__body">
            <div class="sensors__disc">
                <div class="sensors__disc-plane">
                    <div class="sensors__ring-outer"></div>
                    <div class="sensors__ring-mid"></div>
                    <div class="sensors__ring-inner"></div>
                    <div class="sensors__cardinal-v"></div>
                    <div class="sensors__cardinal-h"></div>
                    <div class="sensors__player"></div>
                </div>
                <div class="sensors__contacts" id="sensors-contacts"></div>
            </div>
        </div>
    </div>
```

Then add the JS script tag after the existing `target_list.js` reference (this lands in Task 5; declare it now so the HTML is complete):

```html
    <script src="js/sensors.js"></script>
```

- [ ] **Step 3: Sanity-check HTML structure**

Run: `cat native/assets/ui-cef/hello.html | grep -c "sensors"`
Expected: `>= 5` (one stylesheet link, panel div, header, body, disc, contacts).

There's no automated CSS test — visual verification happens after Task 5 lands the JS, via the live game.

- [ ] **Step 4: Commit**

```bash
git add native/assets/ui-cef/hello.html native/assets/ui-cef/css/sensors.css
git commit -m "feat(radar): sensors panel HTML + CSS chrome

Adds the bottom-left panel block with perspective-tilted disc, range
rings, cardinal cross, and player triangle. Contacts overlay is empty
until the JS landed in the next commit."
```

---

## Task 5: JS — `setRadar(state)` renderer

**Files:**
- Create: `native/assets/ui-cef/js/sensors.js`

The JS rebuilds `#sensors-contacts` on each call. State shape (matches `SensorsPanel.render_payload`):

```json
{
  "visible": true,
  "range_m": 8000,
  "contacts": [
    {"name": "USS Galaxy",
     "affiliation": "FRIENDLY",
     "kind": "ship",
     "x": 0.25, "y": -0.40,
     "alt": 0.15,
     "heading": 1.57,
     "targeted": false}
  ]
}
```

The disc render area is the perspective-tilted ellipse from CSS. The contacts overlay covers the entire `.sensors__disc` rectangle (not the squashed ellipse), so we map disc-relative `(x, y)` into pixel coords as follows:

- `disc_w_px = container.clientWidth` (full panel body width)
- `disc_h_px = container.clientHeight` × `0.42` (matches the 75/180 squash ratio in CSS, accounting for the disc-plane height vs container height — `.sensors__disc-plane` is `height: 75px` inside `height: 180px`)
- `center_x = disc_w_px / 2`, `center_y = container.clientHeight / 2`
- pixel-x = `center_x + x * (disc_w_px / 2)`
- pixel-y = `center_y + (-y) * (disc_h_px / 2)`  *(invert: +y is forward = up on screen)*

Altitude → stem pixel length: `stem_px = alt * MAX_STEM_PX` where `MAX_STEM_PX = 28` (visual choice — spec's mockup uses ~24-42 px for max-magnitude altitude).

The triangle is offset along the stem so it sits at the stem's far end, not on the disc anchor. Stem sign: positive alt → triangle sits above the anchor (translate up); negative alt → triangle sits below.

- [ ] **Step 1: Implement the JS**

Create `native/assets/ui-cef/js/sensors.js`:

```javascript
// native/assets/ui-cef/js/sensors.js
//
// Radar / sensors render fn. Driven by Python via cef_execute_javascript:
//   setRadar({visible, range_m, contacts: [
//     {name, affiliation, kind, x, y, alt, heading, targeted}, ...
//   ]});
//
// No interaction — the radar is read-only in v1.
// Spec: docs/ui_designs/05-sensors-radar.md

const _SENSORS_HTML_ESCAPES = {
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
};
function _sensorsEscapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
        return _SENSORS_HTML_ESCAPES[c];
    });
}

// Disc-plane vertical squash, matches .sensors__disc-plane height (75)
// over .sensors__disc height (180) in sensors.css. If those values
// change, update this in lockstep.
const _SENSORS_PLANE_SQUASH = 75.0 / 180.0;
// Max stem length in pixels for |alt| == 1.0. Tuned to match the
// mockup's longest stem (~42 px) without overshooting the disc.
const _SENSORS_MAX_STEM_PX = 28.0;

function _sensorsBuildContact(c) {
    const aff = String(c.affiliation || 'UNKNOWN');
    const kind = String(c.kind || 'ship');
    const targeted = !!c.targeted;
    const altPx = Math.max(-1.0, Math.min(1.0, +c.alt || 0)) * _SENSORS_MAX_STEM_PX;
    // Heading in radians (0 = same as player forward, +ve = clockwise).
    // CSS rotate() uses degrees; +ve degrees = clockwise.
    const headingDeg = (+c.heading || 0) * (180.0 / Math.PI);

    // Glyph: triangle for ships, filled square for torpedoes/projectiles.
    let glyph;
    if (kind === 'torpedo' || kind === 'projectile') {
        glyph = '<div class="sensors__square"></div>';
    } else {
        glyph = '<div class="sensors__triangle"'
              + ' style="--heading-deg:' + headingDeg.toFixed(2) + 'deg"></div>';
    }

    // Glyph y-offset along the stem — triangle/square sits at the stem
    // tip, not the disc anchor. Stem grows upward for positive alt,
    // downward for negative. Pixel sign convention: -y is up on screen.
    const glyphOffsetY = -altPx; // px

    const stemStyle = altPx === 0
        ? 'display:none'
        : '--stem-px:' + Math.abs(altPx).toFixed(2)
          + ';--stem-sign:' + (altPx >= 0 ? '1' : '-1');

    let bracket = '';
    if (targeted) {
        // Bracket sits around the glyph (at stem tip), not at the
        // anchor — that's where the eye reads the contact.
        bracket = '<div class="sensors__bracket"'
                + ' style="transform:translate(-50%,calc(-50% + ' + glyphOffsetY.toFixed(2) + 'px))">'
                +   '<div class="sensors__bracket-corner sensors__bracket-corner--tl"></div>'
                +   '<div class="sensors__bracket-corner sensors__bracket-corner--tr"></div>'
                +   '<div class="sensors__bracket-corner sensors__bracket-corner--bl"></div>'
                +   '<div class="sensors__bracket-corner sensors__bracket-corner--br"></div>'
                + '</div>';
    }

    return ''
        + '<div class="sensors__contact sensors__contact--' + _sensorsEscapeHtml(aff) + '"'
        +   ' data-name="' + _sensorsEscapeHtml(c.name || '') + '"'
        +   ' style="left:0;top:0">'
        +   '<div class="sensors__anchor"></div>'
        +   '<div class="sensors__stem" style="' + stemStyle + '"></div>'
        +   '<div style="transform:translateY(' + glyphOffsetY.toFixed(2) + 'px)">'
        +     glyph
        +   '</div>'
        +   bracket
        + '</div>';
}

function setRadar(state) {
    const panel = document.getElementById('sensors-panel');
    if (!panel) return;
    if (!state || !state.visible) {
        panel.classList.add('sensors--hidden');
        return;
    }
    panel.classList.remove('sensors--hidden');

    const overlay = document.getElementById('sensors-contacts');
    if (!overlay) return;

    // Disc geometry — re-read on every call so window resize is handled.
    const discRect = overlay.getBoundingClientRect();
    const discW = discRect.width;
    const discH = discRect.height;
    const cx = discW / 2;
    const cy = discH / 2;
    const halfW = discW / 2;
    const halfH = (discH * _SENSORS_PLANE_SQUASH) / 2;

    const contacts = state.contacts || [];
    let html = '';
    for (let i = 0; i < contacts.length; i++) {
        const c = contacts[i];
        // Normalised x,y from Python are already in [-1, +1]; map to px.
        // Invert y: Python's +y = forward = up on screen → CSS pixel -y.
        const px = cx + (+c.x || 0) * halfW;
        const py = cy - (+c.y || 0) * halfH;
        html += '<div style="position:absolute;'
              +   'left:' + px.toFixed(2) + 'px;'
              +   'top:'  + py.toFixed(2) + 'px">'
              +   _sensorsBuildContact(c)
              + '</div>';
    }
    overlay.innerHTML = html;
}
```

- [ ] **Step 2: Sanity-check JS syntax**

Run: `node -c native/assets/ui-cef/js/sensors.js`
Expected: silent (no output, exit 0). If `node` is unavailable: `python3 -c "import esprima; esprima.parseScript(open('native/assets/ui-cef/js/sensors.js').read())"` is a fallback; otherwise visually inspect the file for unbalanced braces.

- [ ] **Step 3: Commit**

```bash
git add native/assets/ui-cef/js/sensors.js
git commit -m "feat(radar): setRadar JS renderer

Rebuilds the contacts overlay on each state push. Maps Python disc
coords into pixels with the planar 75/180 squash, places triangle or
square glyphs at the stem tip, draws target bracket around the
selected contact."
```

---

## Task 6: Host loop wiring

**Files:**
- Modify: `engine/host_loop.py`

Register `SensorsPanel` next to `TargetListView`. Visibility tracks `view_mode.is_exterior` — same SPACE-bar toggle the target list uses, so the sensors panel appears when the player is in the space (tactical) view.

The panel registers as `name="sensors"` and emits no click events, so no mouse forwarding gate is needed (unlike the target list which gates clicks by bbox). The mouse-move forward already runs unconditionally — that covers any future CSS `:hover` on the disc.

- [ ] **Step 1: Add the registration**

Locate the existing block in `engine/host_loop.py` (currently lines 2039-2043):

```python
        from engine.ui.panel_registry import PanelRegistry
        from engine.ui.target_list_view import TargetListView
        registry = PanelRegistry(legacy_handler=pause_menu.dispatch_event)
        target_list_view = TargetListView()
        registry.register(target_list_view)
```

Replace it with:

```python
        from engine.ui.panel_registry import PanelRegistry
        from engine.ui.target_list_view import TargetListView
        from engine.ui.sensors_panel import SensorsPanel
        registry = PanelRegistry(legacy_handler=pause_menu.dispatch_event)
        target_list_view = TargetListView()
        sensors_panel = SensorsPanel()
        registry.register(target_list_view)
        registry.register(sensors_panel)
```

Then locate the visibility-gate block (currently around line 2145):

```python
                target_list_view.visible = view_mode.is_exterior
```

Add a sibling line immediately after:

```python
                target_list_view.visible = view_mode.is_exterior
                sensors_panel.visible    = view_mode.is_exterior
```

- [ ] **Step 2: Run the full suite to make sure nothing regressed**

Run: `uv run pytest tests/unit/test_sensors_panel.py tests/unit/test_radar_display_shim.py tests/unit/test_radar_projection.py tests/unit/test_target_list_view.py tests/unit/test_panel_registry.py -v`
Expected: PASS — all radar + projection tests + existing panel-registry / target-list tests still green.

> **Don't** run `uv run pytest` without a filter — the full suite uses >100 GB RAM and freezes the host (see CLAUDE.md auto-memory note on `pytest_memory.md`).

- [ ] **Step 3: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(radar): wire SensorsPanel into the host loop

Registered next to TargetListView; visibility tracks view_mode.is_exterior
so the panel appears when SPACE switches to the tactical view."
```

---

## Task 7: SDK integration smoke test

**Files:**
- Create: `tests/integration/test_sensors_panel_sdk.py`

End-to-end check: load the real SDK bridge-construction call path against the headless App shim. If `CreateRadarDisplay` from `sdk/Build/scripts/Bridge/TacticalMenuHandlers.py` raises, this test catches it. The target-list integration test at `tests/integration/test_target_list_sdk_integration.py` is the template.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_sensors_panel_sdk.py`:

```python
"""Integration smoke test: the SDK's CreateRadarDisplay helper from
Bridge/TacticalMenuHandlers.py runs against the headless shim and
registers a working RadarDisplay with the TacticalControlWindow."""
import App


def test_sdk_create_radar_display_runs():
    """Imports and invokes the actual SDK CreateRadarDisplay function."""
    pTCW = App.TacticalControlWindow_GetTacticalControlWindow()
    # CreateRadarDisplay is at sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:471
    # It calls App.RadarDisplay_Create + SetUseScrolling + SetRadarDisplay.
    from Bridge import TacticalMenuHandlers
    pRadar = TacticalMenuHandlers.CreateRadarDisplay(pTCW)
    assert pRadar is not None
    assert pTCW.GetRadarDisplay() is pRadar


def test_sensors_panel_renders_for_empty_world():
    """With no ships in the player's spatial set, SensorsPanel emits
    a visible-true / empty-contacts payload — not a crash."""
    import json
    from engine.ui.sensors_panel import SensorsPanel
    from engine.appc.sets import SetClass
    from engine.appc.ships import ShipClass
    from engine.core.game import Game, Episode, Mission, _set_current_game

    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    game.SetPlayer(player)
    spatial = SetClass()
    App.g_kSetManager.AddSet(spatial, "smoke_set")
    player._containing_set = spatial
    _set_current_game(game)

    App._reset_target_menu_singleton()
    App.STTargetMenu_CreateW("Targets")

    try:
        panel = SensorsPanel()
        script = panel.render_payload()
        assert script is not None
        assert script.startswith("setRadar(")
        state = json.loads(script[len("setRadar("):-2])
        assert state["visible"] is True
        assert state["contacts"] == []
        assert state["range_m"] > 0.0
    finally:
        App.g_kSetManager.DeleteSet("smoke_set")
        _set_current_game(None)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_sensors_panel_sdk.py -v`
Expected: PASS — both tests green. If the first test fails with `ImportError: No module named Bridge`, the SDK script path is not on `sys.path`; check that `tests/conftest.py`'s `_SDKFinder` is loaded for integration tests too (it's session-scoped, should be).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_sensors_panel_sdk.py
git commit -m "test(radar): SDK CreateRadarDisplay integration smoke

Loads sdk/Build/scripts/Bridge/TacticalMenuHandlers.CreateRadarDisplay
against the headless App shim and confirms it wires a RadarDisplay into
the TacticalControlWindow. Empty-world panel render confirmed too."
```

---

## Final verification (no commit)

After all seven tasks land, do a manual check:

- [ ] **Step 1: Build the host**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean build of `build/dauntless`.

- [ ] **Step 2: Run the radar-related test subset**

Run: `uv run pytest tests/unit/test_radar_display_shim.py tests/unit/test_radar_projection.py tests/unit/test_sensors_panel.py tests/integration/test_sensors_panel_sdk.py -v`
Expected: all green.

- [ ] **Step 3: Launch the game and visually verify**

Run: `./build/dauntless`
Expected:
- Bottom-left of the screen shows the "SENSORS" panel header with salmon-orange gradient + dark body
- A perspective-tilted disc with three nested range rings + faint cardinal cross
- White triangle (player) at the disc centre, fore-up
- Blue / red / gold / grey triangles for any other ships in the mission, offset onto the disc by their world position relative to the player
- Vertical stems on contacts above / below the player's altitude
- Gold corner bracket around the currently-targeted contact (whichever ship is highlighted in the target list)
- Pressing SPACE flips between tactical view (panel visible) and bridge view (panel hidden) — same gating as the target list

If the panel doesn't appear, check:
1. `_dauntless_host.cef_execute_javascript` is being called (host_loop.py:2166) — temporary `print` in the render loop will confirm.
2. The CEF page actually loaded `js/sensors.js` (DevTools network tab on a CEF debug build).
3. Snapshot is being computed: temporarily print `panel._snapshot()` from a host-loop tick to confirm `_containing_set` resolves.

Visual fidelity bugs (disc proportion off, blip colour wrong, stem direction inverted) are tracked against the mockup [docs/ui_designs/05-sensors-radar.html](../../ui_designs/05-sensors-radar.html) — open it side-by-side with the live game.

---

## Out of scope (deferred follow-ups)

- **Torpedoes / projectiles as contacts.** The kind `"torpedo"` is wired through the JS renderer (square glyph) and the `_AFFILIATION_TO_KIND` table is in place, but the panel currently only walks ships. Adding projectiles means walking the projectile registry (`engine.appc.projectiles`) and mapping each to a `Contact` with `kind="torpedo"` and `affiliation` from the launching ship.
- **Heading-rotated disc.** The original game's disc rotates with the player. Our projection is player-relative (forward = up) so this is implicit; no further work needed unless you decide to lock the disc to world axes.
- **Zoom-in / zoom-out icons.** SDK icon slots 90-102 exist for these but stock BC doesn't bind them. Implement only if a mission script needs runtime range adjustment.
- **`g_kSTRadarBorderHighlighted` alert state.** The SDK has a highlighted border colour for red alert; no callsite drives it in stock BC. Wire only if you add red-alert handling elsewhere.
- **Mod-driven blip colours.** The `LoadInterface.py:135-140` globals are already the colours we use; if a mod overrides them, the C++ side would need to push palette changes to CSS variables. Not needed for stock BC.
