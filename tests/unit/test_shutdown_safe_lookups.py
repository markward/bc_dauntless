"""Lookups called from Condition.__del__ must survive interpreter shutdown.

SDK Condition objects (ConditionSingleShieldBelow, ConditionSystemBelow,
others) call back into the engine from their ``__del__`` methods to remove
watchers. If those engine functions perform runtime imports, they raise
``ImportError: sys.meta_path is None`` once Python starts tearing down the
import system, producing pages of noise at process exit.

We model the shutdown state by poisoning ``sys.modules`` so any subsequent
``import`` statement raises ``ImportError`` — same failure mode as a real
shutdown. The lookups must degrade to safe defaults instead of raising.
"""
import sys

import pytest

import App
from engine.appc.ai import ProximityCheck
from engine.appc.sets import SetClass, _NullSet
from engine.appc.objects import ObjectGroup


@pytest.fixture
def app_import_poisoned():
    saved = sys.modules.get("App")
    sys.modules["App"] = None  # any subsequent `import App` now raises ImportError
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop("App", None)
        else:
            sys.modules["App"] = saved


@pytest.fixture
def sets_import_poisoned():
    saved = sys.modules.get("engine.appc.sets")
    sys.modules["engine.appc.sets"] = None
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop("engine.appc.sets", None)
        else:
            sys.modules["engine.appc.sets"] = saved


@pytest.fixture
def planet_import_poisoned():
    saved = sys.modules.get("engine.appc.planet")
    sys.modules["engine.appc.planet"] = None
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop("engine.appc.planet", None)
        else:
            sys.modules["engine.appc.planet"] = saved


@pytest.fixture
def subsystems_import_poisoned():
    saved = sys.modules.get("engine.appc.subsystems")
    sys.modules["engine.appc.subsystems"] = None
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop("engine.appc.subsystems", None)
        else:
            sys.modules["engine.appc.subsystems"] = saved


def test_nullset_getobject_safe_at_shutdown(app_import_poisoned, sets_import_poisoned):
    ns = _NullSet()
    assert ns.GetObject("does_not_exist") is None


def test_objectgroup_getactiveobjecttuple_safe_at_shutdown(app_import_poisoned):
    g = ObjectGroup()
    g.AddName("does_not_exist")
    assert g.GetActiveObjectTuple() == ()


def test_getproximitymanager_safe_at_shutdown(planet_import_poisoned):
    """GC'd SDK ConditionInRange.__del__ → ProximityCheck.RemoveAndDelete →
    Set.GetProximityManager. With the manager never lazily created, the
    lazy import of ProximityManager raises at shutdown; the getter must
    return None instead."""
    pSet = SetClass()
    assert pSet.GetProximityManager() is None


def test_proximitycheck_removeanddelete_safe_at_shutdown(planet_import_poisoned):
    class _Anchor:
        def __init__(self, containing_set):
            self._set = containing_set

        def GetContainingSet(self):
            return self._set

    check = ProximityCheck()
    check._anchor = _Anchor(SetClass())
    check.RemoveAndDelete()  # must not raise ImportError
    assert check._anchor is None


def test_getproximitymanager_lazy_creation_intact():
    """Under normal import machinery the getter still lazily creates and
    returns a real ProximityManager."""
    from engine.appc.planet import ProximityManager

    pSet = SetClass()
    pm = pSet.GetProximityManager()
    assert isinstance(pm, ProximityManager)
    assert pSet.GetProximityManager() is pm


def test_powersubsystem_cast_safe_at_shutdown(subsystems_import_poisoned):
    """ConditionPowerBelow.__del__ calls App.PowerSubsystem_Cast; its lazy
    import of PowerSubsystem raises at shutdown. The cast must return None
    (the __del__ already null-checks `if pPower:`)."""
    assert App.PowerSubsystem_Cast(object()) is None


def test_pulseweapon_cast_safe_at_shutdown(subsystems_import_poisoned):
    """ConditionPulseReady.__del__ -> GetWeapons -> App.PulseWeapon_Cast has
    the same lazy-import shape; same degrade-to-None contract."""
    assert App.PulseWeapon_Cast(object()) is None


def test_lazy_casts_intact_under_normal_machinery():
    from engine.appc.subsystems import PowerSubsystem, PulseWeapon

    power = PowerSubsystem("power")
    pulse = PulseWeapon("pulse")
    assert App.PowerSubsystem_Cast(power) is power
    assert App.PulseWeapon_Cast(pulse) is pulse
    assert App.PowerSubsystem_Cast(object()) is None
    assert App.PulseWeapon_Cast(object()) is None
