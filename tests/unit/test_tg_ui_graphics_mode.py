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
