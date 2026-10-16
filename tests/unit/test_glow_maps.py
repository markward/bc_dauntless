"""DisableGlowAlphaMaps + LODModelManager glow/specular flags
(spec 2026-10-16 §6.2, §6.3)."""
import App
from engine import host_loop
from engine.appc import glow_maps, running_lights


def _ship(name="GlowShip"):
    return App.ShipClass_Create(name)


def test_disable_glow_alpha_maps_darkens_only_that_ship():
    a, b = _ship("A"), _ship("B")
    a.DisableGlowAlphaMaps()
    assert glow_maps.is_dark(a)
    assert not glow_maps.is_dark(b)


def test_global_glow_off_darkens_everything_and_on_clears_disables():
    a, b = _ship("A"), _ship("B")
    a.DisableGlowAlphaMaps()
    App.g_kLODModelManager.SetGlowMapsEnabled(0)
    assert App.g_kLODModelManager.AreGlowMapsEnabled() == 0
    assert glow_maps.is_dark(a) and glow_maps.is_dark(b)
    App.g_kLODModelManager.SetGlowMapsEnabled(1)
    assert App.g_kLODModelManager.AreGlowMapsEnabled() == 1
    # ASSUMPTION (spec §6.3): re-enabling clears per-object disables.
    assert not glow_maps.is_dark(a)


def test_setting_glow_on_while_on_keeps_disables():
    a = _ship("A")
    a.DisableGlowAlphaMaps()
    App.g_kLODModelManager.SetGlowMapsEnabled(1)
    assert glow_maps.is_dark(a)


def test_enable_object_relights_one_ship():
    a = _ship("A")
    a.DisableGlowAlphaMaps()
    glow_maps.enable_object(a)
    assert not glow_maps.is_dark(a)


def test_specular_flag_is_stored():
    assert App.g_kLODModelManager.AreSpecularMapsEnabled() == 1
    App.g_kLODModelManager.SetSpecularMapsEnabled(0)
    assert App.g_kLODModelManager.AreSpecularMapsEnabled() == 0


def test_emissive_scale_for():
    s = _ship("E")
    assert host_loop._emissive_scale_for(s, False, 1.7) == 1.0
    assert host_loop._emissive_scale_for(s, True, 1.7) == 1.7
    s.DisableGlowAlphaMaps()
    assert host_loop._emissive_scale_for(s, True, 1.7) == 0.0


def test_running_lights_go_out_with_glow():
    s = _ship("R")
    assert running_lights.level_for(s, 0.0, 0.0, 0.0) == 1.0
    s.DisableGlowAlphaMaps()
    assert running_lights.level_for(s, 0.0, 0.0, 0.0) == 0.0
