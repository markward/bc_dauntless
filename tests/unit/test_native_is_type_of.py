"""IsTypeOf answered natively (phase 6 AI part 3, task 4): the same int 0/1 and
the same exceptions as the Python bodies, a memo invalidated by the type
registry's generation, and the native FireScript calling the native answer
directly only when the subsystem's IsTypeOf is the stock body."""
import random
import sys

import pytest

_h = pytest.importorskip("_dauntless_host")

import App
from engine.appc import object_types, objects, subsystem_types, subsystems
from engine.appc.objects import ObjectClass
from engine.appc.planet import Planet_Create, Sun_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ShipSubsystem


def _old_object(self, cls):
    tc = type(cls)
    if tc is not int and not isinstance(cls, type):
        c = object_types.resolve_class(cls)
        return 1 if isinstance(c, type) and isinstance(self, c) else 0
    c = object_types.resolve_class(cls)
    return 1 if isinstance(c, type) and isinstance(self, c) else 0


def _old_subsystem(self, cls):
    target = subsystem_types.subsystem_class_for_ct(cls)
    if target is None:
        return 0
    return 1 if isinstance(self, target) else 0


def _tags():
    stub = App.CT_NEWLY_INVENTED_THING_THAT_DOES_NOT_EXIST
    return (list(object_types.registered_tags())
            + [ObjectClass, ShipClass, ShipSubsystem, 987654, -1, True,
               1.0, None, "junk", stub, (1, 2)])


def test_is_type_of_matches_the_old_body_for_every_tag_and_class():
    objs = [ObjectClass(), ShipClass(), Planet_Create(200.0, "c.nif"),
            Sun_Create(2000.0, 2000, 500)]
    subs = [ShipSubsystem(), subsystems.PhaserSystem(),
            subsystems.HullSubsystem(), subsystems.TorpedoSystem()]
    for _ in range(2):  # cold, then memoised
        for tag in _tags():
            for o in objs:
                got = o.IsTypeOf(tag)
                assert got == _old_object(o, tag) and type(got) is int, tag
            for s in subs:
                got = s.IsTypeOf(tag)
                assert got == _old_subsystem(s, tag) and type(got) is int, tag


def test_a_generation_bump_invalidates():
    class Fresh(ObjectClass):
        pass
    tag = 987001
    o = Fresh()
    saved = dict(object_types._BY_TAG), dict(object_types._BY_CLASS)
    try:
        assert o.IsTypeOf(tag) == 0  # unregistered: 0 (and not memoised wrongly)
        object_types.register(tag, ObjectClass)
        assert o.IsTypeOf(tag) == 1
        object_types.register(tag, ShipClass)
        assert o.IsTypeOf(tag) == 0
    finally:
        object_types._BY_TAG.clear(); object_types._BY_TAG.update(saved[0])
        object_types._BY_CLASS.clear(); object_types._BY_CLASS.update(saved[1])
        object_types._GENERATION += 1
    assert o.IsTypeOf(tag) == 0


def test_the_subsystem_memo_follows_a_replaced_table(monkeypatch):
    sub = subsystems.PhaserSystem()
    tag = App.CT_HULL_SUBSYSTEM
    assert sub.IsTypeOf(tag) == 0
    table = subsystem_types._ct_table()
    swapped = tuple((t, subsystems.PhaserSystem if t == tag else c)
                    for t, c in table)
    monkeypatch.setattr(subsystem_types, "_CT_TABLE_CACHE", swapped)
    assert sub.IsTypeOf(tag) == 1
    monkeypatch.undo()
    assert sub.IsTypeOf(tag) == 0


def test_a_patched_class_for_ct_is_seen(monkeypatch):
    sub = subsystems.PhaserSystem()
    tag = App.CT_HULL_SUBSYSTEM
    assert sub.IsTypeOf(tag) == 0
    monkeypatch.setattr(subsystem_types, "subsystem_class_for_ct",
                        lambda ct: subsystems.PhaserSystem)
    assert sub.IsTypeOf(tag) == 1


def test_errors_match_the_python_bodies():
    class Boom(type):
        def __instancecheck__(cls, inst):
            raise ValueError("boom")
    class Target(metaclass=Boom):
        pass
    o = ObjectClass()
    with pytest.raises(ValueError):
        o.IsTypeOf(Target)
    with pytest.raises(TypeError):
        _h.is_type_of(o, 1)


def test_a_stale_binary_surfaces_as_attributeerror(monkeypatch):
    assert objects._is_type_of is _h.is_type_of
    assert subsystems._subsystem_is_type_of is _h.subsystem_is_type_of


def _calls_of_istypeof(fn):
    seen = []

    def prof(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "IsTypeOf":
            seen.append(frame.f_code.co_filename)
    sys.setprofile(prof)
    try:
        fn()
    finally:
        sys.setprofile(None)
    return seen


def test_the_fire_binding_calls_is_type_of_natively_only_when_stock(monkeypatch):
    from tests.unit import test_native_fire_script as t
    opt = dict(ours="Akira", target="Galaxy", range=1e20, targetable=2,
               weapons=("GetTorpedoSystem", "GetPhaserSystem"),
               kw={"ChooseSubsystemTargets": 1})

    def run(scene):
        def go():
            for step in range(6):
                scene.perturb(random.Random(50 + step))
                scene.inst.Update(0.0)
        return go

    t._reset_app_state()
    stock = t._Scene("A", opt)
    assert _calls_of_istypeof(run(stock)) == []

    t._reset_app_state()
    patched = t._Scene("B", opt)
    hits = []
    original = ShipSubsystem.IsTypeOf

    def spy(self, cls):
        hits.append(cls)
        return original(self, cls)
    monkeypatch.setattr(ShipSubsystem, "IsTypeOf", spy)
    run(patched)()
    assert hits, "a patched ShipSubsystem.IsTypeOf was never called"
