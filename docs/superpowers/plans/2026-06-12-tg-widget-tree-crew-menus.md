# TG Widget Tree + Crew Menus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Headless TG widget tree so the 83 SDK widget-tree files run with real state, plus a `CrewMenuPanel` that renders the bridge crew menus in CEF and routes clicks back into unmodified SDK handlers.

**Architecture:** Two tiers per the spec ([2026-06-12-tg-widget-tree-crew-menus-design.md](../specs/2026-06-12-tg-widget-tree-crew-menus-design.md)). Tier 1: state-holding shim classes in `engine/appc/tg_ui/` (no rendering, no `_NamedStub` leakage) + real `ET_*`/`EST_*` constants. Tier 2: a `Panel` subclass that snapshots the `STTopLevelMenu` trees registered on `TacticalControlWindow` into CEF JSON and fires stored activation events on click.

**Tech Stack:** Python 3 shims (engine/appc conventions), pytest (focused subsets ONLY — full suite OOMs the host), CEF JS/CSS assets under `native/assets/ui-cef/`.

**Key existing facts (verified during planning — do not re-derive):**
- `STButton` ([engine/appc/characters.py:31](../../engine/appc/characters.py)) already stores `(label, event)` and `SendActivationEvent()` fires the stored event via `App.g_kEventManager.AddEvent`.
- `g_kEventManager.AddEvent(evt)` dispatches to `evt.GetDestination().ProcessEvent(evt)`; `ProcessEvent` resolves instance handlers registered via `AddPythonFuncHandlerForInstance(event_type, "module.func")` and calls `fn(dest, event)` ([engine/appc/events.py:141-163,264](../../engine/appc/events.py)).
- `ObjectClass` extends `TGEventHandlerObject`, so `STMenu`/`STButton` inherit handler registration.
- SDK builds menus like: `BridgeUtils.CreateBridgeMenuButton(pName, eType, iSubType, pDest)` → `TGIntEvent` with `SetEventType/SetDestination/SetInt` wrapped in `STButton_CreateW(pName, pEvent)` (sdk/Build/scripts/Bridge/BridgeUtils.py:37-43).
- `HelmMenuHandlers.AllStop(pHelmMenu, pEvent)` sets player AI to `AI.Player.Stay` via `MissionLib.SetPlayerAI` — observable test effect (sdk/Build/scripts/Bridge/HelmMenuHandlers.py:1517).
- Bare `import LCARS_1024` / `import FontsAndIcons` ALREADY resolve via `_SDKFinder`'s rglob fallback in both `tests/conftest.py` and `tools/mission_harness.py` (probed during planning; both pass under pytest). Tests only pin this.
- Icon manager API from SDK callers: `CreateIconGroup(name)`, `AddIconGroup(group)`, `GetScreenWidth()`, `GetScreenHeight()`; `TGIconGroup.LoadIconTexture(path)` → handle, `SetIconLocation(slot, tex, x, y, w, h, rotation=ROTATE_0, mirror=MIRROR_NONE)`, constants `ROTATE_0/90/180/270`, `MIRROR_NONE/HORIZONTAL/VERTICAL` (sdk/Build/scripts/Icons/LCARS_1024.py:208-230).
- Font manager API: `RegisterFont(family, size, registered_name, load_func_name)` (sdk/Build/scripts/Icons/FontsAndIcons.py).
- `tests/conftest.py` pre-stubs `Bridge.HelmMenuHandlers` as a `_StubModule` — integration tests must `sys.modules.pop("Bridge.HelmMenuHandlers", None)` (and re-stub in teardown) to load the real module.
- Static `ET_*` constants must stay **below 1200** (the `Game_GetNextEventType` allocator starts at 1200; input constants occupy 1001–1055). Use 1060+.
- Panel pattern: subclass `engine/ui/panel.py:Panel`; register in `engine/host_loop.py` ~line 2224 with the other `registry.register(...)` calls; JS receives `set<Name>(payload)` calls and emits `dauntlessEvent("<name>/<action>")` (see `engine/appc/sdk_mirror_panel.py` + `native/assets/ui-cef/js/sdk_mirror.js`).

---

### Task 1: ET_* bridge-interaction constants + CharacterClass EST_* constants

**Files:**
- Modify: `App.py` (after the `ET_INPUT_*` block ending at `ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL = 1055`)
- Modify: `engine/appc/characters.py` (the `CharacterClass` constants block at ~line 250 — `EST_ALERT_GREEN/YELLOW/RED` already exist)
- Test: `tests/unit/test_bridge_event_constants.py`

- [ ] **Step 1: Write the failing test**

```python
"""Bridge-interaction ET_* constants are real distinct ints (spec:
2026-06-12-tg-widget-tree-crew-menus-design.md)."""
import App

BRIDGE_ET_NAMES = [
    "ET_ST_BUTTON_CLICKED", "ET_COMMUNICATE", "ET_HAIL", "ET_SCAN",
    "ET_SET_COURSE", "ET_ALL_STOP", "ET_DOCK", "ET_MANAGE_POWER",
    "ET_MANEUVER", "ET_HAILABLE_CHANGE", "ET_SENSORS_SHIP_IDENTIFIED",
    "ET_CLOAK_COMPLETED", "ET_DECLOAK_COMPLETED", "ET_CHARACTER_MENU",
    "ET_CONTACT_STARFLEET",
]


def test_bridge_event_constants_are_distinct_ints():
    values = [getattr(App, n) for n in BRIDGE_ET_NAMES]
    assert all(type(v) is int for v in values)
    assert len(set(values)) == len(values)


def test_bridge_event_constants_below_allocator_start():
    # Game_GetNextEventType allocates from 1200 up; static constants must
    # never collide with allocated ids.
    for n in BRIDGE_ET_NAMES:
        assert getattr(App, n) < 1200


def test_character_est_constants():
    from engine.appc.characters import CharacterClass
    # Spot-check the ones the helm/bridge menu files reference.
    assert type(CharacterClass.EST_SET_COURSE_INTERCEPT) is int
    assert CharacterClass.EST_ALERT_GREEN == 0
    assert CharacterClass.EST_SCAN_OBJECT != CharacterClass.EST_SCAN_AREA
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_event_constants.py -v`
Expected: FAIL — `getattr(App, "ET_ST_BUTTON_CLICKED")` returns `_NamedStub`, so `type(v) is int` is False; `EST_SET_COURSE_INTERCEPT` raises `AttributeError` (actually returns `_Stub` via `TGObject.__getattr__` — the `type(...) is int` assert still fails).

- [ ] **Step 3: Add the ET_ block to App.py**

In `App.py`, directly after `ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL = 1055`:

```python
# ── Bridge-interaction event types ─────────────────────────────────────────────
# Spec: docs/superpowers/specs/2026-06-12-tg-widget-tree-crew-menus-design.md.
# Static ints in 1060-1099 — above the input block (1001-1055), below the
# Game_GetNextEventType allocator floor (1200).
ET_ST_BUTTON_CLICKED        = 1060
ET_COMMUNICATE              = 1061
ET_HAIL                     = 1062
ET_SCAN                     = 1063
ET_SET_COURSE               = 1064
ET_ALL_STOP                 = 1065
ET_DOCK                     = 1066
ET_MANAGE_POWER             = 1067
ET_MANEUVER                 = 1068
ET_HAILABLE_CHANGE          = 1069
ET_SENSORS_SHIP_IDENTIFIED  = 1070
ET_CLOAK_COMPLETED          = 1071
ET_DECLOAK_COMPLETED        = 1072
ET_CHARACTER_MENU           = 1073
ET_CONTACT_STARFLEET        = 1074
```

- [ ] **Step 4: Add EST_* constants to CharacterClass**

In `engine/appc/characters.py`, the `CharacterClass` body already has
`EST_ALERT_GREEN = 0 / EST_ALERT_YELLOW = 1 / EST_ALERT_RED = 2`. Replace that
three-line block with the full SDK enum in SDK declaration order
(sdk/Build/scripts/App.py — `Appc.CharacterClass_EST_*` bindings; sequential
ints matching SWIG enum order):

