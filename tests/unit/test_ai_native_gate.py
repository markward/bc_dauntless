"""The stock gate, the build switch and the counters for native stock
preprocessors (phase 6 AI part 2, Task 1; engine/appc/ai_native.py).

A native preprocessor path runs only for an instance the SDK would have run
unchanged. These tests pin what "stock" means: the functions come from the
real SDK file, nobody shadowed them on the class, the instance or an engine
subclass, and a patch made at any time is seen on the NEXT call."""
import pytest

import AI.Preprocessors as pp

from engine.appc import ai_native
from engine.appc import ai_sensor_gate

SELECT = ("GetTargetRating",)
AVOID = ("NeedToAvoid",)
FIRE = ("Update",)


def _select():
    return pp.SelectTarget("Tgt")


def test_the_stock_sdk_functions_are_stock():
    assert ai_native.is_stock_sdk_function(
        pp.SelectTarget.GetTargetRating, "SelectTarget.GetTargetRating")
    assert ai_native.is_stock_sdk_function(
        pp.AvoidObstacles.NeedToAvoid, "AvoidObstacles.NeedToAvoid")
    assert ai_native.is_stock_sdk_function(
        pp.FireScript.Update, "FireScript.Update")
    assert ai_native.preprocessor_is_stock(_select(), "SelectTarget", SELECT)
    assert ai_native.preprocessor_is_stock(
        pp.AvoidObstacles(), "AvoidObstacles", AVOID)
    assert ai_native.preprocessor_is_stock(
        pp.FireScript("Tgt"), "FireScript", FIRE)


def test_a_wrong_qualname_is_not_stock():
    assert not ai_native.is_stock_sdk_function(
        pp.SelectTarget.GetTargetRating, "SelectTarget.Update")


def test_a_monkeypatch_is_not_stock_and_is_seen_on_the_next_call(monkeypatch):
    inst = _select()
    assert ai_native.preprocessor_is_stock(inst, "SelectTarget", SELECT)

    original = pp.SelectTarget.GetTargetRating

    def patched(self, pTarget):
        return 0.0
    monkeypatch.setattr(pp.SelectTarget, "GetTargetRating", patched)
    assert not ai_native.preprocessor_is_stock(inst, "SelectTarget", SELECT)

    monkeypatch.setattr(pp.SelectTarget, "GetTargetRating", original)
    assert ai_native.preprocessor_is_stock(inst, "SelectTarget", SELECT)


def test_a_subclass_method_is_not_stock():
    class Mod(pp.SelectTarget):
        def GetTargetRating(self, pTarget):
            return 1.0
    assert not ai_native.preprocessor_is_stock(
        Mod("Tgt"), "SelectTarget", SELECT)


def test_a_subclass_that_overrides_nothing_is_stock():
    class Quiet(pp.SelectTarget):
        pass
    assert ai_native.preprocessor_is_stock(
        Quiet("Tgt"), "SelectTarget", SELECT)


def test_an_instance_dict_override_is_not_stock():
    inst = _select()
    assert ai_native.preprocessor_is_stock(inst, "SelectTarget", SELECT)
    inst.__dict__["GetTargetRating"] = lambda pTarget: 0.0
    assert not ai_native.preprocessor_is_stock(inst, "SelectTarget", SELECT)
    del inst.__dict__["GetTargetRating"]
    assert ai_native.preprocessor_is_stock(inst, "SelectTarget", SELECT)


def test_a_function_from_another_file_with_the_same_qualname_is_not_stock():
    ns = {}
    src = ("class SelectTarget:\n"
           "    def GetTargetRating(self, pTarget):\n"
           "        return 0.0\n")
    exec(compile(src, "/somewhere/else/Preprocessors.py", "exec"), ns)
    fn = ns["SelectTarget"].GetTargetRating
    assert fn.__qualname__ == "SelectTarget.GetTargetRating"
    assert not ai_native.is_stock_sdk_function(
        fn, "SelectTarget.GetTargetRating")

    class Faker(ns["SelectTarget"]):
        pass
    assert not ai_native.preprocessor_is_stock(
        Faker(), "SelectTarget", SELECT)


