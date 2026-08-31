import types

import App
from tools.constant_surface_audit import real_attr
from engine.appc.constants_apply import apply_constants


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
    """Task 3 was additive only; corrections land in Tasks 5-11, one family
    at a time. This pins the running total, updated as each lands.

    585 (Task 3/4 baseline), not 584: FOURTH_PI joined its PI/HALF_PI/TWO_PI
    siblings in the "wrong" bucket once fix-round-1 defined it in App.py (see
    the DEVIATIONS entry) -- it was "missing" before that fix, never a
    pre-existing "wrong" value, so that step was additive, not a correction.
    Its value (math.pi / 4.0, kept deliberately at double precision)
    legitimately differs from BC's float32-rounded measurement, exactly like
    its three siblings.

    437 (post-Task 5): Task 5 corrected the 148 ET_* event-type constants
    (App.py's invented numbering -> the q13-measured values), the first
    correction round this sweep has landed."""
    from tools.constant_surface_audit import load
    _, _, wrong, _, _ = load()
    assert len(wrong) == 437, "wrong-value count drifted from Task 5's landed corrections"


def test_deviations_are_respected():
    import math
    from engine.appc.constants_apply import DEVIATIONS
    assert "PI" in DEVIATIONS
    assert App.PI == math.pi          # ours, not BC's float32


def test_every_deviation_is_really_defined():
    """A DEVIATIONS entry suppresses injection for that name -- if App.py
    never defines it independently, the suppression itself creates a truthy
    _NamedStub, exactly the bug class this sweep exists to eliminate.  Use
    real_attr, not getattr: getattr can't distinguish 'defined' from
    'stubbed'."""
    from engine.appc.constants_apply import DEVIATIONS
    for qualified in DEVIATIONS:
        if "." in qualified:
            cls_name, attr = qualified.split(".", 1)
            has_cls, cls = real_attr(App, cls_name)
            assert has_cls and isinstance(cls, type), (
                "%s: owner class not really defined" % qualified)
            defined, _ = real_attr(cls, attr)
        else:
            defined, _ = real_attr(App, qualified)
        assert defined, "%s is in DEVIATIONS but not really defined on App" % qualified


def test_shadow_guard_preserves_falsy_real_attributes():
    """A real class attribute valued None or 0 must not read as 'absent' and
    get overwritten by an injected constant -- that would silently corrupt
    every implemented class whose real value happens to be falsy."""
    class Foo:
        BAR = None
        BAZ = 0

    fake_module = types.ModuleType("fake_constants_apply_target")
    fake_module.Foo = Foo

    apply_constants(
        fake_module, {}, {"Foo": {"BAR": 99, "BAZ": 42}}, {},
        correct_existing=frozenset(), named_stub_factory=lambda n: None,
    )

    assert Foo.BAR is None, "None-valued attribute must survive injection"
    assert Foo.BAZ == 0, "0-valued attribute must survive injection"