```python
    # EST_* — "execute ship task" subtype carried in bridge-menu TGIntEvents
    # (BridgeUtils.CreateBridgeMenuButton SetInt payload). Sequential ints in
    # SDK declaration order (sdk/.../App.py CharacterClass_EST_* bindings).
    EST_ALERT_GREEN                       = 0
    EST_ALERT_YELLOW                      = 1
    EST_ALERT_RED                         = 2
    EST_REPORT_OVERVIEW                   = 3
    EST_REPORT_ENGINES                    = 4
    EST_REPORT_WEAPONS                    = 5
    EST_REPORT_SHIELDS                    = 6
    EST_REPORT_REPAIR                     = 7
    EST_REPORT_SENSORS                    = 8
    EST_REPORT_DESTINATION                = 9
    EST_REPORT_SPEED                      = 10
    EST_REPORT_ETA                        = 11
    EST_SHIP_STATUS                       = 12
    EST_TARGET_STATUS                     = 13
    EST_TRANSFER_POWER_WEAPONS            = 14
    EST_TRANSFER_POWER_SHIELDS_FORE       = 15
    EST_TRANSFER_POWER_SHIELDS_AFT        = 16
    EST_TRANSFER_POWER_SHIELDS_PORT       = 17
    EST_TRANSFER_POWER_SHIELDS_STARBOARD  = 18
    EST_TRANSFER_POWER_SHIELDS_DORSAL     = 19
    EST_TRANSFER_POWER_SHIELDS_VENTRAL    = 20
    EST_TRANSFER_POWER_SENSORS            = 21
    EST_TRANSFER_POWER_ENGINES            = 22
    EST_REPAIR_PHASERS                    = 23
    EST_REPAIR_TORPEDO_TUBES              = 24
    EST_REPAIR_SENSORS                    = 25
    EST_REPAIR_IMPULSE_ENGINES            = 26
    EST_REPAIR_WARP_ENGINES               = 27
    EST_REPAIR_TRACTOR_BEAM               = 28
    EST_REPAIR_ENGINEERING                = 29
    EST_SET_COURSE_TO_MISSION_AREA        = 30
    EST_SET_COURSE_TO_PLANET              = 31
    EST_SET_COURSE_INTERCEPT              = 32
    EST_SET_COURSE_FOLLOW                 = 33
    EST_SCAN_OBJECT                       = 34
    EST_SCAN_AREA                         = 35
    EST_ATTACK_BEAM_WEAPON                = 36
    EST_ATTACK_WARHEAD                    = 37
    EST_ATTACK_IMPULSE_ENGINES            = 38
    EST_ATTACK_WARP_ENGINES               = 39
    EST_ATTACK_SENSORS                    = 40
    EST_ATTACK_ENGINEERING                = 41
    EST_ATTACK_TRACTOR_BEAM               = 42
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_bridge_event_constants.py tests/unit/test_player.py -v`
Expected: all PASS (test_player.py guards against accidental CharacterClass breakage).

- [ ] **Step 6: Commit**

```bash
git add App.py engine/appc/characters.py tests/unit/test_bridge_event_constants.py
git commit -m "feat(tg-ui): bridge-interaction ET_* and CharacterClass EST_* constants"
```

---

### Task 2: tg_ui package — widget ids + core TG widgets

**Files:**
- Create: `engine/appc/tg_ui/__init__.py`
- Create: `engine/appc/tg_ui/widgets.py`
- Test: `tests/unit/test_tg_ui_widgets.py`

- [ ] **Step 1: Write the failing test**

```python
"""Core TG widget tree — headless state holders, no rendering.
Spec: docs/superpowers/specs/2026-06-12-tg-widget-tree-crew-menus-design.md
"""
from engine.appc.tg_ui.widgets import (
    TGPane, TGPane_Create, TGPane_Cast,
    TGIcon, TGIcon_Create, TGIcon_Cast,
    TGParagraph, TGParagraph_Create, TGParagraph_CreateW, TGParagraph_Cast,
    TGIconGroup,
    ensure_widget_id,
)


def test_pane_hierarchy_and_stored_xy():
    parent = TGPane_Create(0.5, 0.04)
    child = TGIcon_Create("LCARS_1024", 120)
    parent.AddChild(child, 0.25, 0.1, 0)
    assert parent.GetChildren() == [(child, 0.25, 0.1)]


def test_pane_visibility_and_enabled_flags():
    p = TGPane_Create()
    assert p.IsVisible() == 1
    p.SetNotVisible()
    assert p.IsVisible() == 0
    p.SetDisabled()
    assert p.IsEnabled() == 0
    p.SetEnabled()
    assert p.IsEnabled() == 1


def test_paragraph_holds_text():
    para = TGParagraph_CreateW("Mission Objectives", 1.0, None)
    assert para.GetText() == "Mission Objectives"
    para.SetText("Updated")
    assert para.GetText() == "Updated"


def test_icon_group_records_atlas_locations():
    g = TGIconGroup("LCARS_1024")
    tex = g.LoadIconTexture("Data/Icons/Bridge/RadarBorder.tga")
    g.SetIconLocation(10, tex, 0, 0, 73, 73)
    g.SetIconLocation(
        20, tex, 0, 0, 73, 73,
        TGIconGroup.ROTATE_0, TGIconGroup.MIRROR_HORIZONTAL,
    )
    assert g.GetIconLocation(10) == (tex, 0, 0, 73, 73,
                                     TGIconGroup.ROTATE_0,
                                     TGIconGroup.MIRROR_NONE)
    assert g.GetIconLocation(20)[6] == TGIconGroup.MIRROR_HORIZONTAL


def test_casts_are_lenient_and_reject_non_widgets():
    p = TGPane_Create()
    assert TGPane_Cast(p) is p
    assert TGPane_Cast(None) is None
    assert TGIcon_Cast(p) is None
    assert TGParagraph_Cast(p) is None


def test_widget_ids_monotonic_and_stable():
    a, b = TGPane_Create(), TGPane_Create()
    ida, idb = ensure_widget_id(a), ensure_widget_id(b)
    assert ida != idb
    assert ensure_widget_id(a) == ida  # stable on re-ask


def test_pane_inherits_event_handler_registration():
    from engine.appc.events import TGEventHandlerObject
    assert isinstance(TGPane_Create(), TGEventHandlerObject)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tg_ui_widgets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.appc.tg_ui'`

- [ ] **Step 3: Implement the package**

`engine/appc/tg_ui/__init__.py`:

```python
"""Headless TG retained-mode widget tier.

SDK interface scripts build this tree (TGPane/TGIcon/TGParagraph + managers);
dauntless stores the state and never renders it — CEF panels observe selected
subtrees. Spec: docs/superpowers/specs/2026-06-12-tg-widget-tree-crew-menus-design.md
"""
from engine.appc.tg_ui.widgets import (  # noqa: F401
    TGPane, TGPane_Create, TGPane_Cast,
    TGIcon, TGIcon_Create, TGIcon_Cast,
    TGParagraph, TGParagraph_Create, TGParagraph_CreateW, TGParagraph_Cast,
    TGIconGroup,
    ensure_widget_id,
)
```

`engine/appc/tg_ui/widgets.py`:

