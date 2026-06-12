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
