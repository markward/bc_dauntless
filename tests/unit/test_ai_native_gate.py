"""The stock gate and the counters for native stock
preprocessors (phase 6 AI part 2, Task 1; engine/appc/ai_native.py).

A native preprocessor path runs only for an instance the SDK would have run
unchanged. These tests pin what "stock" means: the functions come from the
real SDK file, nobody shadowed them on the class, the instance or an engine
subclass, and a patch made at any time is seen on the NEXT call."""
import contextlib

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


def test_a_foreign_wrapper_carrying_dauntless_wraps_is_not_stock(monkeypatch):
    """_dauntless_wraps is honoured only on wrappers defined in the sensor
    gate's file: a mod copying the attribute gets no free pass."""
    original = pp.SelectTarget.GetTargetRating

    def mine(self, pTarget):
        return 0.0
    mine._dauntless_wraps = original
    monkeypatch.setattr(pp.SelectTarget, "GetTargetRating", mine)
    assert not ai_native.is_stock_sdk_function(
        mine, "SelectTarget.GetTargetRating")
    assert not ai_native.preprocessor_is_stock(_select(), "SelectTarget",
                                               SELECT)


def test_a_clone_of_the_sdk_code_with_other_globals_is_not_stock(monkeypatch):
    import types
    sdk_fn = pp.SelectTarget.GetTargetRating
    clone = types.FunctionType(sdk_fn.__code__, {}, sdk_fn.__name__,
                               sdk_fn.__defaults__, None)
    clone.__qualname__ = sdk_fn.__qualname__
    assert not ai_native.is_stock_sdk_function(
        clone, "SelectTarget.GetTargetRating")
    monkeypatch.setattr(pp.SelectTarget, "GetTargetRating", clone)
    assert not ai_native.preprocessor_is_stock(_select(), "SelectTarget",
                                               SELECT)


def test_a_clone_with_a_closure_or_other_defaults_is_not_stock():
    import types
    sdk_fn = pp.SelectTarget.GetTargetRating
    other = types.FunctionType(sdk_fn.__code__, sdk_fn.__globals__,
                               sdk_fn.__name__, (object(),) * len(
                                   sdk_fn.__defaults__ or ()) or (1,), None)
    other.__qualname__ = sdk_fn.__qualname__
    assert not ai_native.is_stock_sdk_function(
        other, "SelectTarget.GetTargetRating")


def test_the_snapshot_exists_right_after_importing_host_loop():
    """The surface snapshot must precede any patch, so boot imports it."""
    import subprocess
    import sys
    code = ("import sys, engine.host_loop;"
            "m = sys.modules.get('engine.appc.ai_native');"
            "assert m is not None and m._READER_BODIES")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr[-1500:]


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