```python
"""Core TG widgets — state-holding, render-free.

Conventions match engine/appc/characters.py STMenu/STButton: real classes,
(x, y) accepted and stored but never consulted (dauntless re-style decision,
2026-06-03 mirror spec), lenient casts, no _NamedStub leakage.
"""
from engine.appc.events import TGEventHandlerObject

# Monotonic per-process widget ids — used by CEF panels to address snapshot
# nodes back to live widgets. Never persisted.
_next_widget_id = 0


def ensure_widget_id(widget) -> int:
    """Assign (once) and return the widget's stable per-process id.

    Reads via __dict__ — TGObject.__getattr__ returns a _Stub (not raising
    AttributeError) for missing attributes, so a plain getattr-with-default
    would never see the default and would return the stub as the id.
    """
    global _next_widget_id
    wid = widget.__dict__.get("_widget_id")
    if wid is None:
        _next_widget_id += 1
        wid = _next_widget_id
        widget._widget_id = wid
    return wid


class TGPane(TGEventHandlerObject):
    """Container widget. Width/height/(x, y) stored, never rendered."""

    def __init__(self, width: float = 0.0, height: float = 0.0):
        super().__init__()
        self._width = float(width)
        self._height = float(height)
        self._children: list = []   # (child, x, y) tuples
        self._visible = True
        self._enabled = True

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append((child, float(x), float(y)))

    def GetChildren(self) -> list:
        return list(self._children)

    def DeleteChild(self, child) -> None:
        self._children = [(c, x, y) for (c, x, y) in self._children if c is not child]

    def KillChildren(self) -> None:
        self._children.clear()

    def SetVisible(self, *args) -> None:      self._visible = True
    def SetNotVisible(self, *args) -> None:   self._visible = False
    def IsVisible(self) -> int:               return 1 if self._visible else 0
    def SetEnabled(self, *args) -> None:      self._enabled = True
    def SetDisabled(self, *args) -> None:     self._enabled = False
    def IsEnabled(self) -> int:               return 1 if self._enabled else 0

    def GetWidth(self) -> float:              return self._width
    def GetHeight(self) -> float:             return self._height
    def Resize(self, *args) -> None:          pass
    def InteriorChangedSize(self, *args) -> None:  pass
    def SetNoFocus(self, *args) -> None:      pass
    def SetFocus(self, *args) -> None:        pass
    def CallNextHandler(self, _evt) -> None:  pass


class TGIcon(TGPane):
    """Atlas-icon widget — records (group, icon id, color), draws nothing."""

    def __init__(self, group_name: str = "", icon_id: int = 0, color=None):
        super().__init__()
        self._group_name = str(group_name)
        self._icon_id = int(icon_id)
        self._color = color

    def GetIconGroupName(self) -> str:  return self._group_name
    def GetIconID(self) -> int:         return self._icon_id
    def SetColor(self, color) -> None:  self._color = color


class TGParagraph(TGPane):
    """Text widget — holds the string; font/scale/color stored, unused."""

    def __init__(self, text: str = "", scale: float = 1.0, color=None):
        super().__init__()
        self._text = str(text)
        self._scale = float(scale)
        self._color = color

    def GetText(self) -> str:           return self._text
    def SetText(self, text) -> None:    self._text = str(text)
    # SDK W-variant setter name used by some callers.
    def SetStringW(self, text) -> None: self._text = str(text)
    def SetFont(self, *args) -> None:   pass
    def SetColor(self, color) -> None:  self._color = color


class TGIconGroup:
    """Texture-atlas icon group. Records SetIconLocation entries verbatim
    so a future renderer (or debug tooling) can read them; draws nothing."""

    ROTATE_0, ROTATE_90, ROTATE_180, ROTATE_270 = 0, 1, 2, 3
    MIRROR_NONE, MIRROR_HORIZONTAL, MIRROR_VERTICAL = 0, 1, 2

    def __init__(self, name: str = ""):
        self._name = str(name)
        self._textures: list = []          # loaded texture paths, index = handle
        self._locations: dict = {}         # slot -> (tex, x, y, w, h, rot, mirror)

    def GetName(self) -> str:
        return self._name

    def LoadIconTexture(self, path: str) -> int:
        self._textures.append(str(path))
        return len(self._textures) - 1

    def SetIconLocation(self, slot, texture, x, y, w, h,
                        rotation=ROTATE_0, mirror=MIRROR_NONE) -> None:
        self._locations[int(slot)] = (
            texture, int(x), int(y), int(w), int(h), int(rotation), int(mirror)
        )

    def GetIconLocation(self, slot):
        return self._locations.get(int(slot))


# ── Factories + lenient casts (engine/appc convention) ───────────────────────

def TGPane_Create(width=0.0, height=0.0) -> TGPane:
    return TGPane(width, height)


def TGPane_Cast(obj):
    return obj if isinstance(obj, TGPane) else None


def TGIcon_Create(group_name="", icon_id=0, color=None, *_extra) -> TGIcon:
    return TGIcon(group_name, icon_id, color)


def TGIcon_Cast(obj):
    return obj if isinstance(obj, TGIcon) else None


def TGParagraph_Create(text="", scale=1.0, color=None, *_extra) -> TGParagraph:
    return TGParagraph(text, scale, color)


def TGParagraph_CreateW(text="", scale=1.0, color=None, *_extra) -> TGParagraph:
    return TGParagraph(str(text), scale, color)


def TGParagraph_Cast(obj):
    return obj if isinstance(obj, TGParagraph) else None
```

Note: `TGIcon_Cast`/`TGParagraph_Cast` use strict isinstance (a `TGPane` is
not an icon), while `TGPane_Cast` accepts subclasses — matches the SDK class
hierarchy where icon/paragraph derive from pane.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tg_ui_widgets.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add engine/appc/tg_ui/ tests/unit/test_tg_ui_widgets.py
git commit -m "feat(tg-ui): headless TGPane/TGIcon/TGParagraph/TGIconGroup widgets"
```

---

### Task 3: tg_ui managers (font / icon / image / focus / root window)

**Files:**
- Create: `engine/appc/tg_ui/managers.py`
- Test: `tests/unit/test_tg_ui_managers.py`

- [ ] **Step 1: Write the failing test**

```python
"""TG UI managers — registration sinks with real storage (no stubs).
SDK call shapes from sdk/Build/scripts/Icons/FontsAndIcons.py and
Icons/LCARS_1024.py LoadLCARS_1024."""
from engine.appc.tg_ui.managers import (
    TGFontManager, TGIconManager, TGImageManager, TGFocusManager,
)
from engine.appc.tg_ui.widgets import TGIconGroup, TGPane


def test_font_manager_register_and_lookup():
    fm = TGFontManager()
    fm.RegisterFont("Crillee", 12, "Crillee12", "LoadCrillee12")
    handle = fm.GetFont("Crillee", 12)
    assert handle.GetHeight() == 12.0
    # Unknown lookups return a default handle, never None/stub.
    assert fm.GetFont("Nope", 99).GetHeight() == 99.0


def test_icon_manager_create_and_add_group():
    im = TGIconManager()
    g = im.CreateIconGroup("LCARS_1024")
    assert isinstance(g, TGIconGroup)
    im.AddIconGroup(g)
    assert im.GetIconGroup("LCARS_1024") is g
    # Canned 1024x768 screen (matches graphics_mode singleton).
    assert im.GetScreenWidth() == 1024.0
    assert im.GetScreenHeight() == 768.0


def test_focus_manager_holds_reference():
    fm = TGFocusManager()
    p = TGPane()
    fm.SetFocus(p)
    assert fm.GetFocus() is p


def test_image_manager_is_a_sink():
    im = TGImageManager()
    im.RegisterImage("splash", "data/splash.tga")  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tg_ui_managers.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` for managers.

- [ ] **Step 3: Implement managers**

`engine/appc/tg_ui/managers.py`:

```python
"""TG UI managers — real storage, no rendering, no _NamedStub leakage.

The point is that Icons/FontsAndIcons.py and the LCARS_* loaders run
against real objects so registrations are inspectable and failures loud.
"""
from engine.appc.tg_ui.widgets import TGIconGroup, TGPane


class TGFontHandle:
    """Plausible-metrics font handle: height = point size, fixed advance,
    so SDK layout math produces finite numbers headless."""

    def __init__(self, family: str, size: int):
        self._family = str(family)
        self._size = int(size)

    def GetHeight(self) -> float:
        return float(self._size)

    def GetStringWidth(self, text) -> float:
        # Fixed 0.6em advance per character — plausible, never zero-div.
        return 0.6 * self._size * len(str(text))


class TGFontManager:
    def __init__(self):
        # (family, size) -> (registered_name, load_func_name)
        self._fonts: dict = {}

    def RegisterFont(self, family, size, registered_name, load_func_name) -> None:
        self._fonts[(str(family), int(size))] = (str(registered_name),
                                                 str(load_func_name))

    def GetFont(self, family, size) -> TGFontHandle:
        return TGFontHandle(family, int(size))


class TGIconManager:
    def __init__(self):
        self._registered: dict = {}   # name -> (texture_base, load_func_name)
        self._groups: dict = {}       # name -> TGIconGroup

    def RegisterIconGroup(self, name, texture_base, load_func_name) -> None:
        self._registered[str(name)] = (str(texture_base), str(load_func_name))

    def CreateIconGroup(self, name) -> TGIconGroup:
        return TGIconGroup(str(name))

    def AddIconGroup(self, group: TGIconGroup) -> None:
        self._groups[group.GetName()] = group

    def GetIconGroup(self, name):
        return self._groups.get(str(name))

    # Canned 1024x768 — single source of truth is graphics_mode's singleton;
    # duplicated value here because the SDK asks both objects.
    def GetScreenWidth(self) -> float:  return 1024.0
    def GetScreenHeight(self) -> float: return 768.0


