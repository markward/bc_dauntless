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
