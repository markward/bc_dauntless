"""Glow region state and the hull emissive scale cross into C++ only on change.

`ShipGlowController.update` and `_sync_instance_transforms` used to resend the
same dim/edge/flicker, impulse gain and emissive scale for every region of
every ship, every frame (native motion phase 3b). The guards must never
swallow a real edge: a state change after a long quiet stretch, a dev forced
glow state, a moving impulse pulse, or a ship going dark when it dies.
"""
from engine import dev_light_preview, host_io, host_loop
from engine.appc import subsystem_glow as sg
from engine.core.native_transform_buffer import NativeTransformBuffer

from tests.unit.test_render_transform_binding import _Obj
from tests.unit.test_subsystem_glow import (
    _AIShip, _FakeRenderer, _ImpulseSub, _Point, _Pod, _Ship)


def _impulse_only(pod=None):
    impulse = pod or _Pod(_Point(0.0, -0.98, -0.45), radius=0.25)
    rend = _FakeRenderer(results=[0])
    ctrl = sg.ShipGlowController(
        rend, instance_id=7, ship=_Ship(None, impulse, None))
    return ctrl, rend, impulse


def _ai_impulse(setpoint):
    impulse = _ImpulseSub(_Point(0.0, -0.98, -0.45), max_speed=10.0)
    ship = _AIShip(None, impulse, None, setpoint=setpoint)
    rend = _FakeRenderer(results=[0])
    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    return ctrl, rend, ship


def test_healthy_region_dim_is_pushed_once():
    ctrl, rend, _ = _impulse_only()
    for k in range(10):
        ctrl.update(now=float(k))
    assert rend.dim_calls == [(7, 0, 1.0, -1.0, 0.0)]


def test_disable_after_many_quiet_frames_pushes_the_edge():
    ctrl, rend, impulse = _impulse_only()
    for k in range(50):
        ctrl.update(now=k * 0.1)
    impulse.disabled = True
    ctrl.update(now=20.0)
    assert len(rend.dim_calls) == 2
    assert rend.dim_calls[-1] == (7, 0, 0.0, 20.0, 1.0)


def test_disabled_then_healthy_pushes_both_edges():
    ctrl, rend, impulse = _impulse_only()
    ctrl.update(now=1.0)
    impulse.disabled = True
    ctrl.update(now=2.0)
    ctrl.update(now=3.0)
    impulse.disabled = False
    ctrl.update(now=4.0)
    ctrl.update(now=5.0)
    assert rend.dim_calls == [
        (7, 0, 1.0, -1.0, 0.0),
        (7, 0, 0.0, 2.0, 1.0),
        (7, 0, 1.0, -1.0, 0.0),
    ]


def test_dev_forced_state_change_pushes(monkeypatch):
    ctrl, rend, _ = _impulse_only()
    ctrl.update(now=1.0)
    ctrl.update(now=2.0)
    monkeypatch.setattr(dev_light_preview, "forced_glow_state",
                        lambda: sg.DESTROYED)
    ctrl.update(now=3.0)
    ctrl.update(now=4.0)
    assert rend.dim_calls == [
        (7, 0, 1.0, -1.0, 0.0),
        (7, 0, 0.0, 3.0, 0.0),
    ]


def test_idle_impulse_gain_is_pushed_once():
    ctrl, rend, _ = _ai_impulse(setpoint=(0.0, (0, 1, 0), 0))
    for k in range(10):
        ctrl.update(now=k * 0.1)
    assert len(rend.gain_calls) == 1
    assert rend.gain_calls[0][2] == 1.0


def test_moving_impulse_gain_still_pulses_every_frame():
    ctrl, rend, _ = _ai_impulse(setpoint=(10.0, (0, 1, 0), 0))
    for now in (0.0, 0.1, 0.2):
        ctrl.update(now=now)
    gains = [c[2] for c in rend.gain_calls]
    assert len(gains) == 3
    assert len(set(gains)) == 3


def test_settle_threshold_is_1e_3():
    assert sg.IMPULSE_SETTLE_EPS == 1e-3


def test_eased_throttle_settles_to_zero_and_stops_pushing():
    ctrl, rend, ship = _ai_impulse(setpoint=(10.0, (0, 1, 0), 0))
    ctrl.update(now=0.0)
    ship._setpoint = (0.0, (0, 1, 0), 0)
    now = 0.0
    # tau 0.35 s: 10 s of 0.1 s steps eases the throttle far below 1e-3.
    for _ in range(100):
        now += 0.1
        ctrl.update(now=now)
    assert ctrl._eased_frac == 0.0
    before = len(rend.gain_calls)
    for _ in range(5):
        now += 0.1
        ctrl.update(now=now)
    assert len(rend.gain_calls) == before


class _EmissiveRenderer:
    def __init__(self):
        self.emissive_calls = []

    def set_world_transform(self, iid, mat):
        pass

    def set_emissive_scale(self, iid, scale):
        self.emissive_calls.append((iid, scale))

    def set_visible(self, iid, visible):
        pass

    def nebula_lightning_enabled(self):
        return False


class _MortalObj(_Obj):
    dead = False

    def IsDying(self):
        return False

    def IsDead(self):
        return self.dead


def test_emissive_scale_pushed_on_change_only(monkeypatch):
    monkeypatch.setattr(host_io, "set_instance_transform_slot",
                        lambda *a: True)
    r = _EmissiveRenderer()
    player = _MortalObj()
    other = _MortalObj(x=5.0)
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.ship_instances[other] = 2
    session.player = player
    buf = NativeTransformBuffer()

    def _sync():
        host_loop._sync_instance_transforms(
            r, session, player, buf, 0.5, game_time=1.0, model_scale=2.0)

    _sync()
    _sync()
    assert sorted(r.emissive_calls) == [(1, 1.0), (2, 1.0)]

    other.dead = True
    _sync()
    _sync()
    assert sorted(r.emissive_calls) == [(1, 1.0), (2, 0.0), (2, 1.0)]


def test_emissive_scale_guard_is_pruned_with_the_ship(monkeypatch):
    monkeypatch.setattr(host_io, "set_instance_transform_slot",
                        lambda *a: True)
    r = _EmissiveRenderer()
    player = _MortalObj()
    other = _MortalObj(x=5.0)
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.ship_instances[other] = 2
    session.player = player
    host_loop._sync_instance_transforms(
        r, session, player, NativeTransformBuffer(), 0.5,
        game_time=1.0, model_scale=2.0)
    del session.ship_instances[other]
    host_loop._sync_instance_transforms(
        r, session, player, NativeTransformBuffer(), 0.5,
        game_time=1.0, model_scale=2.0)
    assert set(session.emissive_scales) == {1}