class TGImageManager:
    """Registration sink — SDK registers loose images; nothing reads back."""

    def __init__(self):
        self._images: dict = {}

    def RegisterImage(self, name, path, *args) -> None:
        self._images[str(name)] = str(path)


class TGFocusManager:
    def __init__(self):
        self._focused = None

    def SetFocus(self, widget, *args) -> None:
        self._focused = widget

    def GetFocus(self):
        return self._focused


# Module-level singletons re-exported by App.py.
g_kFontManager = TGFontManager()
g_kIconManager = TGIconManager()
g_kImageManager = TGImageManager()
g_kFocusManager = TGFocusManager()
g_kRootWindow = TGPane()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tg_ui_managers.py tests/unit/test_tg_ui_widgets.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add engine/appc/tg_ui/managers.py tests/unit/test_tg_ui_managers.py
git commit -m "feat(tg-ui): font/icon/image/focus managers + root window singletons"
```

---

### Task 4: graphics mode + TGUIModule_PixelAlignValue

**Files:**
- Create: `engine/appc/tg_ui/graphics_mode.py`
- Test: `tests/unit/test_tg_ui_graphics_mode.py`

- [ ] **Step 1: Write the failing test**

```python
"""Canned graphics mode. SDK call shapes:
  LCARS = __import__(App.GraphicsModeInfo_GetCurrentMode().GetLcarsModule())
  pcLCARS = App.GraphicsModeInfo_GetCurrentMode().GetLcarsString()
  v = App.TGUIModule_PixelAlignValue(v)
"""
from engine.appc.tg_ui.graphics_mode import (
    GraphicsModeInfo, GraphicsModeInfo_GetCurrentMode, TGUIModule_PixelAlignValue,
)


def test_current_mode_is_singleton():
    assert GraphicsModeInfo_GetCurrentMode() is GraphicsModeInfo_GetCurrentMode()


def test_mode_names_lcars_1024():
    mode = GraphicsModeInfo_GetCurrentMode()
    assert mode.GetLcarsModule() == "LCARS_1024"
    assert mode.GetLcarsString() == "LCARS_1024"


def test_mode_dimensions():
    mode = GraphicsModeInfo_GetCurrentMode()
    assert mode.GetWidth() == 1024
    assert mode.GetHeight() == 768


def test_pixel_align_value_is_identity():
    assert TGUIModule_PixelAlignValue(0.12345) == 0.12345


def test_lcars_module_actually_imports():
    mode = GraphicsModeInfo_GetCurrentMode()
    LCARS = __import__(mode.GetLcarsModule())
    assert LCARS.SCREEN_PIXEL_WIDTH == 1024.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tg_ui_graphics_mode.py -v`
Expected: FAIL with `ImportError` for graphics_mode.

- [ ] **Step 3: Implement**

`engine/appc/tg_ui/graphics_mode.py`:

```python
"""Canned display-mode answers for headless/CEF dauntless.

The SDK queries the mode only to pick a resolution-specific LCARS layout
module and to scale pixel layout we never render. Fixed 1024x768: LCARS_1024
is the layout the SDK ships for that mode (sdk/Build/scripts/Icons/).
"""


class GraphicsModeInfo:
    def GetLcarsModule(self) -> str:  return "LCARS_1024"
    def GetLcarsString(self) -> str:  return "LCARS_1024"
    def GetWidth(self) -> int:        return 1024
    def GetHeight(self) -> int:       return 768
    def GetBitDepth(self) -> int:     return 32


_current_mode = GraphicsModeInfo()


def GraphicsModeInfo_GetCurrentMode() -> GraphicsModeInfo:
    return _current_mode


def TGUIModule_PixelAlignValue(value):
    """Identity — pixel alignment is meaningless without a pixel grid."""
    return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tg_ui_graphics_mode.py -v`
Expected: all PASS (`test_lcars_module_actually_imports` exercises the
existing `_SDKFinder` rglob fallback — this is the bare-name regression pin).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/tg_ui/graphics_mode.py tests/unit/test_tg_ui_graphics_mode.py
git commit -m "feat(tg-ui): canned GraphicsModeInfo + PixelAlignValue identity"
```

---

### Task 5: ST widgets — STCharacterMenu, STWarpButton, SortedRegionMenu, panes, casts

**Files:**
- Create: `engine/appc/tg_ui/st_widgets.py`
- Modify: `engine/appc/characters.py` (add `CallNextHandler` no-op to `STMenu`)
- Test: `tests/unit/test_tg_ui_st_widgets.py`

- [ ] **Step 1: Write the failing test**

```python
"""ST stylized widgets used by Bridge/*MenuHandlers.CreateMenus().
Call shapes from sdk/Build/scripts/Bridge/HelmMenuHandlers.py:136-260."""
from engine.appc.characters import STButton, STMenu
from engine.appc.tg_ui.st_widgets import (
    STCharacterMenu, STCharacterMenu_CreateW,
    STWarpButton, STWarpButton_CreateW,
    SortedRegionMenu, SortedRegionMenu_CreateW,
    SortedRegionMenu_SetWarpButton, SortedRegionMenu_GetWarpButton,
    SortedRegionMenu_SetPauseSorting, SortedRegionMenu_ClearSetCourseMenu,
    STRoundedButton, STRoundedButton_CreateW, STRoundedButton_Cast,
    STSubPane, STSubPane_Create, STSubPane_Cast,
    STButton_Cast, STStylizedWindow_Cast, STToggle_Cast,
    _reset_module_state,
)
from engine.appc.windows import STStylizedWindow_CreateW


def setup_function(_):
    _reset_module_state()


def test_character_menu_is_an_stmenu():
    m = STCharacterMenu_CreateW("Hail")
    assert isinstance(m, STMenu)
    assert m.GetLabel() == "Hail"


def test_warp_button_holds_warp_time_and_course_menu():
    b = STWarpButton_CreateW("Warp")
    course = SortedRegionMenu_CreateW("Set Course")
    b.SetWarpTime(5)
    b.SetCourseMenu(course)
    assert b.GetWarpTime() == 5.0
    assert b.GetCourseMenu() is course


def test_sorted_region_menu_module_registry():
    b = STWarpButton_CreateW("Warp")
    SortedRegionMenu_SetWarpButton(b)
    assert SortedRegionMenu_GetWarpButton() is b
    SortedRegionMenu_SetPauseSorting(1)       # state sink, must not raise
    SortedRegionMenu_ClearSetCourseMenu()     # state sink, must not raise


def test_module_state_resets():
    SortedRegionMenu_SetWarpButton(STWarpButton_CreateW("Warp"))
    _reset_module_state()
    assert SortedRegionMenu_GetWarpButton() is None


def test_casts():
    btn = STButton("X")
    assert STButton_Cast(btn) is btn
    assert STButton_Cast(None) is None
    assert STButton_Cast("nope") is None
    win = STStylizedWindow_CreateW("Helm")
    assert STStylizedWindow_Cast(win) is win
    rb = STRoundedButton_CreateW("OK")
    assert STRoundedButton_Cast(rb) is rb
    sp = STSubPane_Create()
    assert STSubPane_Cast(sp) is sp
    assert STToggle_Cast(btn) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tg_ui_st_widgets.py -v`
Expected: FAIL with `ImportError` for st_widgets.

- [ ] **Step 3: Implement**

`engine/appc/tg_ui/st_widgets.py`:

