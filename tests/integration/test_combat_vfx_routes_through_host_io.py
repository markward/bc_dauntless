"""The combat-advance VFX publish routes the 6 per-frame descriptor-list
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


def test_advance_combat_routes_all_six_vfx_setters_through_host_io():
    calls = {}
    names = ("set_torpedoes", "set_shockwaves", "set_hit_vfx",
             "set_particle_emitters", "set_phaser_beams", "set_tractor_beams")
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
    assert captured["torps"][0]["position"] == pytest.approx((1.0, 2.0, 3.0))
