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
    assert rend.gain_calls == []
    assert len(rend.impulse_calls) == 1
    _iid, _idx, start, target, _t0, powered, _gate = rend.impulse_calls[0]
    assert (start, target, powered) == (0.0, 0.0, True)


def test_moving_impulse_pushes_once_per_target_change():
    # The pulse and the ease run in C++ from the game clock (glow_impulse.h),
    # so a held throttle is ONE push, however many frames it is held for.
    ctrl, rend, ship = _ai_impulse(setpoint=(10.0, (0, 1, 0), 0))
    for now in (0.0, 0.1, 0.2):
        ctrl.update(now=now)
    assert rend.gain_calls == []
    assert rend.impulse_calls == [
        (7, 0, 1.0, 1.0, 0.0, True, sg.IMPULSE_AFT_AXIS)]
    # A new commanded target re-bases the ease at the value it had reached.
    ship._setpoint = (5.0, (0, 1, 0), 0)
    ctrl.update(now=0.3)
    ctrl.update(now=0.4)
    assert len(rend.impulse_calls) == 2
    _iid, _idx, start, target, t0, powered, _gate = rend.impulse_calls[1]
    assert (start, target, t0, powered) == (1.0, 0.5, 0.3, True)
    ship._setpoint = (10.0, (0, 1, 0), 0)
    ctrl.update(now=0.5)
    _iid, _idx, start, target, t0, _p, _gate = rend.impulse_calls[2]
    assert start == sg.eased_frac(1.0, 0.5, 0.3, 0.5)
    assert (target, t0) == (1.0, 0.5)


def test_impulse_push_on_power_gate_flip():
    ctrl, rend, ship = _ai_impulse(setpoint=(10.0, (0, 1, 0), 0))
    ctrl.update(now=0.0)
    ship._impulse.disabled = True
    ctrl.update(now=1.0)
    ctrl.update(now=2.0)
    ship._impulse.disabled = False
    ctrl.update(now=3.0)
    assert [c[5] for c in rend.impulse_calls] == [True, False, True]
    assert rend.gain_calls == []


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
    assert ctrl.eased_frac(now) == 0.0
    assert len(rend.impulse_calls) == 2     # spawn + the stop command
    for _ in range(5):
        now += 0.1
        ctrl.update(now=now)
    assert len(rend.impulse_calls) == 2
    assert rend.gain_calls == []


def _count_glow_state(monkeypatch):
    calls = []
    real = sg.glow_state

    def counting(sub):
        calls.append(sub)
        return real(sub)
    monkeypatch.setattr(sg, "glow_state", counting)
    return calls


def test_ai_controller_polls_at_20hz(monkeypatch):
    for iid in range(8):
        impulse = _ImpulseSub(_Point(0.0, -0.98, -0.45), max_speed=10.0)
        ship = _AIShip(None, impulse, None, setpoint=(10.0, (0, 1, 0), 0))
        ctrl = sg.ShipGlowController(_FakeRenderer(results=[0]),
                                     instance_id=iid, ship=ship)
        calls = _count_glow_state(monkeypatch)
        for k in range(10):
            ctrl.update(now=k / 60.0)
        assert 2 <= len(calls) <= 4, (iid, len(calls))


def test_player_controller_polls_every_frame(monkeypatch):
    ctrl, _rend, _ = _impulse_only()
    calls = _count_glow_state(monkeypatch)
    for k in range(10):
        ctrl.update(now=k / 60.0, throttle_frac=0.5, is_player=True)
    assert len(calls) == 10


def test_ai_damage_edge_lands_within_one_poll():
    # Accepted latency (spec §2.3): an AI ship's flicker starts at most one
    # 20 Hz poll late -- the edge time is the detection time.
    for iid in range(4):
        for drop_frame in range(1, 12):
            impulse = _ImpulseSub(_Point(0.0, -0.98, -0.45), max_speed=10.0)
            impulse.GetConditionPercentage = lambda: impulse.condition
            impulse.condition = 1.0
            ship = _AIShip(None, impulse, None, setpoint=(0.0, (0, 1, 0), 0))
            rend = _FakeRenderer(results=[0])
            ctrl = sg.ShipGlowController(rend, instance_id=iid, ship=ship)
            pushed_at = None
            for k in range(40):
                now = k / 60.0
                if k == drop_frame:
                    impulse.condition = 0.95
                ctrl.update(now=now)
                if pushed_at is None and rend.dim_calls[-1][4] == 1.0:
                    pushed_at = now
            assert pushed_at is not None, (iid, drop_frame)
            assert pushed_at - drop_frame / 60.0 <= sg.AI_GLOW_POLL_S + 1e-9, (
                iid, drop_frame, pushed_at)


def test_time_going_backwards_snaps_and_repolls():
    ctrl, rend, ship = _ai_impulse(setpoint=(10.0, (0, 1, 0), 0))
    ctrl.update(now=5.0)
    ship._setpoint = (0.0, (0, 1, 0), 0)
    ctrl.update(now=1.0)                     # mission swap / reset
    assert rend.impulse_calls[-1][2:5] == (0.0, 0.0, 1.0)


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