```python
"""ST stylized widgets — headless subclasses of the characters.py menu
primitives plus the SortedRegionMenu module-function registry.

Warp/set-course *behaviour* is out of scope (spec non-goal); these classes
exist so Bridge/*MenuHandlers.CreateMenus() completes with real objects.
"""
from engine.appc.characters import STButton, STMenu
from engine.appc.tg_ui.widgets import TGPane
from engine.appc.windows import _STStylizedWindow


class STCharacterMenu(STMenu):
    """Crew-interaction submenu (Hail list, character dialog root)."""
    pass


class STToggle(STButton):
    """Two-state button (on/off). State sink in Phase 2 headless tier."""

    def __init__(self, label: str = "", event=None, flags: int = 0):
        super().__init__(label, event, flags)
        self._toggled = False

    def SetToggled(self, *args) -> None:    self._toggled = True
    def SetNotToggled(self, *args) -> None: self._toggled = False
    def IsToggled(self) -> int:             return 1 if self._toggled else 0


class STWarpButton(STButton):
    """Warp trigger button — stores config; warp execution is a follow-up."""

    def __init__(self, label: str = "", event=None, flags: int = 0):
        super().__init__(label, event, flags)
        self._warp_time = 0.0
        self._course_menu = None

    def SetWarpTime(self, t) -> None:     self._warp_time = float(t)
    def GetWarpTime(self) -> float:       return self._warp_time
    def SetCourseMenu(self, m) -> None:   self._course_menu = m
    def GetCourseMenu(self):              return self._course_menu


class SortedRegionMenu(STMenu):
    """Set-course region list. Sorting/pause flags recorded, unused."""

    def __init__(self, label: str = ""):
        super().__init__(label)
        self._pause_sorting = 0


class STRoundedButton(STButton):
    pass


class STSubPane(TGPane):
    pass


# ── Module-level registry (SDK: SortedRegionMenu_* module functions) ─────────

_warp_button: "STWarpButton | None" = None
_pause_sorting: int = 0


def _reset_module_state() -> None:
    """Test-only — clear module registry between tests."""
    global _warp_button, _pause_sorting
    _warp_button = None
    _pause_sorting = 0


def SortedRegionMenu_SetWarpButton(button) -> None:
    global _warp_button
    _warp_button = button


def SortedRegionMenu_GetWarpButton():
    return _warp_button


def SortedRegionMenu_SetPauseSorting(flag) -> None:
    global _pause_sorting
    _pause_sorting = int(flag)


def SortedRegionMenu_ClearSetCourseMenu(*args) -> None:
    pass


# ── Factories ────────────────────────────────────────────────────────────────

def STCharacterMenu_CreateW(label="", *_extra) -> STCharacterMenu:
    return STCharacterMenu(str(label))


def STWarpButton_CreateW(label="", event=None, flags=0) -> STWarpButton:
    return STWarpButton(str(label), event, flags)


def SortedRegionMenu_CreateW(label="", *_extra) -> SortedRegionMenu:
    return SortedRegionMenu(str(label))


def STRoundedButton_CreateW(label="", event=None, flags=0) -> STRoundedButton:
    return STRoundedButton(str(label), event, flags)


def STSubPane_Create(*args) -> STSubPane:
    return STSubPane()


# ── Strict-ish casts (None for wrong type — SDK null-guards these) ───────────

def STButton_Cast(obj):
    return obj if isinstance(obj, STButton) else None


def STStylizedWindow_Cast(obj):
    return obj if isinstance(obj, _STStylizedWindow) else None


def STRoundedButton_Cast(obj):
    return obj if isinstance(obj, STRoundedButton) else None


def STSubPane_Cast(obj):
    return obj if isinstance(obj, STSubPane) else None


def STToggle_Cast(obj):
    return obj if isinstance(obj, STToggle) else None
```

- [ ] **Step 4: Add `CallNextHandler` no-op to STMenu**

In `engine/appc/characters.py`, `STMenu` class, after the `Close` method
(`def Close(self, *args) -> None: pass`), add:

```python
    def CallNextHandler(self, _evt) -> None:
        # SDK handlers end with pMenu.CallNextHandler(pEvent) for chain
        # propagation (e.g. HelmMenuHandlers.AllStop:1524). No parent
        # window chain headless — explicit no-op instead of __getattr__ stub.
        pass
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tg_ui_st_widgets.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add engine/appc/tg_ui/st_widgets.py engine/appc/characters.py tests/unit/test_tg_ui_st_widgets.py
git commit -m "feat(tg-ui): STCharacterMenu/STWarpButton/SortedRegionMenu + casts"
```

---

### Task 6: TacticalControlWindow menu list

**Files:**
- Modify: `engine/appc/windows.py` (`TacticalControlWindow`, lines 14-40)
- Test: `tests/unit/test_tactical_window_menus.py`

- [ ] **Step 1: Write the failing test**

```python
"""TacticalControlWindow menu attachment — the CrewMenuPanel observation
surface. SDK: HelmMenuHandlers.CreateMenus does
  pTacticalControlWindow.AddChild(pHelmPane, 0.0, 0.0)
  pTacticalControlWindow.AddMenuToList(pHelmMenu)
"""
from engine.appc.windows import TacticalControlWindow
from engine.appc.characters import STTopLevelMenu


def setup_function(_):
    TacticalControlWindow._instance = None


def test_add_menu_to_list_and_read_back():
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    tactical = STTopLevelMenu("Tactical")
    tcw.AddMenuToList(helm)
    tcw.AddMenuToList(tactical)
    assert tcw.GetMenuList() == [helm, tactical]


def test_add_child_is_recorded():
    tcw = TacticalControlWindow.GetInstance()
    tcw.AddChild(object(), 0.0, 0.0)  # must not raise
    assert tcw.GetMenuList() == []    # children are not menus
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tactical_window_menus.py -v`
Expected: FAIL — `AddMenuToList` resolves to `_Stub` via `TGObject.__getattr__`
(call silently succeeds) and `GetMenuList()` returns a `_Stub`, so the `==` assert fails.

- [ ] **Step 3: Implement**

In `engine/appc/windows.py`, `TacticalControlWindow.__init__`, add two fields
and three methods:

```python
    def __init__(self):
        super().__init__()
        self._radar_display = None
        self._children: list = []      # (child, x, y) — recorded, not rendered
        self._menus: list = []         # STTopLevelMenu roots, in add order

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append((child, float(x), float(y)))

    def AddMenuToList(self, menu) -> None:
        if menu not in self._menus:
            self._menus.append(menu)

    def GetMenuList(self) -> list:
        return list(self._menus)
```