def test_a_class_that_is_not_the_sdk_class_is_not_stock():
    assert not ai_native.preprocessor_is_stock(
        _select(), "AvoidObstacles", AVOID)


def test_the_sensor_gate_wrapper_counts_as_stock():
    ai_sensor_gate.uninstall_ai_sensor_gate()
    try:
        ai_sensor_gate.install_ai_sensor_gate()
        assert getattr(pp.SelectTarget.FindGoodTarget, "_sensor_gated", False)
        assert getattr(pp.FireScript.TargetVisible, "_sensor_gated", False)
        assert ai_native.preprocessor_is_stock(
            _select(), "SelectTarget", ("FindGoodTarget", "GetTargetRating"))
        assert ai_native.preprocessor_is_stock(
            pp.FireScript("Tgt"), "FireScript", ("TargetVisible", "Update"))
    finally:
        ai_sensor_gate.uninstall_ai_sensor_gate()
    assert not getattr(pp.SelectTarget.FindGoodTarget, "_sensor_gated", False)
    assert ai_native.preprocessor_is_stock(
        _select(), "SelectTarget", ("FindGoodTarget", "GetTargetRating"))
    assert ai_native.preprocessor_is_stock(
        pp.FireScript("Tgt"), "FireScript", ("TargetVisible", "Update"))


def test_a_foreign_wrapper_is_not_stock(monkeypatch):
    original = pp.SelectTarget.FindGoodTarget

    def mine(self):
        return original(self)
    monkeypatch.setattr(pp.SelectTarget, "FindGoodTarget", mine)
    assert not ai_native.preprocessor_is_stock(
        _select(), "SelectTarget", ("FindGoodTarget",))
    # Wrapping the SDK function is not enough: the wrapper's own code is not
    # in the SDK file, and only the sensor gate's functions are unwrapped by
    # their _dauntless_wraps mark.


def test_a_marked_engine_override_is_checked_against_the_sdk_base(monkeypatch):
    """An engine subclass overriding the hot method (marked) is stock exactly
    while the SDK base method it shadows is stock."""
    class EngineSelect(pp.SelectTarget):
        def GetTargetRating(self, pTarget):
            return 0.0
        GetTargetRating._dauntless_native_entry = True

    inst = EngineSelect("Tgt")
    assert ai_native.preprocessor_is_stock(inst, "SelectTarget", SELECT)

    original = pp.SelectTarget.GetTargetRating

    def patched(self, pTarget):
        return 1.0
    monkeypatch.setattr(pp.SelectTarget, "GetTargetRating", patched)
    assert not ai_native.preprocessor_is_stock(inst, "SelectTarget", SELECT)
    monkeypatch.setattr(pp.SelectTarget, "GetTargetRating", original)
    assert ai_native.preprocessor_is_stock(inst, "SelectTarget", SELECT)


def test_an_unmarked_override_on_an_engine_subclass_is_not_stock():
    class Sneaky(pp.SelectTarget):
        def GetTargetRating(self, pTarget):
            return 0.0
    assert not ai_native.preprocessor_is_stock(
        Sneaky("Tgt"), "SelectTarget", SELECT)


def test_a_monkeypatched_avoid_override_target_is_seen(monkeypatch):
    """The real case: AvoidObstacles.TestCourseOverride patched on the SDK
    class while an engine subclass carries the marked override."""
    class EngineAvoid(pp.AvoidObstacles):
        def TestCourseOverride(self):
            return None
        TestCourseOverride._dauntless_native_entry = True

    inst = EngineAvoid()
    names = ("TestCourseOverride", "NeedToAvoid")
    assert ai_native.preprocessor_is_stock(inst, "AvoidObstacles", names)
    monkeypatch.setattr(pp.AvoidObstacles, "TestCourseOverride",
                        lambda self: None)
    assert not ai_native.preprocessor_is_stock(inst, "AvoidObstacles", names)


