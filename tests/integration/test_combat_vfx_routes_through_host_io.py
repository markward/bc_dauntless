"""The combat-advance VFX publish routes the 7 per-frame descriptor-list
setters through engine.host_io wrappers, not through a raw host= module.

Task 3 of the host_io façade refactor: _advance_combat used to call
`host.set_torpedoes(...)` etc. on a raw _dauntless_host module. It now calls
host_io.set_torpedoes(...) so the manifest-validated façade owns every native
touch. These tests patch the host_io wrappers and assert the combat step drives
them (no fake host module needed for the setters)."""
from unittest.mock import patch

import pytest

from engine import host_io
from engine.appc.math import TGPoint3
from engine.host_loop import _advance_combat


@pytest.fixture(autouse=True)
def clear_torpedo_registry():
    from engine.appc import projectiles
    projectiles._active.clear()
    yield
    projectiles._active.clear()


def _capture_setter(name, calls):
    def _fn(data):
        calls[name] = list(data)
    return _fn


def test_advance_combat_routes_all_seven_vfx_setters_through_host_io():
    calls = {}
    names = ("set_torpedoes", "set_dynamic_lights", "set_shockwaves",
             "set_hit_vfx", "set_particle_emitters", "set_phaser_beams",
             "set_tractor_beams")
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


def test_advance_combat_publishes_torpedo_descriptors_via_host_io():
    from engine.appc.projectiles import Torpedo, register

    t = Torpedo()
    t._position = TGPoint3(1.0, 2.0, 3.0)
    t._velocity = TGPoint3(0.0, 0.0, 0.0)
    t._ttl = 30.0
    t._age = 0.0
    t._source_ship = None
    t._damage = 10.0
    register(t)

    captured = {}
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        with patch.object(host_io, "set_torpedoes",
                          lambda data: captured.setdefault("torps", list(data))):
            _advance_combat([], dt=0.0, ship_instances=None)

    assert "torps" in captured, "host_io.set_torpedoes was never called"
    assert len(captured["torps"]) == 1
    entry = captured["torps"][0]
    assert entry["position"] == pytest.approx((1.0, 2.0, 3.0))
    # Task 2: every descriptor also carries the disruptor-bolt fields,
    # unconditionally, alongside the torpedo-quad fields — the C++ parser
    # (Task 3) reads every key regardless of family.
    for key in ("id", "is_disruptor", "forward", "shell_color",
                "bolt_core_color", "bolt_length", "bolt_width"):
        assert key in entry, f"{key!r} missing from torpedo descriptor"
    assert entry["id"] == t._id
    assert entry["is_disruptor"] is False
    # t._velocity is (0, 0, 0) above -> zero-velocity fallback.
    assert entry["forward"] == pytest.approx((0.0, 0.0, 1.0))


def test_advance_combat_publishes_dynamic_light_descriptors_via_host_io():
    import App
    from engine.appc.projectiles import Torpedo, register

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
    t._position = TGPoint3(1.0, 2.0, 3.0)
    t._velocity = TGPoint3(0.0, 0.0, 0.0)
    register(t)

    captured = {}
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        with patch.object(
            host_io, "set_dynamic_lights",
            lambda data: captured.setdefault("lights", list(data)),
        ):
            _advance_combat([], dt=0.0, ship_instances=None)

    assert "lights" in captured, "host_io.set_dynamic_lights was never called"
    assert len(captured["lights"]) == 1
    entry = captured["lights"][0]
    assert entry["position"] == pytest.approx((1.0, 2.0, 3.0))
    assert set(entry.keys()) == {"position", "color", "radius", "intensity"}
