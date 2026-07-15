"""Torpedo.CreateDisruptorModel + SetLifetime mirror the pulse-weapon SDK
projectile modules (sdk/Build/scripts/Tactical/Projectiles/PulseDisruptor.py).
Pulse bolts reuse the torpedo render fields (core+glow textured quads, no
flares) so they ride the existing torpedo render pass with no renderer change.
"""
import App
from engine.appc.projectiles import Torpedo


def _color(r, g, b, a=1.0):
    c = App.TGColorA()
    c.SetRGBA(r, g, b, a)
    return c


def test_set_lifetime_sets_ttl():
    t = Torpedo()
    assert t._ttl == 60.0  # default
    t.SetLifetime(8.0)
    assert isinstance(t._ttl, float) and t._ttl == 8.0


def test_create_disruptor_model_maps_onto_quad_fields():
    t = Torpedo()
    shell = _color(0.172549, 1.0, 0.172549)
    core  = _color(0.639216, 1.0, 0.639216)
    t.CreateDisruptorModel(shell, core, 1.8, 0.15)
    assert t._core_color  is core
    assert t._core_size_a == 1.8
    assert t._core_size_b == 0.15
    assert t._glow_color  is shell
    assert t._num_flares  == 0
    assert t._core_texture
    assert t._glow_texture
    assert t._flares_texture == ""
    assert t._flares_color is None


def test_create_disruptor_model_coerces_numeric_types():
    t = Torpedo()
    t.CreateDisruptorModel(None, None, 2, 1)
    assert isinstance(t._core_size_a, float)
    assert isinstance(t._core_size_b, float)
    assert isinstance(t._glow_size_a, float)
    assert isinstance(t._glow_size_b, float)


def test_create_disruptor_model_via_pulse_disruptor_script():
    """Run the actual SDK PulseDisruptor.Create against a fresh Torpedo and
    confirm our Torpedo is populated as the script encodes it."""
    import importlib
    mod = importlib.import_module("Tactical.Projectiles.PulseDisruptor")
    t = Torpedo()
    mod.Create(t)
    assert t._damage == 220.0
    assert t._ttl == 8.0
    assert t._guidance_lifetime == 0.0
    assert t._core_size_a == 1.8
    assert t._core_size_b == 0.15
    assert t._num_flares == 0
    assert t._core_texture.endswith(".tga")
    assert t._glow_texture.endswith(".tga")
