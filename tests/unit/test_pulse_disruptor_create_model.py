"""Torpedo.CreateDisruptorModel + SetLifetime mirror the pulse-weapon SDK
projectile modules (sdk/Build/scripts/Tactical/Projectiles/PulseDisruptor.py).
BC builds disruptor bolts as a procedural two-color tapered-tube mesh (audited
weapon-firing-mechanics.md §5.5) — NOT torpedo-style textured quads — so
CreateDisruptorModel stores the authentic shell/core colors + length/width and
leaves the torpedo quad fields at their __init__ defaults (empty, unused until
the real tube render path lands).
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


def test_create_disruptor_model_stores_authentic_bolt_fields():
    t = Torpedo()
    shell = _color(0.172549, 1.0, 0.172549)
    core  = _color(0.639216, 1.0, 0.639216)
    t.CreateDisruptorModel(shell, core, 1.8, 0.15)
    assert t._is_disruptor is True
    assert t._shell_color is shell
    assert t._bolt_core_color is core
    assert t._bolt_length == 1.8
    assert t._bolt_width == 0.15
    # Torpedo quad fields stay at their __init__ defaults — the real tube
    # render path (later tasks) does not ride the textured-quad pass.
    assert t._core_texture == ""
    assert t._core_color is None
    assert t._core_size_a == 0.0
    assert t._core_size_b == 0.0
    assert t._glow_texture == ""
    assert t._glow_color is None
    assert t._num_flares == 0
    assert t._flares_texture == ""
    assert t._flares_color is None


def test_create_disruptor_model_coerces_numeric_types():
    t = Torpedo()
    t.CreateDisruptorModel(None, None, 2, 1)
    assert isinstance(t._bolt_length, float)
    assert isinstance(t._bolt_width, float)


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
    assert t._is_disruptor is True
    assert t._bolt_length == 1.8
    assert t._bolt_width == 0.15
    assert t._shell_color is not None
    assert t._bolt_core_color is not None
    # Quad fields untouched — disruptors don't ride the torpedo quad pass.
    assert t._core_texture == ""
    assert t._glow_texture == ""
    assert t._num_flares == 0


def test_create_disruptor_model_via_disruptor_script():
    """Disruptor.py (the non-pulse variant) passes length 2.0, width 0.2."""
    import importlib
    mod = importlib.import_module("Tactical.Projectiles.Disruptor")
    t = Torpedo()
    mod.Create(t)
    assert t._is_disruptor is True
    assert t._bolt_length == 2.0
    assert t._bolt_width == 0.2
