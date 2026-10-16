"""CreateControllerFX the NanoFX way (spec 2026-10-16 §8.4)."""
import importlib

import pytest

import App
from engine.appc import particles as P

NANO = "scripts/Custom/NanoFXv2/"


@pytest.fixture
def acts():
    return importlib.import_module("Custom.NanoFXv2.NanoFX_ScriptActions")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: 0)
    P.reset()
    yield
    P.reset()


def test_stub_emit_source_anchors_to_attach_owner(acts):
    ship = App.ShipClass_Create("Host")
    stub = App.TGModelUtils_CastNodeToAVObject(ship.GetNode())
    action = acts.CreateControllerFX(NANO + "ExplosionFX/Gfx/Explosions/Exp_Nano1.tga",
                                     stub, ship.GetNode(), 2.0,
                                     App.NiPoint3(0.0, 3.0, 0.0), App.NiPoint3(0.0, 0.0, 1.0))
    c = action.GetController()
    assert c._emit_from is ship
    assert (c._emit_pos.x, c._emit_pos.y, c._emit_pos.z) == (0.0, 3.0, 0.0)


def test_normal_type_keys_and_timing(acts):
    action = acts.CreateControllerFX(NANO + "ExplosionFX/Gfx/ExpFlash/ExpFlash1.tga",
                                     None, App.ShipClass_Create("K").GetNode(), 1.5,
                                     iTiming=15, fLifeTime=0.1, fRed=51.0, fGreen=102.0,
                                     fBlue=255.0, fBrightness=0.4)
    c = action.GetController()
    assert c._color_keys == [(0.1, 1.0, 1.0, 1.0), (0.4, 0.2, 0.4, 1.0), (1.0, 0.0, 0.0, 0.0)]
    assert c._alpha_keys == [(0.0, 1.0), (0.7, 0.5), (1.0, 0.0)]
    assert c._size_keys == [(0.0, 1.5), (1.0, 1.5)]
    assert c._emit_life == 1.0 and c._effect_life_time == pytest.approx(1.1)
    assert c._blend_mode == 1


def test_debris_type_uses_a_debris_controller(acts):
    action = acts.CreateControllerFX(NANO + "ExplosionFX/Gfx/Debris/nano_debris1a.tga",
                                     None, App.ShipClass_Create("D").GetNode(), 4.0,
                                     fLifeTime=30.0, sType="Debris", fDamping=0.1)
    c = action.GetController()
    assert isinstance(c, P.DebrisParticleController)
    assert c._roll_rate > 0.0 and c._damping == 0.1


def test_gravity_is_accepted_and_ignored(acts):
    acts.CreateControllerFX(NANO + "ExplosionFX/Gfx/Particles/Sparks.tga", None,
                            App.ShipClass_Create("G").GetNode(), vGravity=App.NiPoint3(0, 0, -9))


def test_niPoint3_is_a_real_point():
    p = App.NiPoint3(1.0, 2.0, 3.0)
    assert (p.x, p.y, p.z) == (1.0, 2.0, 3.0)
