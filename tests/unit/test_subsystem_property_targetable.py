"""SubsystemProperty.IsTargetable / SetTargetable.

MissionLib.HideSubsystem (sdk/.../MissionLib.py:2166-2174) calls
``pProp.IsTargetable()`` and ``pProp.SetTargetable(0)`` on the
SubsystemProperty returned by ``ShipSubsystem.GetProperty()``. Real BC
exposes both methods on SubsystemProperty itself (App.py:9136, 9143).

E2M1 and E6M2 trip the missing method during init.
"""

from engine.appc.properties import (
    SubsystemProperty, HullProperty, PowerProperty, ShieldProperty,
)


def test_subsystem_property_defaults_to_targetable():
    prop = SubsystemProperty("any")
    assert prop.IsTargetable() == 1


def test_subsystem_property_set_targetable_round_trip():
    prop = SubsystemProperty("any")
    prop.SetTargetable(0)
    assert prop.IsTargetable() == 0
    prop.SetTargetable(1)
    assert prop.IsTargetable() == 1


def test_targetable_flag_present_on_subclasses():
    for cls in (HullProperty, PowerProperty, ShieldProperty):
        prop = cls("x")
        assert prop.IsTargetable() == 1
        prop.SetTargetable(0)
        assert prop.IsTargetable() == 0
