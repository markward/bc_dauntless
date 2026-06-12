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
