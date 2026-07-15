"""Torpedo.CreateTorpedoModel mirrors sdk/Build/scripts/Tactical/Projectiles/
PhotonTorpedo.py:22-45 — 14 args populate visual fields. SetDamage /
SetDamageRadiusFactor / SetGuidanceLifetime / SetMaxAngularAccel /
SetNetType complete the per-projectile init surface.
"""
import App
from engine.appc.projectiles import Torpedo


def _color(r, g, b, a=1.0):
    c = App.TGColorA()
    c.SetRGBA(r, g, b, a)
    return c


def test_create_torpedo_model_stores_all_visual_fields():
    t = Torpedo()
    core_color   = _color(1.0, 0.99, 0.39)
    glow_color   = _color(1.0, 0.25, 0.0)
    flares_color = glow_color
    t.CreateTorpedoModel(
        "data/Textures/Tactical/TorpedoCore.tga",   core_color, 0.2, 1.2,
        "data/Textures/Tactical/TorpedoGlow.tga",   glow_color, 3.0, 0.3, 0.6,
        "data/Textures/Tactical/TorpedoFlares.tga", flares_color, 8, 0.7, 0.4,
    )
    assert t._core_texture   == "data/Textures/Tactical/TorpedoCore.tga"
    assert t._core_color     is core_color
    assert t._core_size_a    == 0.2
    assert t._core_size_b    == 1.2
    assert t._glow_texture   == "data/Textures/Tactical/TorpedoGlow.tga"
    assert t._glow_color     is glow_color
    assert t._glow_size_a    == 3.0
    assert t._glow_size_b    == 0.3
    assert t._glow_size_c    == 0.6
    assert t._flares_texture == "data/Textures/Tactical/TorpedoFlares.tga"
    assert t._flares_color   is flares_color
    assert t._num_flares     == 8
    assert t._flares_size_a  == 0.7
    assert t._flares_size_b  == 0.4
    assert t._is_disruptor   is False


def test_create_torpedo_model_coerces_numeric_types():
    t = Torpedo()
    t.CreateTorpedoModel("core", None, 1, 2,
                          "glow", None, 3, 4, 5,
                          "flares", None, 8.0, 6, 7)
    assert isinstance(t._core_size_a, float)
    assert isinstance(t._num_flares, int) and t._num_flares == 8


def test_set_damage_setters_coerce():
    t = Torpedo()
    t.SetDamage(500)
    t.SetDamageRadiusFactor(0.13)
    t.SetGuidanceLifetime(6.0)
    t.SetMaxAngularAccel(0.15)
    assert isinstance(t._damage, float) and t._damage == 500.0
    assert t._damage_radius_factor == 0.13
    assert t._guidance_lifetime == 6.0
    assert t._max_angular_accel == 0.15


def test_set_net_type_is_noop_accept():
    """Multiplayer.SpeciesToTorp.PHOTON etc. — accepted but ignored in PR 2b."""
    t = Torpedo()
    t.SetNetType(123)  # must not raise


def test_create_torpedo_model_via_photon_script():
    """Run the actual SDK PhotonTorpedo.Create against a fresh Torpedo and
    confirm the values match what the script encodes (PhotonTorpedo.py:22-50)."""
    import importlib
    mod = importlib.import_module("Tactical.Projectiles.PhotonTorpedo")
    t = Torpedo()
    mod.Create(t)
    assert t._core_texture.endswith("TorpedoCore.tga")
    assert t._core_size_a == 0.2
    assert t._glow_size_a == 3.0
    assert t._num_flares == 8
    assert t._damage == 500.0
    assert t._guidance_lifetime == 6.0
    assert t._max_angular_accel == 0.15
