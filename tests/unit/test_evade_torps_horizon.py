"""EvadeTorps dodges only torpedoes that would hit within 20 s (engine.evade_torps_horizon).

BC's AI.PlainAI.EvadeTorps asks for every torpedo closing within 3600 s, and
its PickRandomVector weighs each one alike whatever its time to impact (the
fTime/20 term is the same for every candidate vector). A torpedo a minute
out pulled the dodge as hard as one about to hit.
"""
import pytest

import App
from engine import evade_torps_horizon
from engine.appc import projectiles
from engine.appc.ai import PlainAI_Create
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


@pytest.fixture
def evade_cls():
    import AI.PlainAI.EvadeTorps as mod
    cls = mod.EvadeTorps
    bc = cls.__dict__["fDangerTimeThreshold"]
    yield cls
    cls.fDangerTimeThreshold = bc
    if "_dauntless_bc_danger_time" in cls.__dict__:
        delattr(cls, "_dauntless_bc_danger_time")


@pytest.fixture
def space():
    App.g_kSetManager._sets.clear()
    projectiles._active.clear()
    s = App.SetClass_Create()
    s.SetName("S")
    App.g_kSetManager._sets["S"] = s
    yield s
    projectiles._active.clear()
    App.g_kSetManager._sets.clear()


def _ship(space):
    s = ShipClass()
    s._hull = HullSubsystem("H")
    s._hull.SetMaxCondition(1000.0)
    s._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    s._impulse_engine_subsystem.SetMaxSpeed(120.0)
    space.AddObjectToSet(s, "Ours")
    return s


def _torp(space, y, vy):
    t = projectiles.Torpedo()
    t.SetTranslateXYZ(0.0, y, 0.0)
    t._velocity = TGPoint3(0.0, vy, 0.0)
    projectiles.register(t)
    if t.GetContainingSet() is None:
        space.AddObjectToSet(t, "Torp%d" % t._id)
    return t


def test_install_caps_the_danger_time_at_20_seconds(evade_cls):
    assert evade_cls.fDangerTimeThreshold == 3600.0
    assert evade_torps_horizon.install() is True
    assert evade_cls.fDangerTimeThreshold == evade_torps_horizon.EVADE_HORIZON_S == 20.0
    assert evade_cls._dauntless_bc_danger_time == 3600.0
    assert evade_torps_horizon.install() is False


def test_a_torpedo_beyond_20_seconds_is_not_dodged(evade_cls, space):
    evade_torps_horizon.install()
    ship = _ship(space)
    near = _torp(space, 500.0, -50.0)     # hits in 10 s
    _torp(space, 1500.0, -50.0)           # hits in 30 s
    plain = PlainAI_Create(ship, "Evade")
    plain.SetScriptModule("EvadeTorps")
    inst = plain.GetScriptInstance()
    inst.UpdateTorpInfo(ship)
    assert list(inst.dTorpInfo) == [near.GetObjID()]


def test_without_the_cap_both_are_dodged(evade_cls, space):
    ship = _ship(space)
    _torp(space, 500.0, -50.0)
    _torp(space, 1500.0, -50.0)
    plain = PlainAI_Create(ship, "Evade")
    plain.SetScriptModule("EvadeTorps")
    inst = plain.GetScriptInstance()
    inst.UpdateTorpInfo(ship)
    assert len(inst.dTorpInfo) == 2