(Keep the existing `CallNextHandler` / radar accessors unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tactical_window_menus.py tests/unit/test_target_menu_bridge_subscription.py -v`
Expected: all PASS (second file guards existing TacticalControlWindow consumers).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/windows.py tests/unit/test_tactical_window_menus.py
git commit -m "feat(tg-ui): TacticalControlWindow records children + menu list"
```

---

### Task 7: App.py exports + FontsAndIcons real-registration test

**Files:**
- Modify: `App.py` (import block, near the existing `engine.appc.windows` import)
- Test: `tests/unit/test_tg_ui_app_exports.py`

- [ ] **Step 1: Write the failing test**

```python
"""Every tg_ui symbol the SDK references resolves to a real object on App,
and FontsAndIcons registers against real managers (not _NamedStub)."""
import sys
import App


REAL_SYMBOLS = [
    "TGPane", "TGPane_Create", "TGPane_Cast",
    "TGIcon", "TGIcon_Create", "TGIcon_Cast",
    "TGParagraph", "TGParagraph_Create", "TGParagraph_CreateW", "TGParagraph_Cast",
    "TGIconGroup",
    "g_kFontManager", "g_kIconManager", "g_kImageManager",
    "g_kFocusManager", "g_kRootWindow",
    "GraphicsModeInfo", "GraphicsModeInfo_GetCurrentMode",
    "TGUIModule_PixelAlignValue",
    "STCharacterMenu", "STCharacterMenu_CreateW",
    "STWarpButton", "STWarpButton_CreateW",
    "SortedRegionMenu", "SortedRegionMenu_CreateW",
    "SortedRegionMenu_SetWarpButton", "SortedRegionMenu_GetWarpButton",
    "SortedRegionMenu_SetPauseSorting", "SortedRegionMenu_ClearSetCourseMenu",
    "STRoundedButton", "STRoundedButton_CreateW", "STRoundedButton_Cast",
    "STSubPane", "STSubPane_Create", "STSubPane_Cast",
    "STButton_Cast", "STStylizedWindow_Cast", "STToggle_Cast",
]


def test_symbols_are_real_not_stubs():
    for name in REAL_SYMBOLS:
        obj = getattr(App, name)
        assert not isinstance(obj, App._Stub), name


def test_fonts_and_icons_registers_real_entries():
    # Re-import so registration runs against the real managers even if an
    # earlier test imported it when stubs were live.
    sys.modules.pop("FontsAndIcons", None)
    import FontsAndIcons  # noqa: F401
    assert ("Crillee", 12) in App.g_kFontManager._fonts
    assert "LCARS_1024" in App.g_kIconManager._registered


def test_lcars_1024_loader_runs_against_real_icon_group():
    sys.modules.pop("LCARS_1024", None)
    import LCARS_1024
    LCARS_1024.LoadLCARS_1024()
    g = App.g_kIconManager.GetIconGroup("LCARS_1024")
    assert g is not None
    assert g.GetIconLocation(10) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tg_ui_app_exports.py -v`
Expected: FAIL — `App.TGPane` etc. resolve to `_NamedStub` (module
`__getattr__`); `isinstance(obj, App._Stub)` is True.

- [ ] **Step 3: Wire exports in App.py**

In `App.py`, after the `from engine.appc.windows import (...)` block, add:

```python
from engine.appc.tg_ui.widgets import (
    TGPane, TGPane_Create, TGPane_Cast,
    TGIcon, TGIcon_Create, TGIcon_Cast,
    TGParagraph, TGParagraph_Create, TGParagraph_CreateW, TGParagraph_Cast,
    TGIconGroup,
)
from engine.appc.tg_ui.managers import (
    g_kFontManager, g_kIconManager, g_kImageManager,
    g_kFocusManager, g_kRootWindow,
)
from engine.appc.tg_ui.graphics_mode import (
    GraphicsModeInfo, GraphicsModeInfo_GetCurrentMode,
    TGUIModule_PixelAlignValue,
)
from engine.appc.tg_ui.st_widgets import (
    STCharacterMenu, STCharacterMenu_CreateW,
    STToggle, STToggle_Cast,
    STWarpButton, STWarpButton_CreateW,
    SortedRegionMenu, SortedRegionMenu_CreateW,
    SortedRegionMenu_SetWarpButton, SortedRegionMenu_GetWarpButton,
    SortedRegionMenu_SetPauseSorting, SortedRegionMenu_ClearSetCourseMenu,
    STRoundedButton, STRoundedButton_CreateW, STRoundedButton_Cast,
    STSubPane, STSubPane_Create, STSubPane_Cast,
    STButton_Cast, STStylizedWindow_Cast,
)
```

**Conflict check (do this, it bites):** `App.py` line ~239 defines
`class SortedRegionMenu(STMenu): pass` for `CT_SORTED_REGION_MENU`. Delete that
inline class — the `st_widgets` import above replaces it (same base class, so
`CT_SORTED_REGION_MENU = SortedRegionMenu` still points at an `STMenu`
subclass and the `isinstance` call sites keep working).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tg_ui_app_exports.py tests/unit/test_bridge_event_constants.py tests/unit/test_tg_ui_st_widgets.py -v`
Expected: all PASS

- [ ] **Step 5: Run a broader guard subset (App.py import-order regressions)**

Run: `uv run pytest tests/unit/test_player.py tests/unit/test_game.py tests/unit/test_target_menu_bridge_subscription.py tests/unit/test_sensors_panel.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add App.py tests/unit/test_tg_ui_app_exports.py
git commit -m "feat(tg-ui): export widget tier through App shim"
```

---

### Task 8: Integration — real HelmMenuHandlers.CreateMenus()

**Files:**
- Test: `tests/integration/test_helm_menu_creation.py`
- Possibly modify: `App.py` (additional ET_* constants discovered at import time — see Step 3 procedure)

- [ ] **Step 1: Write the integration test**

```python
"""Run the REAL sdk/Build/scripts/Bridge/HelmMenuHandlers.CreateMenus().

conftest pre-stubs Bridge.HelmMenuHandlers as a _StubModule (MissionLib
writes attributes onto it), so this test swaps in the real module and
restores the stub afterwards.
"""
import sys

import App
from engine.appc.windows import TacticalControlWindow
from engine.appc.target_menu import _reset_target_menu_singleton


def _fresh_real_helm():
    saved = sys.modules.pop("Bridge.HelmMenuHandlers", None)
    saved_bare = sys.modules.pop("HelmMenuHandlers", None)
    import Bridge.HelmMenuHandlers as real
    return real, saved, saved_bare


def _restore(saved, saved_bare):
    if saved is not None:
        sys.modules["Bridge.HelmMenuHandlers"] = saved
    if saved_bare is not None:
        sys.modules["HelmMenuHandlers"] = saved_bare


def test_create_menus_builds_helm_tree():
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    real, saved, saved_bare = _fresh_real_helm()
    try:
        real.CreateMenus()
        tcw = TacticalControlWindow.GetInstance()
        menus = tcw.GetMenuList()
        assert len(menus) >= 1
        helm = menus[0]
        labels = [c.GetLabel() for c in helm._children if hasattr(c, "GetLabel")]
        # TGL lookup may localize; assert on structure not exact strings:
        # helm menu has multiple children including a warp button and a
        # sorted-region set-course menu.
        from engine.appc.tg_ui.st_widgets import STWarpButton, SortedRegionMenu
        assert any(isinstance(c, STWarpButton) for c in helm._children)
        assert any(isinstance(c, SortedRegionMenu) for c in helm._children)
        assert len(labels) >= 5
        # The warp button registered itself in the module registry.
        from engine.appc.tg_ui.st_widgets import SortedRegionMenu_GetWarpButton
        assert SortedRegionMenu_GetWarpButton() is not None
    finally:
        _restore(saved, saved_bare)
```

- [ ] **Step 2: Run it and triage failures (expected on first run)**

Run: `uv run pytest tests/integration/test_helm_menu_creation.py -v -x`

This exercises a deep SDK import chain (`BridgeUtils`, `Characters.Graff`,
`Systems.Starbase12.Starbase12_S`, `MissionLib`, `BridgeHandlers`,
`BridgeMenus`). Likely failure classes and the fix for each:

1. **`AttributeError: ... object has no attribute 'X'` on a tg_ui/characters
   class** → add the method as a state-sink to that class, following the
   exact style of its siblings (store value or `pass`), with a comment citing
   the SDK file:line that calls it.
2. **An `App.ET_*` or `App.<CONSTANT>` assert-failure or stub leak** → add the
   constant to the Task 1 block in `App.py` (next free int, stay below 1200),
   and add its name to `BRIDGE_ET_NAMES` in
   `tests/unit/test_bridge_event_constants.py`.
3. **A missing `App.<Factory>_CreateW`/`_Cast` for an ST/TG widget** → add the
   class+factory to `st_widgets.py`/`widgets.py` per Task 2/5 patterns and
   export per Task 7.
4. **`g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")` returning
   stub strings** — acceptable: the test asserts structure, not labels. Do
   NOT chase TGL fidelity here.

Iterate `run → fix one failure class → re-run` until green. Every symbol
added must have a one-line SDK file:line citation comment.

- [ ] **Step 3: Run the full focused set**

Run: `uv run pytest tests/integration/test_helm_menu_creation.py tests/unit/test_bridge_event_constants.py tests/unit/test_tg_ui_app_exports.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add -A tests/ App.py engine/appc/
git commit -m "test(tg-ui): real HelmMenuHandlers.CreateMenus builds the helm tree"
```

---

### Task 9: CrewMenuPanel — outbound snapshot

**Files:**
- Create: `engine/ui/crew_menu_panel.py`
- Test: `tests/unit/test_crew_menu_panel.py`

- [ ] **Step 1: Write the failing test**

```python
"""CrewMenuPanel snapshot/diff/dispatch. Pattern: engine/appc/sdk_mirror_panel.py."""
import json

import App
from engine.appc.windows import TacticalControlWindow
from engine.appc.characters import STButton, STTopLevelMenu
from engine.ui.crew_menu_panel import CrewMenuPanel


def setup_function(_):
    TacticalControlWindow._instance = None


def _build_helm_with_button(event_type=None):
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    evt = App.TGIntEvent_Create()
    evt.SetEventType(event_type if event_type is not None else App.ET_ALL_STOP)
    evt.SetDestination(helm)
    btn = App.STButton_CreateW("All Stop", evt)
    helm.AddChild(btn)
    tcw.AddMenuToList(helm)
    return helm, btn


def test_payload_shape_and_ids():
    helm, btn = _build_helm_with_button()
    panel = CrewMenuPanel()
    payload = panel.render_payload()
    assert payload.startswith("setCrewMenus(")
    data = json.loads(payload[len("setCrewMenus("):-2])  # strip call + ");"
    assert len(data["menus"]) == 1
    root = data["menus"][0]
    assert root["label"] == "Helm"
    assert root["type"] == "menu"
    assert root["children"][0]["label"] == "All Stop"
    assert root["children"][0]["type"] == "button"
    assert isinstance(root["children"][0]["id"], int)
    assert root["children"][0]["enabled"] is True


def test_payload_dedups_until_state_changes():
    helm, btn = _build_helm_with_button()
    panel = CrewMenuPanel()
    assert panel.render_payload() is not None
    assert panel.render_payload() is None          # unchanged → no re-emit
    btn.SetDisabled()
    assert panel.render_payload() is not None      # change → re-emit


def test_invalidate_forces_reemission():
    _build_helm_with_button()
    panel = CrewMenuPanel()
    panel.render_payload()
    panel.invalidate()
    assert panel.render_payload() is not None


def test_panel_name():
    assert CrewMenuPanel().name == "crew-menu"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_crew_menu_panel.py -v`
Expected: FAIL with `ImportError` for crew_menu_panel.

- [ ] **Step 3: Implement (outbound half — dispatch_event stub returns False)**

`engine/ui/crew_menu_panel.py`:

```python
"""CrewMenuPanel — projects the STTopLevelMenu trees registered on
TacticalControlWindow into CEF, and routes clicks back as SDK events.

Outbound: walk TacticalControlWindow.GetMenuList() once per tick, snapshot
labels/flags/ids, diff, emit setCrewMenus(...). Inbound: resolve clicked id
to the live widget and fire its activation event (Task 10).

Spec: docs/superpowers/specs/2026-06-12-tg-widget-tree-crew-menus-design.md
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.appc.characters import STButton, STMenu
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.appc.windows import TacticalControlWindow
from engine.ui.panel import Panel

_logger = logging.getLogger(__name__)


class CrewMenuPanel(Panel):
    def __init__(self):
        super().__init__()
        self._last_pushed: Optional[str] = None
        self._widgets_by_id: dict = {}
        self._logged_unrecognised: set = set()

    @property
    def name(self) -> str:
        return "crew-menu"

    def render_payload(self) -> Optional[str]:
        self._widgets_by_id = {}
        menus = [
            self._snapshot_node(m)
            for m in TacticalControlWindow.GetInstance().GetMenuList()
        ]
        payload = json.dumps({"menus": [m for m in menus if m is not None]})
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setCrewMenus(" + payload + ");"

    def _snapshot_node(self, widget) -> Optional[dict]:
        if isinstance(widget, STMenu):
            node_type = "menu"
        elif isinstance(widget, STButton):
            node_type = "button"
        else:
            self._log_unrecognised_once(type(widget).__name__)
            return None
        wid = ensure_widget_id(widget)
        self._widgets_by_id[wid] = widget
        node = {
            "id": wid,
            "type": node_type,
            "label": widget.GetLabel(),
            "enabled": bool(widget.IsEnabled()),
            "visible": bool(widget.IsVisible()),
        }
        if isinstance(widget, STMenu):
            children = [self._snapshot_node(c) for c in widget._children]
            node["children"] = [c for c in children if c is not None]
        return node

    def dispatch_event(self, action: str) -> bool:
        return False  # inbound dispatch lands in the next commit

    def invalidate(self) -> None:
        self._last_pushed = None

    def _log_unrecognised_once(self, type_name: str) -> None:
        if type_name in self._logged_unrecognised:
            return
        self._logged_unrecognised.add(type_name)
        _logger.info("crew-menu: skipping unrecognised child type %s", type_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_crew_menu_panel.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add engine/ui/crew_menu_panel.py tests/unit/test_crew_menu_panel.py
git commit -m "feat(crew-menu): CrewMenuPanel outbound snapshot with diffing"
```

---

### Task 10: CrewMenuPanel — inbound click dispatch

**Files:**
- Modify: `engine/ui/crew_menu_panel.py`
- Test: `tests/unit/test_crew_menu_panel.py` (append)

- [ ] **Step 1: Write the failing tests (append to test_crew_menu_panel.py)**

```python
_clicks = []


def _record_all_stop(dest, event):
    _clicks.append((dest, event.GetEventType()))


def test_click_fires_buttons_stored_event_into_sdk_handler():
    _clicks.clear()
    helm, btn = _build_helm_with_button()
    helm.AddPythonFuncHandlerForInstance(
        App.ET_ALL_STOP, __name__ + "._record_all_stop")
    panel = CrewMenuPanel()
    panel.render_payload()                      # builds the id map
    wid = ensure_widget_id(btn)
    assert panel.dispatch_event(f"click:{wid}") is True
    assert _clicks == [(helm, App.ET_ALL_STOP)]


def test_click_also_fires_st_button_clicked_at_root_menu():
    _clicks.clear()
    helm, btn = _build_helm_with_button()
    helm.AddPythonFuncHandlerForInstance(
        App.ET_ST_BUTTON_CLICKED, __name__ + "._record_all_stop")
    panel = CrewMenuPanel()
    panel.render_payload()
    panel.dispatch_event(f"click:{ensure_widget_id(btn)}")
    assert (helm, App.ET_ST_BUTTON_CLICKED) in _clicks


def test_stale_click_id_is_dropped_not_raised():
    _build_helm_with_button()
    panel = CrewMenuPanel()
    panel.render_payload()
    assert panel.dispatch_event("click:999999") is True   # handled: dropped


def test_click_on_disabled_button_is_ignored():
    _clicks.clear()
    helm, btn = _build_helm_with_button()
    helm.AddPythonFuncHandlerForInstance(
        App.ET_ALL_STOP, __name__ + "._record_all_stop")
    btn.SetDisabled()
    panel = CrewMenuPanel()
    panel.render_payload()
    panel.dispatch_event(f"click:{ensure_widget_id(btn)}")
    assert _clicks == []
```

Also add `from engine.appc.tg_ui.widgets import ensure_widget_id` to the test
file imports.

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/unit/test_crew_menu_panel.py -v`
Expected: the four new tests FAIL (`dispatch_event` returns False); earlier ones still PASS.

- [ ] **Step 3: Implement dispatch**

Replace `dispatch_event` in `engine/ui/crew_menu_panel.py` with:

```python
    def dispatch_event(self, action: str) -> bool:
        if not action.startswith("click:"):
            return False
        try:
            wid = int(action[len("click:"):])
        except ValueError:
            _logger.info("crew-menu: malformed click action %r", action)
            return True
        widget = self._widgets_by_id.get(wid)
        if widget is None:
            # Menu rebuilt between frames — drop; next snapshot repairs the UI.
            _logger.info("crew-menu: stale click id %d dropped", wid)
            return True
        if not widget.IsEnabled():
            return True
        root = self._root_of(wid)
        if isinstance(widget, STButton):
            # Original engine order: per-button activation event, then
            # ET_ST_BUTTON_CLICKED at the owning top-level menu (the SDK
            # registers BridgeMenus.ButtonClicked there for click sounds).
            widget.SendActivationEvent()
            if root is not None:
                import App
                clicked = App.TGEvent_Create()
                clicked.SetEventType(App.ET_ST_BUTTON_CLICKED)
                clicked.SetDestination(root)
                clicked.SetSource(widget)
                App.g_kEventManager.AddEvent(clicked)
        return True

    def _root_of(self, wid: int):
        """Top-level menu whose subtree contains the widget id, else None."""
        for menu in TacticalControlWindow.GetInstance().GetMenuList():
            if self._contains(menu, wid):
                return menu
        return None

    def _contains(self, widget, wid: int) -> bool:
        # __dict__ read — TGObject.__getattr__ stubs missing attributes.
        if widget.__dict__.get("_widget_id") == wid:
            return True
        if isinstance(widget, STMenu):
            return any(self._contains(c, wid) for c in widget._children)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_crew_menu_panel.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add engine/ui/crew_menu_panel.py tests/unit/test_crew_menu_panel.py
git commit -m "feat(crew-menu): click dispatch fires stored SDK activation events"
```

---

### Task 11: CEF assets + host_loop registration

**Files:**
- Create: `native/assets/ui-cef/js/crew_menus.js`
- Create: `native/assets/ui-cef/css/crew_menus.css`
- Modify: `native/assets/ui-cef/hello.html` (slot + links, next to the sdk-mirror entries)
- Modify: `engine/host_loop.py` (~line 2230, with the other `registry.register(...)` calls)

No Python unit test (JS); verified by the existing panel-registration smoke
in Step 4 and visually via `/verify`-style run after Task 12.

- [ ] **Step 1: JS**

`native/assets/ui-cef/js/crew_menus.js` (model: `sdk_mirror.js` — global
`set*` function + `dauntlessEvent` emission):

```javascript
// CrewMenuPanel renderer — dauntless-styled menu bar for SDK bridge menus.
// Payload: {menus:[{id,type,label,enabled,visible,children:[...]}]}
let crewMenuOpenId = null;

function setCrewMenus(payload) {
  const slot = document.getElementById("crew-menu-bar");
  if (!slot) return;
  slot.innerHTML = "";
  for (const menu of payload.menus) {
    slot.appendChild(renderCrewMenu(menu));
  }
}

function renderCrewMenu(menu) {
  const wrap = document.createElement("div");
  wrap.className = "crew-menu" + (menu.id === crewMenuOpenId ? " open" : "");
  const title = document.createElement("div");
  title.className = "crew-menu-title" + (menu.enabled ? "" : " disabled");
  title.textContent = menu.label;
  title.onclick = () => {
    crewMenuOpenId = crewMenuOpenId === menu.id ? null : menu.id;
    wrap.classList.toggle("open");
  };
  wrap.appendChild(title);
  const drop = document.createElement("div");
  drop.className = "crew-menu-drop";
  for (const child of menu.children || []) {
    drop.appendChild(renderCrewMenuEntry(child));
  }
  wrap.appendChild(drop);
  return wrap;
}

function renderCrewMenuEntry(node) {
  const row = document.createElement("div");
  row.className = "crew-menu-entry " + node.type +
                  (node.enabled ? "" : " disabled");
  row.textContent = node.label;
  if (node.type === "button" && node.enabled) {
    row.onclick = () => dauntlessEvent("crew-menu/click:" + node.id);
  }
  if (node.type === "menu" && (node.children || []).length) {
    const sub = document.createElement("div");
    sub.className = "crew-menu-sub";
    for (const child of node.children) {
      sub.appendChild(renderCrewMenuEntry(child));
    }
    row.appendChild(sub);
  }
  return row;
}
```

- [ ] **Step 2: CSS**

`native/assets/ui-cef/css/crew_menus.css` — match the chrome of the existing
panels (inspect `css/sdk_mirror.css` for the palette variables in use and
reuse them; the structure below is the contract):

```css
#crew-menu-bar {
  position: absolute;
  top: 8px;
  left: 8px;
  display: flex;
  gap: 6px;
  z-index: 30; /* above scene, below pause menu */
}
.crew-menu { position: relative; }
.crew-menu-title {
  padding: 4px 12px;
  cursor: pointer;
  user-select: none;
}
.crew-menu-drop { display: none; position: absolute; top: 100%; left: 0; min-width: 160px; }
.crew-menu.open .crew-menu-drop { display: block; }
.crew-menu-entry { padding: 4px 12px; cursor: pointer; position: relative; }
.crew-menu-entry.disabled { opacity: 0.4; cursor: default; }
.crew-menu-sub { display: none; position: absolute; left: 100%; top: 0; min-width: 160px; }
.crew-menu-entry:hover > .crew-menu-sub { display: block; }
```

- [ ] **Step 3: hello.html slot + links**

In `native/assets/ui-cef/hello.html`, next to the existing sdk-mirror slot
and asset links, add:

```html
<div id="crew-menu-bar"></div>
```
```html
<link rel="stylesheet" href="css/crew_menus.css">
<script src="js/crew_menus.js"></script>
```

- [ ] **Step 4: Register the panel in host_loop**

In `engine/host_loop.py`, where the other panels are constructed/registered
(~line 2224-2235), add — always-on, NOT dev-gated, matching `sdk_mirror`:

```python
        from engine.ui.crew_menu_panel import CrewMenuPanel
        crew_menu_panel = CrewMenuPanel()
        registry.register(crew_menu_panel)
