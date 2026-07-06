"""Canned display-mode answers for headless/CEF dauntless.

The SDK queries the mode only to pick a resolution-specific LCARS layout
module and to scale pixel layout we never render. Fixed 1024x768: LCARS_1024
is the layout the SDK ships for that mode (sdk/Build/scripts/Icons/).
"""


class GraphicsModeInfo:
    # Resolution enum — SDK compares GetCurrentResolution() against these
    # (17 call sites: EngineerMenuHandlers, TacticalControlWindow, Maelstrom
    # E1M1/E1M2/E2M0, ...). Sequential ints in SDK declaration order.
    RES_640x480   = 0
    RES_800x600   = 1
    RES_1024x768  = 2
    RES_1280x1024 = 3
    RES_1600x1200 = 4

    def GetLcarsModule(self) -> str:  return "LCARS_1024"
    def GetLcarsString(self) -> str:  return "LCARS_1024"
    def GetWidth(self) -> int:        return 1024
    def GetHeight(self) -> int:       return 768
    def GetBitDepth(self) -> int:     return 32

    def GetCurrentResolution(self) -> int:
        return self.RES_1024x768

    # Size of one pixel in normalized layout coordinates — SDK widget
    # layout math (StylizedWindow.py:430/521, PowerDisplay, ShieldsDisplay).
    def GetPixelWidth(self) -> float:  return 1.0 / 1024.0
    def GetPixelHeight(self) -> float: return 1.0 / 768.0


_current_mode = GraphicsModeInfo()


def GraphicsModeInfo_GetCurrentMode() -> GraphicsModeInfo:
    return _current_mode


def TGUIModule_PixelAlignValue(value, *_axis):
    """Identity — pixel alignment is meaningless without a pixel grid.

    SDK callers pass an optional axis flag as a 2nd arg (PowerDisplay
    CreateLegendElbows: PixelAlignValue(v, 0)); it is ignored headless."""
    return value
