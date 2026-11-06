"""The combat-advance VFX publish: every per-frame descriptor list is pushed.

Task 3 of the host_io façade refactor: _advance_combat used to call
`host.set_torpedoes(...)` etc. on a raw _dauntless_host module. It now calls
host_io's wrappers so the manifest-validated façade owns every native touch.
Since phase 6 follow-up 4 the torpedoes, the dynamic lights and both beam
feeds are built natively (native_combat.torpedo_feed / beam_feed write their
vectors themselves, with no Python fallback); the shockwaves, hit VFX and
particles still go through host_io's setters."""
from unittest.mock import patch

import pytest

from engine import host_io
from engine.appc.math import TGPoint3
from engine.host_loop import _advance_combat
from tests.helpers.viewed_set import place_in_viewed_set, release_viewed_set


@pytest.fixture(autouse=True)
def clear_torpedo_registry():
    from engine.appc import projectiles
    projectiles._active.clear()
    yield
    projectiles._active.clear()
    release_viewed_set()


def _capture_setter(name, calls):
    def _fn(data):
        calls[name] = list(data)
    return _fn


def _h():
    if host_io._h is None:
        pytest.skip("native host not built")
    return host_io._h


def test_advance_combat_publishes_every_vfx_feed(monkeypatch):
    from engine.appc import native_combat
    calls = {}
    names = ("set_shockwaves", "set_hit_vfx", "set_particle_emitters")
    native = []
    for feed in ("torpedo_feed", "beam_feed"):
        orig = getattr(native_combat, feed)

        def spy(*a, _orig=orig, _n=feed, **k):
            native.append(_n)
            return _orig(*a, **k)

        monkeypatch.setattr(native_combat, feed, spy)
    _h()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        with patch.multiple(
            host_io,
            **{n: _capture_setter(n, calls) for n in names},
        ):
            # The setters must still fire (they no longer gate on a raw host
            # module). ship_instances=None is fine — no hits queued.
            _advance_combat([], dt=0.1, ship_instances=None)

    for n in names:
        assert n in calls, f"host_io.{n} was not called by _advance_combat"
    # Both native feeds ran, and pushed (True: a native host).
    assert native == ["torpedo_feed", "beam_feed"]
    assert native_combat.torpedo_feed_counts()["native"] == 1
    assert native_combat.beam_feed_counts()["native"] == 1


def test_advance_combat_publishes_torpedo_descriptors_natively():
    from engine.appc.projectiles import Torpedo, register
    h = _h()

    # No Create*Model: the default visual record (Torpedo.__init__).
    t = Torpedo()
    t.SetTranslateXYZ(1.0, 2.0, 3.0)
    place_in_viewed_set(t)   # the render feeds carry only the viewed frame
    t._velocity = TGPoint3(0.0, 0.0, 0.0)
    t._ttl = 30.0
    t._age = 0.0
    t._source_ship = None
    t._damage = 10.0
    register(t)

    try:
        with patch("engine.audio.tg_sound.TGSoundManager.instance"):
            _advance_combat([], dt=0.0, ship_instances=None)
        rows = h.torpedoes_debug()
    finally:
        h.set_torpedoes([])
        h.set_dynamic_lights([])

    assert len(rows) == 1
    (pos, *_r) = rows[0]
    assert tuple(pos) == pytest.approx((1.0, 2.0, 3.0))
    # The disruptor-bolt fields ride with the torpedo-quad fields (struct
    # order: ... age 15, id 16, is_disruptor 17, forward 18, ...).
    assert rows[0][16] == t._id
    assert rows[0][17] is False
    # t._velocity is (0, 0, 0) above -> zero-velocity fallback.
    assert tuple(rows[0][18]) == pytest.approx((0.0, 0.0, 1.0))


def test_advance_combat_publishes_dynamic_light_descriptors_natively():
    import App
    from engine.appc.projectiles import Torpedo, register
    h = _h()

    def _color(r, g, b, a=1.0):
        c = App.TGColorA()
        c.SetRGBA(r, g, b, a)
        return c

    t = Torpedo()
    core_color = _color(1.0, 0.99, 0.39)
    glow_color = _color(1.0, 0.25, 0.0)
    t.CreateTorpedoModel(
        "data/Textures/Tactical/TorpedoCore.tga",   core_color, 0.2, 1.2,
        "data/Textures/Tactical/TorpedoGlow.tga",   glow_color, 3.0, 0.3, 0.6,
        "data/Textures/Tactical/TorpedoFlares.tga", glow_color, 8, 0.7, 0.4,
    )
    t.SetTranslateXYZ(1.0, 2.0, 3.0)
    place_in_viewed_set(t)   # the render feeds carry only the viewed frame
    t._velocity = TGPoint3(0.0, 0.0, 0.0)
    register(t)

    try:
        with patch("engine.audio.tg_sound.TGSoundManager.instance"):
            _advance_combat([], dt=0.0, ship_instances=None)
        lights = h.dynamic_lights_debug()
    finally:
        h.set_torpedoes([])
        h.set_dynamic_lights([])

    assert len(lights) == 1
    # A point light (pos_a == pos_b) at the torpedo, the glow's colour.
    assert tuple(lights[0][0]) == pytest.approx((1.0, 2.0, 3.0))
    assert tuple(lights[0][1]) == pytest.approx((1.0, 2.0, 3.0))
    assert tuple(lights[0][2]) == pytest.approx((1.0, 0.25, 0.0))