```

Run: `uv run pytest tests/host/test_host_loop_unit.py -v`
Expected: PASS (guards host_loop import/registration wiring).

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/ engine/host_loop.py
git commit -m "feat(crew-menu): CEF menu bar slot + panel registration"
```

---

### Task 12: Round-trip integration test — All Stop via CEF click

**Files:**
- Test: `tests/integration/test_crew_menu_round_trip.py`

- [ ] **Step 1: Write the test**

```python
"""End-to-end proof: real HelmMenuHandlers menu tree -> CrewMenuPanel
snapshot -> simulated CEF click on All Stop -> SDK handler runs ->
MissionLib.SetPlayerAI gives the player Stay AI.
"""
import json
import sys

import App
from engine.appc.windows import TacticalControlWindow
from engine.appc.ships import ShipClass_Create
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.core.game import Game, _set_current_game
from engine.ui.crew_menu_panel import CrewMenuPanel


def _fresh_real_helm():
    saved = sys.modules.pop("Bridge.HelmMenuHandlers", None)
    saved_bare = sys.modules.pop("HelmMenuHandlers", None)
    import Bridge.HelmMenuHandlers as real
    return real, saved, saved_bare


def _find_button(node, label):
    if node.get("type") == "button" and node["label"] == label:
        return node
    for child in node.get("children", []):
        hit = _find_button(child, label)
        if hit:
            return hit
    return None


def test_all_stop_click_gives_player_stay_ai():
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    game = Game()
    _set_current_game(game)
    player = ShipClass_Create("TestPlayer")
    App.Game_SetCurrentPlayer(player)
    player.SetAI(None)

    real, saved, saved_bare = _fresh_real_helm()
    try:
        real.CreateMenus()
        panel = CrewMenuPanel()
        payload = panel.render_payload()
        data = json.loads(payload[len("setCrewMenus("):-2])
        all_stop = None
        for menu in data["menus"]:
            all_stop = _find_button(menu, "All Stop")
            if all_stop:
                break
        # TGL may localize the label; fall back to structural lookup:
        # the All Stop button is the STButton whose stored event type is
        # ET_ALL_STOP.
        if all_stop is None:
            from engine.appc.characters import STButton
            for wid, w in panel._widgets_by_id.items():
                if (isinstance(w, STButton) and w._event is not None
                        and w._event.GetEventType() == App.ET_ALL_STOP):
                    all_stop = {"id": wid}
                    break
        assert all_stop is not None, "no All Stop button in snapshot"

        assert panel.dispatch_event("click:%d" % all_stop["id"]) is True

        ai = player.GetAI()
        assert ai is not None, "AllStop handler did not assign player AI"
    finally:
        if saved is not None:
            sys.modules["Bridge.HelmMenuHandlers"] = saved
        if saved_bare is not None:
            sys.modules["HelmMenuHandlers"] = saved_bare
        _set_current_game(None)
```

