"""ShipSubsystem.IsTypeOf — SDK class-id check via source-property type."""
import App
from engine.appc.subsystems import (
    ShipSubsystem, ShieldSubsystem, ImpulseEngineSubsystem,
)
from engine.appc.properties import (
    ShieldProperty, ImpulseEngineProperty, SensorProperty,
)


def test_default_is_type_of_zero_with_no_property():
    s = ShieldSubsystem("Shield Generator")
    # No SetProperty called.
    assert s.IsTypeOf(ShieldProperty) == 0


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
