"""kind:native (shock_ring -> procedural shockwave) and kind:none
(spec 2026-10-16 §7.5)."""
import App
from engine.appc import particles as P
from engine.appc import shockwaves

RING = "scripts/Custom/NanoFXv2/ExplosionFX/Gfx/NovaRing/Nova_Ring2a.tga"
BLANK = "scripts/Custom/NanoFXv2/SpecialFX/Gfx/Blinker/Blank.tga"


def _ring_controller(ship):
    c = P.AnimTSParticleController_Create()
    c.CreateTarget(RING)
    c.AddColorKey(0.1, 1.0, 1.0, 1.0)
    c.AddColorKey(0.5, 0.2, 0.4, 1.0)
    c.AddColorKey(1.0, 0.0, 0.0, 0.0)
    c.AddSizeKey(0.0, 12.0)
    c.AddSizeKey(1.0, 12.0)
    c.SetEmitLife(64 / 15.0)
    c.SetEmitFromObject(ship)
    c.SetEmitPositionAndDirection(App.TGPoint3(0.0, 2.0, 0.0), App.TGPoint3(0.0, 0.0, 0.0))
    return c


def test_native_ring_spawns_a_tinted_shockwave_not_an_emitter():
    shockwaves.reset()
    P.reset()
    ship = App.ShipClass_Create("Nova")
    ship.SetTranslateXYZ(10.0, 0.0, 0.0)
    P.EffectAction_Create(_ring_controller(ship)).Start()
    assert P.active_count() == 0
    (sw,) = shockwaves.render_data()
    assert sw["max_radius"] == 12.0
    assert abs(sw["lifetime"] - 64 / 15.0) < 1e-9
    assert sw["tint"] == (0.2, 0.4, 1.0)
    cx, cy, cz = sw["world_center"]
    assert abs(cx - 10.0) < 1e-6 and abs(cy - 2.0) < 1e-6
    shockwaves.reset()


def test_none_kind_never_emits():
    P.reset()
    c = P.AnimTSParticleController_Create()
    c.CreateTarget(BLANK)
    P.EffectAction_Create(c).Start()
    assert P.active_count() == 0


def test_unknown_native_effect_logs_once_per_name(capsys):
    P.reset()
    for effect in ("plasma_arc", "plasma_arc", "other_thing"):
        c = P.AnimTSParticleController_Create()
        c.__dict__["_library_kind"] = "native"
        c._native = {"effect": effect}
        P.EffectAction_Create(c).Start()
    err = capsys.readouterr().err
    assert err.count("plasma_arc") == 1
    assert err.count("other_thing") == 1
    assert P.active_count() == 0


def test_default_tint_is_white():
    shockwaves.reset()
    shockwaves.spawn((0.0, 0.0, 0.0), 5.0, 1.0)
    assert shockwaves.render_data()[0]["tint"] == (1.0, 1.0, 1.0)
    shockwaves.reset()