- [ ] **Step 2: Run and triage**

Run: `uv run pytest tests/integration/test_crew_menu_round_trip.py -v -x`

The click path runs `HelmMenuHandlers.AllStop` → `MissionLib.SetPlayerAI("Helm",
AI.Player.Stay.CreateAI(pPlayer))`. Triage rules, same discipline as Task 8:
fix missing symbols with cited state-sink additions; do NOT weaken the final
`player.GetAI() is not None` assertion — that is the round-trip proof. If
`MissionLib.SetPlayerAI` itself short-circuits headless (e.g. needs an
Episode/Mission), construct them via `engine.core.game.Episode`/`Mission` in
the test setup the same way `tests/unit/test_game.py` does.

- [ ] **Step 3: Run the whole feature's focused set**

Run: `uv run pytest tests/unit/test_bridge_event_constants.py tests/unit/test_tg_ui_widgets.py tests/unit/test_tg_ui_managers.py tests/unit/test_tg_ui_graphics_mode.py tests/unit/test_tg_ui_st_widgets.py tests/unit/test_tactical_window_menus.py tests/unit/test_tg_ui_app_exports.py tests/unit/test_crew_menu_panel.py tests/integration/test_helm_menu_creation.py tests/integration/test_crew_menu_round_trip.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_crew_menu_round_trip.py
git commit -m "test(crew-menu): All Stop CEF click round-trip through real SDK handler"
```

---

### Task 13: Visual verification + wrap-up

- [ ] **Step 1: Build + run the host and verify the menu bar renders**

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless
```

Expected: crew-menu bar appears top-left once a mission's `CreateMenus` has
run; clicking Helm opens the dropdown; All Stop halts the ship. If menus
never appear, check whether the active mission path actually calls
`Bridge.*MenuHandlers.CreateMenus` — if not, note it in the PR description as
the activation gap rather than forcing it from the panel.

- [ ] **Step 2: Use the finishing skill**

Invoke superpowers:finishing-a-development-branch to choose merge/PR/cleanup.