def test_no_native_ai_switch_remains():
    """The temporary build switch is gone: only the test-only in-process
    flag forces the SDK Python."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    word = "DAUNTLESS_" + "NATIVE_AI"
    hits = [str(p.relative_to(root))
            for top in ("engine", "native")
            for p in (root / top).rglob("*")
            if p.is_file() and p.suffix in (".py", ".cc", ".h", ".txt",
                                            ".js", ".json")
            and word in p.read_text(errors="ignore")]
    assert hits == []
    assert not hasattr(ai_native, "enabled")


def test_force_python_sends_the_gate_to_the_sdk(monkeypatch):
    inst = pp.FireScript("Tgt")
    assert ai_native.preprocessor_is_stock(inst, "FireScript", FIRE)
    monkeypatch.setattr(ai_native, "_force_python", True)
    assert not ai_native.preprocessor_is_stock(inst, "FireScript", FIRE)
    monkeypatch.setattr(ai_native, "_force_python", False)
    assert ai_native.preprocessor_is_stock(inst, "FireScript", FIRE)


def test_reader_contract_detects_a_subclass_override():
    from engine.appc.ships import ShipClass, ShipClass_Create
    ship = ShipClass_Create("Galaxy")
    contract = ai_native.reader_contract("GetRadius", "GetWorldLocation")
    assert ai_native.object_reads_are_stock(ship, contract)

    class Modded(ShipClass):
        def GetRadius(self):
            return 1.0
    other = Modded()
    assert not ai_native.object_reads_are_stock(other, contract)
    assert ai_native.object_reads_are_stock(ship, contract)


def test_reader_contract_sees_a_patch_on_the_engine_class(monkeypatch):
    from engine.appc.objects import ObjectClass
    from engine.appc.ships import ShipClass, ShipClass_Create
    ship = ShipClass_Create("Galaxy")
    contract = ai_native.reader_contract("GetWorldLocation")
    assert ai_native.object_reads_are_stock(ship, contract)
    original = ShipClass.GetWorldLocation
    monkeypatch.setattr(ShipClass, "GetWorldLocation",
                        lambda self: original(self))
    assert not ai_native.object_reads_are_stock(ship, contract)
    monkeypatch.delattr(ShipClass, "GetWorldLocation")
    assert ai_native.object_reads_are_stock(ship, contract)
    # Patching the defining class itself is seen too.
    monkeypatch.setattr(ObjectClass, "GetWorldLocation",
                        lambda self: original(self))
    assert not ai_native.object_reads_are_stock(ship, contract)


def test_reader_contract_sees_an_instance_override():
    from engine.appc.ships import ShipClass_Create
    ship = ShipClass_Create("Galaxy")
    contract = ai_native.reader_contract("GetRadius")
    assert ai_native.object_reads_are_stock(ship, contract)
    ship.__dict__["GetRadius"] = lambda: 1.0
    assert not ai_native.object_reads_are_stock(ship, contract)


def test_reader_contract_requires_the_exact_body_the_reader_mirrors():
    """Not "any engine function": DebrisChunk's GetWorldLocation / GetRadius
    and Torpedo's GetVelocityTG are engine code, but not the bodies a native
    reader reproduces, so they are rejected."""
    from engine.appc.debris_chunk import DebrisChunk
    from engine.appc.objects import ObjectClass, PhysicsObjectClass
    from engine.appc.projectiles import Torpedo
    from engine.core.ids import TGObject
    chunk = DebrisChunk.__new__(DebrisChunk)
    assert not ai_native.object_reads_are_stock(
        chunk, ai_native.reader_contract("GetWorldLocation", "GetRadius"))
    torp = Torpedo()
    assert not ai_native.object_reads_are_stock(
        torp, ai_native.reader_contract("GetVelocityTG"))
    # Its inherited ObjectClass readers ARE the mirrored bodies.
    assert ai_native.object_reads_are_stock(
        torp, ai_native.reader_contract("GetWorldLocation", "GetRadius"))
    assert dict(ai_native.reader_contract(
        "GetObjID", "IsTypeOf", "GetWorldLocation", "GetRadius",
        "GetVelocityTG")) == {
        "GetObjID": TGObject.__dict__["GetObjID"],
        "IsTypeOf": ObjectClass.__dict__["IsTypeOf"],
        "GetWorldLocation": ObjectClass.__dict__["GetWorldLocation"],
        "GetRadius": ObjectClass.__dict__["GetRadius"],
        "GetVelocityTG": PhysicsObjectClass.__dict__["GetVelocityTG"]}
    with pytest.raises(KeyError):
        ai_native.reader_contract("GetMass")     # no native reader mirrors it


def test_reader_contract_object_without_a_dict_shadows_nothing():
    obj = _no_dict_ship()
    contract = ai_native.reader_contract("GetRadius")
    _NoDictShip.hidden = True
    try:
        assert ai_native.object_reads_are_stock(obj, contract)
    finally:
        _NoDictShip.hidden = False


def test_reader_contract_object_with_a_non_dict___dict___shadows():
    """A ``__dict__`` that is not a dict is not a lookup anyone reproduces:
    the conservative answer, "shadows", here and in every native reader
    (the host's one dict_shadows helper)."""
    from engine.appc.ships import ShipClass
    obj = ShipClass()
    contract = ai_native.reader_contract("GetRadius")
    with mapping_dict(obj):
        assert not isinstance(obj.__dict__, dict)
        assert not ai_native.object_reads_are_stock(obj, contract)
    assert ai_native.object_reads_are_stock(obj, contract)


def _real_dict_descriptor(cls):
    for klass in cls.__mro__[1:]:
        d = klass.__dict__.get("__dict__")
        if d is not None:
            return d
    raise AssertionError("no __dict__ slot")


def _make_no_dict_class():
    from engine.appc.ships import ShipClass

    class _NoDict(ShipClass):
        """A ship whose `__dict__` attribute is missing while `hidden`."""
        hidden = False

        @property
        def __dict__(self):
            if type(self).hidden:
                raise AttributeError("__dict__")
            return _real_dict_descriptor(type(self)).__get__(self)

        def __getattr__(self, name):
            raise AttributeError(name)
    return _NoDict


_NoDictShip = _make_no_dict_class()


def _no_dict_ship():
    return _NoDictShip()


def _make_mapping_dict_class():
    """A ship whose `__dict__` attribute is a read-only view of its real
    dict: not a dict (the real one still holds its attributes)."""
    import types
    from engine.appc.ships import ShipClass

    class _MappingDict(ShipClass):
        @property
        def __dict__(self):
            return types.MappingProxyType(
                _real_dict_descriptor(type(self)).__get__(self))
    return _MappingDict


_MappingDictShip = _make_mapping_dict_class()


@contextlib.contextmanager
def mapping_dict(*objs):
    """Each of `objs` (plain ships) as a _MappingDictShip for the block.
    Only for the block: the engine writes obj.__dict__ (the constructor,
    every setter that pushes to the native combat mirror), so the objects
    are built and moved as plain ships, and put back before teardown."""
    plain = [type(o) for o in objs]
    for o in objs:
        o.__class__ = _MappingDictShip
    try:
        yield objs
    finally:
        for o, cls in zip(objs, plain):
            o.__class__ = cls


_EMPTY = {"native": 0, "python": 0, "reasons": {}, "object_fallbacks": {},
          "counts": {}}


def test_stats_count_and_reset():
    ai_native.reset_stats()
    ai_native.note("avoid", "native")
    ai_native.note("avoid", "python", "not_stock")
    ai_native.note("avoid", "python", "not_stock")
    ai_native.note("fire", "python", "no_mirror")
    # Per-object fallbacks inside a native call, and results: neither is a
    # call, so neither moves "native" or "python".
    ai_native.note_object_fallback("avoid", "surface")
    ai_native.count("avoid", "avoided", 3)
    s = ai_native.stats()
    assert s["avoid"] == {"native": 1, "python": 2,
                          "reasons": {"not_stock": 2},
                          "object_fallbacks": {"surface": 1},
                          "counts": {"avoided": 3}}
    assert s["fire"] == dict(_EMPTY, python=1, reasons={"no_mirror": 1})
    assert s["select"] == _EMPTY
    ai_native.reset_stats()
    assert all(v == _EMPTY for v in ai_native.stats().values())


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
    ai_native.note_object_fallback("avoid", "surface")
    (line,) = frame_profiler._ai_native_lines()
    assert line.startswith("  ai native: avoid native 1, python 1 "
                           "(not_stock 1) [objects to python: surface 1]; ")
    ai_native.reset_stats()
