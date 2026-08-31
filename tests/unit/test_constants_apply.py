import App
from tools.constant_surface_audit import real_attr


def test_previously_missing_constants_are_now_real_ints():
    """The 17 dead-handler event types from the stub report."""
    for name, want in [
        ("ET_CANT_FIRE", 0x800037), ("ET_FIRE", 0x800036),
        ("ET_OBJECTIVES", 0x80002E), ("ET_SET_WARP_SEQUENCE", 0x8000EE),
        ("ET_TORPEDO_ENTERED_SET", 0x80005C),
        ("ET_TRACTOR_BEAM_STARTED_FIRING", 0x80007D),
    ]:
        defined, value = real_attr(App, name)
        assert defined, "%s must be really defined, not stubbed" % name
        assert value == want


def test_synthesized_class_still_stubs_unknown_attributes():
    """A class we do not implement must keep today's silent-no-op behaviour:
    unknown attrs vend a stub, not AttributeError, and it stays callable."""
    cls = App.AnimTSParticleController
    assert cls.HIGH == 3 and cls.LOWEST == 0
    assert cls.SOME_ATTR_BC_HAS_THAT_WE_DO_NOT is not None   # must not raise
    instance = cls()                                          # must not raise
    assert instance.AnyMethod() is not None                   # must not raise


def test_injection_does_not_touch_classes_we_implement():
    """Real behaviour must survive: injecting constants onto ShipClass must
    not shadow its methods."""
    assert callable(App.ShipClass.GetName)


def test_additive_pass_changes_no_existing_value():
    """Task 3 is additive only -- corrections land in Tasks 5-11."""
    from tools.constant_surface_audit import load
    _, _, wrong, _, _ = load()
    assert len(wrong) == 584, "additive pass must not correct anything yet"


def test_deviations_are_respected():
    import math
    from engine.appc.constants_apply import DEVIATIONS
    assert "PI" in DEVIATIONS
    assert App.PI == math.pi          # ours, not BC's float32
