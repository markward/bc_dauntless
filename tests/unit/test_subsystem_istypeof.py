"""ShipSubsystem.IsTypeOf — SDK class-id check via the shared CT_* <->
subsystem-class table in engine/appc/subsystem_types.py (task 3b).

`cls` is a CT_* Property-class constant (e.g. CT_SHIELD_SUBSYSTEM =
ShieldProperty); IsTypeOf resolves it through subsystem_class_for_ct() and
tests isinstance(self, that_class) -- it answers "is this subsystem
instance of this kind", independent of whether SetProperty has ever been
called (see test_is_type_of_one_with_no_property)."""
import App
from engine.appc.subsystems import (
    ShipSubsystem, ShieldSubsystem, ImpulseEngineSubsystem,
)
from engine.appc.properties import (
    ShieldProperty, ImpulseEngineProperty, SensorProperty,
)


def test_is_type_of_one_with_no_property():
    """IsTypeOf answers a runtime class-id check (this subsystem's own
    class), not whether a hardpoint property template has been mirrored
    onto it yet -- see engine/appc/subsystem_types.py. Task 3b replaced the
    historical property-based implementation (which conflated "class
    identity" with "has SetProperty run"): a ShieldSubsystem genuinely IS a
    CT_SHIELD_SUBSYSTEM the instant it's constructed."""
    s = ShieldSubsystem("Shield Generator")
    # No SetProperty called.
    assert s.IsTypeOf(ShieldProperty) == 1


def test_is_type_of_matches_property_class():
    s = ShieldSubsystem("Shield Generator")
    s.SetProperty(ShieldProperty("template"))
    assert s.IsTypeOf(ShieldProperty) == 1


def test_is_type_of_zero_for_wrong_class():
    s = ShieldSubsystem("Shield Generator")
    s.SetProperty(ShieldProperty("template"))
    assert s.IsTypeOf(SensorProperty) == 0
    assert s.IsTypeOf(ImpulseEngineProperty) == 0


def test_is_type_of_zero_when_cls_is_a_named_stub_instance():
    """App.CT_UNKNOWN_THING returns a _NamedStub instance (not a class).
    Guard against TypeError from isinstance(prop, instance)."""
    s = ShieldSubsystem("Shield Generator")
    s.SetProperty(ShieldProperty("template"))
    fake_ct = App.CT_NEWLY_INVENTED_THING_THAT_DOES_NOT_EXIST
    assert isinstance(fake_ct, App._NamedStub)
    # Must not raise; must return 0.
    assert s.IsTypeOf(fake_ct) == 0


def test_is_type_of_works_on_other_subsystem_types():
    """Confirms IsTypeOf lives on the base, not the shield subclass."""
    s = ImpulseEngineSubsystem("Impulse")
    s.SetProperty(ImpulseEngineProperty("template"))
    assert s.IsTypeOf(ImpulseEngineProperty) == 1
    assert s.IsTypeOf(ShieldProperty) == 0
