"""AI acquires a cloaked ship inside its sensor bubble — INTENTIONAL divergence.

**The gap this closes.** Stage 4 made cloak a range contest, but only on two of
the three AI surfaces. Acquisition stayed absolute, because
`AI/Preprocessors.py:1444-1450` — inside `SelectTarget.FindGoodTarget`, pure SDK
code — does an unconditional `if pCloakSystem.IsCloaked(): continue`, downstream
of our sensor-gated candidate enumeration. Measured live by Mark 2026-08-17 and
then in a probe: `FindGoodTarget` returned None at EVERY distance, including
1 GU (0.18 km), so no normal combat AI could ever start engaging a cloaked
player. Only `StarbaseAttack.GetTargets` (stations) lacked the skip.

**The shape of the fix** (`ai_sensor_gate._wrap_find_good_target`): the SDK path
runs untouched and wins whenever it answers, so uncloaked enemies keep their
existing priority. Only when the SDK declines do we re-pick from the
already-sensor-gated enumeration, scoring with the SDK's OWN `GetTargetRating`.
No SDK logic is duplicated.

**The toggle needs no code here.** With ENHANCED_SENSOR_CONTEST off, `can_detect`
rejects cloaked contacts at any range, so the gated enumeration hands the
fallback nothing and stock BC's absolute behaviour returns on its own. That is
asserted below — if someone "helpfully" adds a flag check to the wrapper, these
tests still pass, but the module regains a rule it deliberately does not own.
"""
import App
import pytest

from engine.appc import sensor_detection as sd
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.ai_sensor_gate import install_ai_sensor_gate
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, ShieldSubsystem, CloakingSubsystem, SensorSubsystem,
)
from tests.helpers.cloak_geometry import inside_gu, outside_gu


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    install_ai_sensor_gate()
    yield
    _reset_app_state()


def _kitted_ship(x, y, z, cloak=False, sensor_range=None):
    """Real engine objects, not fakes. Mirrors
    tests/unit/test_select_target_drops_cloaked.py::_kitted_ship, plus an
    optional REAL SensorSubsystem so the observer's bubble is a Galaxy's rather
    than the much larger sensor-less FALLBACK_RANGE_GU."""
    s = ShipClass()
    s.SetTranslateXYZ(x, y, z)
    s._hull = HullSubsystem("H")
    s._hull.SetMaxCondition(1000.0)
    s._shield_subsystem = ShieldSubsystem("Shd")
    if cloak:
        s.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    if sensor_range is not None:
        sen = SensorSubsystem("Sensors")
        sen._max_condition = 100.0
        sen._condition = 100.0
        sen.SetBaseSensorRange(sensor_range)
        s.SetSensorSubsystem(sen)
    return s


def _wire_select_target(ours, *target_names):
    from AI.Preprocessors import SelectTarget
    pp = PreprocessingAI_Create(ours, "SelectPP")
    pp._has_focus = True
    grp = ObjectGroup()
    for n in target_names:
        grp.AddName(n)
    inst = SelectTarget(grp)
    inst.pCodeAI = pp
    inst.dDamageReceived = {}
    inst.pEventHandler = App.TGPythonInstanceWrapper()
    inst.pEventHandler.SetPyWrapper(inst)
    pp.SetPreprocessingMethod(inst, "Update")
    return inst, pp


def _scene(distance_gu, cloak=True, extra=None):
    """Observer with a Galaxy's 2000 GU sensors at the origin and a bandit at
    *distance_gu* on +x. *extra* adds a second contact as (name, distance, cloak).
    Returns (select_target_instance, bandit, extras_by_name)."""
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ours = _kitted_ship(0, 0, 0, sensor_range=2000.0)
    ours.SetName("Ours")
    pSet.AddObjectToSet(ours, "Ours")

    bandit = _kitted_ship(distance_gu, 0, 0, cloak=cloak)
    bandit.SetName("Bandit")
    pSet.AddObjectToSet(bandit, "Bandit")
    if cloak:
        bandit.GetCloakingSubsystem().InstantCloak()

    names = ["Bandit"]
    extras = {}
    if extra is not None:
        ename, edist, ecloak = extra
        e = _kitted_ship(edist, 0, 0, cloak=ecloak)
        e.SetName(ename)
        pSet.AddObjectToSet(e, ename)
        if ecloak:
            e.GetCloakingSubsystem().InstantCloak()
        names.append(ename)
        extras[ename] = e

    inst, _pp = _wire_select_target(ours, *names)
    return inst, bandit, extras


def test_ai_acquires_a_cloaked_ship_inside_the_bubble():
    """THE BUG THIS FILE EXISTS FOR. Before the fix this returned None at every
    distance, so an AI never began engaging a cloaked player."""
    inst, bandit, _ = _scene(inside_gu())
    assert inst.FindGoodTarget() == "Bandit"


def test_ai_still_ignores_a_cloaked_ship_outside_the_bubble():
    """The bubble is the whole limit — beyond it, stock BC behaviour stands and
    cloak remains a working escape."""
    inst, _bandit, _ = _scene(outside_gu())
    assert inst.FindGoodTarget() is None


def test_uncloaked_target_keeps_its_sdk_priority():
    """The SDK path wins whenever it answers. A visible enemy FARTHER away than
    a cloaked one must still be chosen, because the fallback only runs when the
    SDK declines outright — otherwise this change would quietly re-rank every
    ordinary engagement in the game."""
    inst, _bandit, _extras = _scene(inside_gu(),
                                    extra=("Visible", 800.0, False))
    assert inst.FindGoodTarget() == "Visible"


def test_dead_cloaked_ship_is_not_acquired():
    """The fallback keeps the SDK's own dead/dying filter — it only replaces the
    cloak rule."""
    inst, bandit, _ = _scene(inside_gu())
    bandit.SetDying(True)          # the real engine mechanism (objects.py:742)
    assert bandit.IsDying() == 1
    assert inst.FindGoodTarget() is None


def test_contest_off_restores_absolute_cloak_with_no_flag_check_here(monkeypatch):
    """Stock BC returns WITHOUT this module consulting the flag: can_detect
    rejects the cloaked contact during enumeration, so the fallback sees nothing.
    Patched on sensor_detection deliberately — see the module docstring."""
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    inst, _bandit, _ = _scene(inside_gu())
    assert inst.FindGoodTarget() is None


def test_offline_sensors_acquire_nothing_even_point_blank():
    """`r <= 0.0` precedes the cloak term, so wrecked sensors mean no bubble at
    all rather than a flat floor's worth of x-ray vision."""
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = _kitted_ship(0, 0, 0, sensor_range=2000.0)
    ours.SetName("Ours")
    ours.GetSensorSubsystem()._condition = 20.0     # below the 25% cutoff
    pSet.AddObjectToSet(ours, "Ours")
    bandit = _kitted_ship(1.0, 0, 0, cloak=True)
    bandit.SetName("Bandit")
    pSet.AddObjectToSet(bandit, "Bandit")
    bandit.GetCloakingSubsystem().InstantCloak()
    inst, _pp = _wire_select_target(ours, "Bandit")
    assert inst.FindGoodTarget() is None
