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

    def __init__(self, label: str = ""):
        super().__init__(label)
        self._sub_pane: "STSubPane | None" = None

    def GetSubPane(self) -> "STSubPane":
        # SDK TacticalMenuHandlers.CreateOrdersStatusDisplay:644 calls
        # App.STSubPane_Cast(pPopupMenu.GetSubPane()).SetExpandToFillParent(0)
        # to opt out of the sub-pane's fill-to-parent layout behaviour.
        # Headless: return a stable STSubPane so the cast succeeds.
        if self._sub_pane is None:
            self._sub_pane = STSubPane()
        return self._sub_pane

    def Open(self, *_args) -> None:   pass
    def Close(self, *_args) -> None:  pass
    def GetDesiredSize(self, size_out=None) -> None:
        # TacticalMenuHandlers:673,677: pMenu.GetDesiredSize(kSize)
        # kSize is an App.NiPoint2; set x/y to 0.0 to avoid layout errors.
        if size_out is not None and hasattr(size_out, "x"):
            size_out.x = 0.0
            size_out.y = 0.0


class STToggle(STButton):
    """Two-state button (on/off). State sink in Phase 2 headless tier."""

    def __init__(self, label: str = "", event=None, flags: int = 0):
        super().__init__(label, event, flags)
        self._toggled = False

    def SetToggled(self, *args) -> None:    self._toggled = True
    def SetNotToggled(self, *args) -> None: self._toggled = False
    def IsToggled(self) -> int:             return 1 if self._toggled else 0
    def GetToggleState(self) -> int:        return self.IsToggled()


class STWarpButton(STButton):
    """Warp trigger button — stores config; warp execution is a follow-up."""

    def __init__(self, label: str = "", event=None, flags: int = 0):
        super().__init__(label, event, flags)
        self._warp_time = 0.0
        self._course_menu = None
        self._destination = None

    def SetWarpTime(self, t) -> None:     self._warp_time = float(t)
    def GetWarpTime(self) -> float:       return self._warp_time
    def SetCourseMenu(self, m) -> None:   self._course_menu = m
    def GetCourseMenu(self):              return self._course_menu
    # Destination is read in SDK truth-branches and string comparisons
    # (BridgeHandlers.py:1409, E6M1/E6M5/E7M6 warp handlers) — must be a
    # real falsy default, never a truthy _Stub.
    def SetDestination(self, dest) -> None:  self._destination = dest
    def GetDestination(self):                return self._destination


class SortedRegionMenu(STMenu):
    """Set-course region list. Sorting/pause flags recorded, unused.

    `region` is the SDK region-module string (e.g. "Systems.Vesuvi.Vesuvi4")
    passed as the 2nd arg of SortedRegionMenu_CreateW — the warp destination
    module. Retained so the offline catalog baker can record it.
    """

    def __init__(self, label: str = "", region=None):
        super().__init__(label)
        self._pause_sorting = 0
        self._region = str(region) if region is not None else None

    def GetRegionModule(self):
        return self._region

    def ClearInfo(self, *args) -> None:
        # Region-info reset on set-course rebuild (Systems/Utils.py:70).
        pass


class STRoundedButton(STButton):
    pass


class STSubPane(TGPane):
    def SetExpandToFillParent(self, *_args) -> None:
        # TacticalMenuHandlers:644 opts out of fill-to-parent layout.
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


def SortedRegionMenu_IsSortingPaused() -> int:
    # Systems/Utils.py:32 branches on `if not bPaused:` — must return the
    # real flag, not a truthy stub.
    return _pause_sorting


# ── Factories ────────────────────────────────────────────────────────────────

def STCharacterMenu_CreateW(label="", *_extra) -> STCharacterMenu:
    return STCharacterMenu(str(label))


def STWarpButton_CreateW(label="", event=None, flags=0) -> STWarpButton:
    return STWarpButton(str(label), event, flags)


def STToggle_CreateW(label="", default=0, label_on="", event_on=None,
                     label_off="", event_off=None, *_extra) -> STToggle:
    """SDK signature (BridgeUtils.py:76): STToggle_CreateW(pName, iDefault,
    pNameOn, pOnEvent, pNameOff, pOffEvent)."""
    t = STToggle(str(label), event_on)
    t._label_on = str(label_on)
    t._label_off = str(label_off)
    t._event_on = event_on
    t._event_off = event_off
    if default:
        t.SetToggled()
    return t


def SortedRegionMenu_CreateW(label="", region=None, *_extra) -> SortedRegionMenu:
    return SortedRegionMenu(str(label), region)


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


def STWarpButton_Cast(obj):
    return obj if isinstance(obj, STWarpButton) else None


def SortedRegionMenu_Cast(obj):
    """Lenient pass-through, same rationale as characters.STMenu_Cast:
    SDK chains the result without null-guarding (Systems/Utils.py:70
    `pSystemMenu.ClearInfo()`, MissionLib.py:2613 `assert pMenu`), and the
    input is often a plain STMenu auto-vivified by GetSubmenuW. Real
    SortedRegionMenus cast cleanly; other objects flow through so their
    TGObject stub-__getattr__ absorbs the follow-up calls."""
    if isinstance(obj, SortedRegionMenu):
        return obj
    if obj is None:
        return None
    return obj