@pytest.mark.parametrize("raw, want", [
    (None, {"avoid", "select", "fire"}),
    ("", {"avoid", "select", "fire"}),
    ("1", {"avoid", "select", "fire"}),
    ("0", set()),
    ("avoid,fire", {"avoid", "fire"}),
    (" select ", {"select"}),
    ("junk", set()),
    ("avoid,junk", {"avoid"}),
])
def test_switch_parsing(monkeypatch, raw, want):
    if raw is None:
        monkeypatch.delenv("DAUNTLESS_NATIVE_AI", raising=False)
    else:
        monkeypatch.setenv("DAUNTLESS_NATIVE_AI", raw)
    assert ai_native.KINDS == ("avoid", "select", "fire")
    assert {k for k in ai_native.KINDS if ai_native.enabled(k)} == want


def test_switch_is_read_at_use(monkeypatch):
    monkeypatch.setenv("DAUNTLESS_NATIVE_AI", "0")
    assert not ai_native.enabled("avoid")
    monkeypatch.setenv("DAUNTLESS_NATIVE_AI", "1")
    assert ai_native.enabled("avoid")


def test_object_surface_detects_a_subclass_override():
    from engine.appc.ships import ShipClass, ShipClass_Create
    ship = ShipClass_Create("Galaxy")
    names = ("GetRadius", "GetWorldLocation")
    assert ai_native.object_surface_is_stock(ship, names)

    class Modded(ShipClass):
        def GetRadius(self):
            return 1.0
    other = Modded()
    assert not ai_native.object_surface_is_stock(other, names)
    assert ai_native.object_surface_is_stock(ship, names)


def test_object_surface_sees_a_patch_on_the_engine_class(monkeypatch):
    from engine.appc.ships import ShipClass, ShipClass_Create
    ship = ShipClass_Create("Galaxy")
    names = ("GetWorldLocation",)
    assert ai_native.object_surface_is_stock(ship, names)
    original = ShipClass.GetWorldLocation
    monkeypatch.setattr(ShipClass, "GetWorldLocation",
                        lambda self: original(self))
    assert not ai_native.object_surface_is_stock(ship, names)
    monkeypatch.setattr(ShipClass, "GetWorldLocation", original)
    assert ai_native.object_surface_is_stock(ship, names)


def test_object_surface_sees_an_instance_override():
    from engine.appc.ships import ShipClass_Create
    ship = ShipClass_Create("Galaxy")
    names = ("GetRadius",)
    assert ai_native.object_surface_is_stock(ship, names)
    ship.__dict__["GetRadius"] = lambda: 1.0
    assert not ai_native.object_surface_is_stock(ship, names)


def test_stats_count_and_reset():
    ai_native.reset_stats()
    ai_native.note("avoid", "native")
    ai_native.note("avoid", "python", "not_stock")
    ai_native.note("avoid", "python", "not_stock")
    ai_native.note("fire", "python", "switch")
    s = ai_native.stats()
    assert s["avoid"] == {"native": 1, "python": 2,
                          "reasons": {"not_stock": 2}}
    assert s["fire"] == {"native": 0, "python": 1, "reasons": {"switch": 1}}
    assert s["select"] == {"native": 0, "python": 0, "reasons": {}}
    ai_native.reset_stats()
    assert all(v == {"native": 0, "python": 0, "reasons": {}}
               for v in ai_native.stats().values())


def test_stats_reset_on_mission_state_reset():
    from engine import host_loop
    ai_native.note("select", "native")
    host_loop.reset_mission_state()
    assert ai_native.stats()["select"]["native"] == 0


def test_stats_line_prints_with_the_frame_profiler_report():
    from engine.core import frame_profiler
    ai_native.reset_stats()
    ai_native.note("avoid", "native")
    ai_native.note("avoid", "python", "not_stock")
    (line,) = frame_profiler._ai_native_lines()
    assert line == ("  ai native: avoid native 1, python 1 (not_stock 1); "
                    "select native 0, python 0; fire native 0, python 0")
    ai_native.reset_stats()
