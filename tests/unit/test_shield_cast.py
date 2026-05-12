"""App.ShieldClass_Cast / ShieldProperty_Cast / ShieldClass surface."""
import App
from engine.appc.subsystems import ShieldSubsystem, ImpulseEngineSubsystem
from engine.appc.properties import ShieldProperty, SensorProperty


def test_shield_class_cast_returns_subsystem_unchanged():
    s = ShieldSubsystem("Shield Generator")
    assert App.ShieldClass_Cast(s) is s


def test_shield_class_cast_rejects_other_subsystem():
    other = ImpulseEngineSubsystem("Impulse")
    assert App.ShieldClass_Cast(other) is None


def test_shield_class_cast_rejects_none():
    assert App.ShieldClass_Cast(None) is None


def test_shield_class_cast_rejects_named_stub():
    """Without this, every undefined attribute access keeps producing
    stub-tracker hits via __getattr__."""
    stub = App.SomeUndefinedThing
    assert isinstance(stub, App._NamedStub)
    assert App.ShieldClass_Cast(stub) is None


def test_shield_property_cast_returns_property_unchanged():
    p = ShieldProperty("Shield Generator")
    assert App.ShieldProperty_Cast(p) is p


def test_shield_property_cast_rejects_other_property():
    other = SensorProperty("Sensors")
    assert App.ShieldProperty_Cast(other) is None


def test_shield_property_cast_rejects_named_stub():
    stub = App.SomethingElse
    assert App.ShieldProperty_Cast(stub) is None


def test_app_shield_class_is_subsystem():
    """SDK reads App.ShieldClass.NUM_SHIELDS, .FRONT_SHIELDS, etc."""
    assert App.ShieldClass is ShieldSubsystem
    assert App.ShieldClass.NUM_SHIELDS == 6
    assert App.ShieldClass.FRONT_SHIELDS == 0
