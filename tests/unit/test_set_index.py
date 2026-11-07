"""The native set index (engine/appc/set_index.py) answers
SetClass.GetClassObjectList exactly as the old scan of `SetClass._objects`
did: same objects, same order, a new list each call.

Spec: docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md
§4.1; plan docs/superpowers/plans/2026-11-07-phase6-ai-p1-set-index.md.
"""
import ast
import gc
import os
import subprocess
import sys
import textwrap
import types
import weakref
from pathlib import Path

import App
import _dauntless_host as _h
import pytest

from engine.appc import contact_index, object_types, set_index
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass, ShipClass_Create

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _scan(pSet, cls):
    return [o for o in pSet._objects.values() if isinstance(o, cls)]


def _class_for(tag):
    from engine.appc.properties import ShipProperty
    cls = object_types.resolve_class(tag)
    return ShipClass if cls is ShipProperty else cls


def _ship(name):
    s = ShipClass_Create(name)
    return s


def _mixed_set():
    from engine.appc.placement import Waypoint
    from engine.appc.planet import Planet_Create, Sun_Create
    from engine.appc.projectiles import Torpedo
    from engine.rocks.rock import RockClass_Create
    s = SetClass()
    s.SetName("IndexTest")
    members = [
        (_ship("Alpha"), "Alpha"),
        (Torpedo(), "Torp 1"),
        (Planet_Create(170.0, ""), "Planet"),
        (RockClass_Create(1.0, name="Rock"), "Rock"),
        (Sun_Create(4000.0, 4000.0, 500.0), "Sun"),
        (App.MetaNebula_Create(0.6, 0.35, 0.72, 145.0, 10.5, "i.tga", "e.tga"),
         "Nebula"),
        (Torpedo(), "Torp 2"),
        (_ship("Bravo"), "Bravo"),
        (Waypoint(), "Way"),
        (App.CharacterClass_Create(), "Kiska"),
        (Torpedo(), "Torp 3"),
    ]
    for obj, name in members:
        s.AddObjectToSet(obj, name)
    return s


def test_class_lists_match_the_scan_for_every_ct_tag():
    s = _mixed_set()
    tags = list(object_types.registered_tags()) + [App.CT_SHIP]
    for tag in tags:
        cls = _class_for(tag)
        if not isinstance(cls, type):
            continue
        got = s.GetClassObjectList(tag)
        want = _scan(s, cls)
        assert [id(o) for o in got] == [id(o) for o in want], (tag, cls)
        assert s.GetClassObjectList(tag) is not got
    # A member added after the buckets exist joins each bucket it belongs to.
    late = _ship("Charlie")
    s.AddObjectToSet(late, "Charlie")
    for tag in tags:
        cls = _class_for(tag)
        if isinstance(cls, type):
            assert ([id(o) for o in s.GetClassObjectList(tag)]
                    == [id(o) for o in _scan(s, cls)]), (tag, cls)


def test_overwrite_keeps_the_slot():
    s = SetClass()
    a, b, c, d = (_ship(n) for n in "abcd")
    s.AddObjectToSet(a, "A")
    s.AddObjectToSet(b, "B")
    s.AddObjectToSet(c, "C")
    s.AddObjectToSet(d, "B")
    assert s.GetClassObjectList(App.CT_SHIP) == [a, d, c]
    # Popped and re-added: to the end, as the dict does.
    s.RemoveObjectFromSet("A")
    s.AddObjectToSet(a, "A")
    assert s.GetClassObjectList(App.CT_SHIP) == [d, c, a]


def test_exit_handlers_still_see_the_leaving_object(monkeypatch):
    s = SetClass()
    s.SetName("ExitTest")
    ship = _ship("Leaver")
    other = _ship("Stayer")
    s.AddObjectToSet(ship, "Leaver")
    s.AddObjectToSet(other, "Stayer")
    seen = []

    def exited(_dest, _event):
        seen.append((list(s.GetClassObjectList(App.CT_SHIP)),
                     contact_index.ships_in(s), set_index.ships_in(s)))

    mod = types.ModuleType("_tsi_exit")
    mod.Exited = exited
    monkeypatch.setitem(sys.modules, "_tsi_exit", mod)
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_EXITED_SET, s, "_tsi_exit.Exited")

    s.DeleteObjectFromSet("Leaver")

    assert len(seen) == 1
    class_list, contacts, index_contacts = seen[0]
    assert any(o is ship for o in class_list)
    assert all(o is not ship for o in contacts)
    assert index_contacts == (other,)  # LEAVING hides it from the contact view
    assert all(o is not ship for o in s.GetClassObjectList(App.CT_SHIP))
    assert all(o is not ship for o in contact_index.ships_in(s))
    assert set_index.ships_in(s) == (other,)


def test_rock_conversion_moves_buckets():
    from engine.rocks.rock import RockClass, maybe_become_rock
    s = SetClass()
    ship = _ship("Asteroid 1")
    s.AddObjectToSet(ship, "Asteroid 1")
    assert s.GetClassObjectList(App.CT_SHIP) == [ship]
    assert s.GetClassObjectList(RockClass) == []

    ship.SetGenus(App.GENUS_ASTEROID)
    assert maybe_become_rock(ship) is True

    assert s.GetClassObjectList(RockClass) == [ship]
    assert s.GetClassObjectList(App.CT_SHIP) == [ship]


def _clear_other_holders():
    """Other registries hold ships (and, through `_containing_set` or a
    bucket key, their set) until the per-test reset: the mission-scoped ones
    (host_loop.reset_mission_state, which does NOT touch the set index), the
    contact buckets and the global id registry (both cleared by
    tests/conftest.py between tests)."""
    import engine.host_loop as hl
    from engine.core import ids
    hl.reset_mission_state(None)
    contact_index.reset()
    ids._registry.clear()
    gc.collect()


def _tracked():
    t = _h.set_index_tracked()
    return t["sets"], t["entries"]


def _populated():
    s = SetClass()
    a, b = _ship("A"), _ship("B")
    s.AddObjectToSet(a, "A")
    s.AddObjectToSet(b, "B")
    s.AddObjectToSet(a, "A2")
    s.GetClassObjectList(App.CT_SHIP)
    s.GetClassObjectList(App.CT_OBJECT)
    set_index.ships_in(s)
    return s, a, b


def _key_state(key):
    """What the index holds under one address (an int: the object may be
    dead). Asserting only a test's OWN keys keeps the test independent of
    whatever else the process-global index tracks."""
    return _h.set_index_key_state(key)


_GONE = {"set": False, "watched": False, "entries": 0, "held_by": 0}


def test_a_dropped_set_is_released_without_a_reset():
    """The index holds members BORROWED and each set by a weakref whose
    callback forgets it: a set and its ships die with the last outside
    reference, and the index forgets the set, with no reset call."""
    s, a, b = _populated()
    keys = [id(o) for o in (s, a, b)]
    assert _key_state(keys[0]) == {"set": True, "watched": True, "entries": 3,
                                   "held_by": 0}
    assert _key_state(keys[1])["held_by"] == 1
    refs = [weakref.ref(o) for o in (s, a, b)]
    del s, a, b
    _clear_other_holders()
    assert [r() for r in refs] == [None, None, None]
    assert [_key_state(k) for k in keys] == [_GONE] * 3


def test_a_set_dying_with_members_inside_leaves_no_entries():
    s = SetClass()
    things = [types.SimpleNamespace() for _ in range(4)]
    for i, o in enumerate(things):
        s.AddObjectToSet(o, f"thing {i}")
    s.GetClassObjectList(types.SimpleNamespace)
    key = id(s)
    assert _key_state(key)["entries"] == 4
    ref = weakref.ref(s)
    del s
    _clear_other_holders()  # the global id registry holds every TGObject
    assert ref() is None
    assert _key_state(key) == _GONE
    assert [_key_state(id(o))["held_by"] for o in things] == [0] * 4


def test_forget_set_drops_the_set():
    s, a, b = _populated()
    set_index.forget_set(s)
    assert _key_state(id(s)) == _GONE
    assert [_key_state(id(o))["held_by"] for o in (a, b)] == [0, 0]
    set_index.forget_set(s)  # twice is harmless
    assert _key_state(id(s)) == _GONE


def _run_isolated(code):
    """Run `code` in a fresh interpreter: what it does to the set index (a
    reset, a forced collection) must not reach the live sets that
    tests/conftest.py keeps across tests in this process."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PROJECT_ROOT), str(PROJECT_ROOT / "build" / "python")]
        + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(code)],
                       cwd=PROJECT_ROOT, env=env, capture_output=True,
                       text=True, timeout=300)
    assert r.returncode == 0 and r.stdout.strip().endswith("OK"), (
        f"rc={r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr[-4000:]}")


def test_reset_forgets_every_set():
    _run_isolated("""
        import App
        import _dauntless_host as _h
        from engine.appc import set_index
        from engine.appc.sets import SetClass
        from engine.appc.ships import ShipClass_Create
        s = SetClass()
        s.AddObjectToSet(ShipClass_Create("A"), "A")
        assert _h.set_index_tracked()["sets"] >= 1
        set_index.reset()
        t = _h.set_index_tracked()
        assert (t["sets"], t["entries"], t["watched"], t["classes"]) == (0, 0, 0, 0), t
        print("OK")
    """)


def test_set_lists_survive_a_collection_inside_the_binding():
    """Review fix: sets_holding computed its set keys, THEN allocated the
    output list. With the list freelist empty that allocation can run a
    gen-0 collection whose weakref callbacks forget and free sets in a
    garbage cycle, and the binding then borrowed freed pointers (a fatal
    _PyObject_AssertFailed here). The output is allocated before the keys
    are read, so a set returned is a set still tracked."""
    _run_isolated("""
        import gc, types
        import App
        import _dauntless_host as _h
        from engine.appc import set_index
        from engine.appc.sets import SetClass
        from engine.core import ids
        x = types.SimpleNamespace()
        gc.collect()
        base = _h.set_index_tracked()["sets"]
        for trial in range(20):
            gc.collect()
            gc.disable()
            for i in range(6):
                s = SetClass()
                s.AddObjectToSet(x, "x")
                s._cycle = s  # garbage only to the cycle collector
                ids._registry.pop(s.GetObjID(), None)
            del s
            drain = [[] for _ in range(200)]  # the list freelist, emptied
            gc.set_threshold(1, 10, 10)
            gc.enable()
            got = set_index.sets_holding(x)
            gc.set_threshold(700, 10, 10)
            still = _h.set_index_tracked()["sets"] - base
            assert len(got) <= still, (trial, len(got), still)
            assert all(type(o) is SetClass for o in got)
            got = drain = None
            gc.collect()
        print("OK")
    """)


def test_every_object_returning_binding_survives_a_collection_inside_it():
    """Final-review fix: set_index_hide_all computed its changed set keys,
    THEN allocated the output list, so a gen-0 collection inside that
    allocation freed sets it was about to return (a SIGSEGV). Every binding
    that turns core keys into Python objects is driven here under the same
    pressure: a cycle of dead sets holding a visible ship, the list freelist
    drained, a gen-0 threshold of 1. A returned object must be alive and of
    the right type; a set returned must still be tracked."""
    _run_isolated("""
        import gc, faulthandler
        faulthandler.enable()
        import App
        import _dauntless_host as _h
        from App import Nebula
        from engine.appc import set_index  # configures the binding
        from engine.appc.ships import ShipClass

        class FakeSet:
            pass

        ship = object.__new__(ShipClass)
        neb = object.__new__(Nebula)
        keep = FakeSet()  # a live set the member-returning bindings read
        _h.set_index_add(keep, "ship", ship, True, 7, -1)
        _h.set_index_add(keep, "neb", neb, False, -1, -1)
        gc.collect()
        base = _h.set_index_tracked()["sets"]
        CALLS = {
            "class_objects": (lambda: _h.set_index_class_objects(keep, ShipClass),
                              ShipClass),
            "ships": (lambda: _h.set_index_ships(keep), ShipClass),
            "nebulae": (lambda: _h.set_index_nebulae(keep), Nebula),
            "targeting": (lambda: _h.set_index_targeting(keep, 7), ShipClass),
            "sets_holding": (lambda: _h.set_index_sets_holding(ship), FakeSet),
            "hide_all": (lambda: _h.set_index_hide_all(), FakeSet),
        }
        for name, (call, kind) in CALLS.items():
            for trial in range(20):
                _h.set_index_add(keep, "ship", ship, True, 7, -1)  # re-shown
                _h.set_index_add(keep, "neb", neb, False, -1, -1)
                gc.collect()
                gc.disable()
                for i in range(6):
                    s = FakeSet()
                    s._cycle = s  # garbage only to the cycle collector
                    _h.set_index_add(s, "x", ship, True, 7, -1)  # visible: changed
                del s
                drain = [[] for _ in range(200)]  # the list freelist, emptied
                gc.set_threshold(1, 10, 10)
                gc.enable()
                got = call()
                gc.set_threshold(700, 10, 10)
                assert all(type(o) is kind for o in got), (name, trial)
                if kind is FakeSet:
                    still = _h.set_index_tracked()["sets"]
                    assert len(got) <= still, (name, trial, len(got), still)
                else:
                    assert len(got) >= 1, (name, trial)
                got = drain = None
                gc.collect()
            assert _h.set_index_tracked()["sets"] == base, name
            print(name, "survived", flush=True)  # names the crashing binding
        print("OK")
    """)


def test_a_set_outliving_reset_mission_state_keeps_its_lists():
    """HostController's swap runs reset_mission_state BEFORE
    reset_sdk_globals tears down against still-live sets, and conftest keeps
    sets across tests: a live set's lists must survive it."""
    import engine.host_loop as hl
    from engine.appc.projectiles import Torpedo
    s, a, b = _populated()
    t = Torpedo()
    s.AddObjectToSet(t, "Torp")
    ships = s.GetClassObjectList(App.CT_SHIP)
    torps = s.GetClassObjectList(App.CT_TORPEDO)
    contacts = set_index.ships_in(s)
    hl.reset_mission_state(None)
    assert s.GetClassObjectList(App.CT_SHIP) == ships == [a, b, a]
    assert s.GetClassObjectList(App.CT_TORPEDO) == torps == [t]
    assert set_index.ships_in(s) == contacts == (a, b)


class _Boom(type):
    """A class test that raises on one chosen member while armed."""
    bad = None

    def __instancecheck__(cls, obj):
        if obj is _Boom.bad:
            raise RuntimeError("class test raised")
        return isinstance(obj, types.SimpleNamespace)


class _Picky(metaclass=_Boom):
    pass


def test_a_raising_class_test_leaves_no_half_built_bucket():
    """Final-review fix: an isinstance raising partway through building a
    bucket (create_bucket) or re-testing a member (reassess) erased nothing,
    so the next read silently returned the partial bucket. The bucket is
    erased: the next read builds it again (and raises again)."""
    s = SetClass()
    first, bad, last = (types.SimpleNamespace(n=i) for i in range(3))
    for name, o in (("First", first), ("Bad", bad), ("Last", last)):
        s.AddObjectToSet(o, name)
    _Boom.bad = bad
    try:
        for _ in range(2):  # create_bucket: raises, and raises again
            with pytest.raises(RuntimeError):
                set_index.class_objects(s, _Picky)
        _Boom.bad = None
        assert set_index.class_objects(s, _Picky) == [first, bad, last]
        other = types.SimpleNamespace(n=9)
        _Boom.bad = other
        with pytest.raises(RuntimeError):  # reassess, on an overwrite
            s.AddObjectToSet(other, "Bad")
        with pytest.raises(RuntimeError):
            set_index.class_objects(s, _Picky)
        _Boom.bad = None
        assert set_index.class_objects(s, _Picky) == [first, other, last]
        assert set_index.class_objects(s, _Picky) == _scan(s, types.SimpleNamespace)
    finally:
        _Boom.bad = None


class _Thing:
    pass


class _NotThing:
    pass


class _BoomThing(type):
    armed = False

    def __instancecheck__(cls, obj):
        if _BoomThing.armed:
            raise RuntimeError("class test raised")
        return type(obj) is _Thing


class _PickyThing(metaclass=_BoomThing):
    pass


def test_a_raising_reclassification_leaves_no_stale_bucket_in_any_set():
    """A class test raising while one set re-tests a reclassified object
    still re-tests (and so erases) the other sets' buckets: none keeps the
    object under its old class."""
    a = _Thing()
    s1, s2 = SetClass(), SetClass()
    s1.AddObjectToSet(a, "A")
    s2.AddObjectToSet(a, "A")
    assert set_index.class_objects(s1, _PickyThing) == [a]
    assert set_index.class_objects(s2, _PickyThing) == [a]
    a.__class__ = _NotThing
    _BoomThing.armed = True
    try:
        with pytest.raises(RuntimeError):
            _h.set_index_reclassified(a, False)
    finally:
        _BoomThing.armed = False
    assert set_index.class_objects(s1, _PickyThing) == []
    assert set_index.class_objects(s2, _PickyThing) == []


def test_a_removed_object_is_released():
    s = SetClass()
    a, b = _ship("A"), _ship("B")
    s.AddObjectToSet(a, "A")
    s.AddObjectToSet(b, "B")
    s.AddObjectToSet(_ship("C"), "B")  # the overwrite drops b
    s.RemoveObjectFromSet("A")
    refs = [weakref.ref(o) for o in (a, b)]
    del a, b
    _clear_other_holders()
    assert [r() for r in refs] == [None, None]


def test_audit_flags_a_drift(monkeypatch):
    s = SetClass()
    s.SetName("AuditTest")
    s.AddObjectToSet(_ship("A"), "A")
    monkeypatch.setenv("DAUNTLESS_SET_INDEX_AUDIT", "1")
    assert len(s.GetClassObjectList(App.CT_SHIP)) == 1
    s._objects["Poked"] = _ship("Poked")  # bypasses the door
    with pytest.raises(AssertionError, match="AuditTest"):
        s.GetClassObjectList(App.CT_SHIP)


def test_audit_flags_a_bypassing_pop(monkeypatch):
    """A pop around the doors leaves the index holding a borrowed key the set
    no longer keeps alive: the audit reports the length mismatch BEFORE it
    reads the index. The CT_SHIP lists alone would still agree here."""
    from engine.appc.projectiles import Torpedo
    s = SetClass()
    s.SetName("AuditPop")
    s.AddObjectToSet(_ship("A"), "A")
    torp = Torpedo()
    s.AddObjectToSet(torp, "Torp")
    monkeypatch.setenv("DAUNTLESS_SET_INDEX_AUDIT", "1")
    assert len(s.GetClassObjectList(App.CT_SHIP)) == 1
    s._objects.pop("Torp")  # bypasses the door; `torp` keeps it alive
    with pytest.raises(AssertionError, match="AuditPop"):
        s.GetClassObjectList(App.CT_SHIP)
    s._objects["Torp"] = torp  # back in step for teardown


def test_a_non_string_identifier_is_refused_before_any_change():
    s = SetClass()
    ship = _ship("A")
    before = _tracked()
    with pytest.raises(TypeError):
        s.AddObjectToSet(ship, 5)
    assert s._objects == {}
    assert _tracked() == before
    assert ship.GetContainingSet() is not s


def test_removing_an_absent_or_non_string_name_is_a_silent_no_op():
    s = SetClass()
    s.AddObjectToSet(_ship("A"), "A")
    assert s.RemoveObjectFromSet(None) is None
    assert s.RemoveObjectFromSet("nope") is None
    assert s.DeleteObjectFromSet(None) is None
    assert s.DeleteObjectFromSet(7) is None
    assert [o.GetName() for o in s.GetClassObjectList(App.CT_SHIP)] == ["A"]


def test_a_set_deleted_by_a_mission_change_still_answers_like_its_dict():
    """Ruling: mission_change no longer forgets a deleted set. While anything
    still holds it, its lists match its `_objects`; its weakref forgets it
    when it dies."""
    from tests.helpers.mission_change_fixtures import (
        _forget_world, _install, _world)
    from engine.core import mission_change
    try:
        _world()
        doomed = App.g_kSetManager.GetSet("Beol4")
        npc = App.ShipClass_Create()
        npc.SetName("Warbird 1")
        doomed.AddObjectToSet(npc, "Warbird 1")
        _install("_t.Old", Terminate=lambda m: None)
        _install("_t.New", Initialize=lambda m: None)
        assert mission_change.change(mission="_t.New") is True
        assert App.g_kSetManager.GetSet("Beol4") is not doomed
        assert doomed.GetClassObjectList(App.CT_SHIP) == _scan(doomed, ShipClass)
        assert npc in doomed.GetClassObjectList(App.CT_SHIP)
    finally:
        _forget_world()


# ── Review Focus 5: one writer of SetClass._objects ──────────────────────────

_MUTATORS = {"pop", "clear", "update", "setdefault", "popitem"}
_DOORS = {"AddObjectToSet", "RemoveObjectFromSet", "DeleteObjectFromSet"}
# Rebinding `_objects` is allowed only where SetClass creates it, and in
# classes that own an UNRELATED attribute of the same name (a list, not a
# set's dict): (file relative to the project root, class, function).
_REBIND_ALLOWED = {
    ("engine/appc/sets.py", "SetClass", "__init__"),
    # engine.appc.planet.ProximityManager's own object list.
    ("engine/appc/planet.py", "ProximityManager", "__init__"),
    ("engine/appc/planet.py", "ProximityManager", "_forget"),
}


def _is_objects(node):
    """`<x>._objects`, or `<x>.__dict__["_objects"]`."""
    if isinstance(node, ast.Attribute):
        return node.attr == "_objects"
    return (isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "__dict__"
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "_objects")


def _flat(targets):
    for t in targets:
        if isinstance(t, (ast.Tuple, ast.List)):
            yield from _flat(t.elts)
        elif isinstance(t, ast.Starred):
            yield from _flat([t.value])
        else:
            yield t


def _writes(tree):
    """(line, class, function, kind) for every mutation of `_objects`:
    kind "item" (an item written, deleted or a mutator called) or "rebind"
    (the attribute itself assigned, deleted or set via setattr)."""
    out = []

    def visit(node, cls, func):
        if isinstance(node, ast.ClassDef):
            cls, func = node.name, None
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node.name
        kinds = []
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            targets = (node.targets if isinstance(node, (ast.Assign, ast.Delete))
                       else [node.target])
            for t in _flat(targets):
                if isinstance(t, ast.Subscript) and _is_objects(t.value):
                    kinds.append("item")
                elif _is_objects(t):
                    kinds.append("rebind")
        if isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr in _MUTATORS
                    and _is_objects(f.value)):
                kinds.append("item")
            named = ((isinstance(f, ast.Name) and f.id in ("setattr", "delattr"))
                     or (isinstance(f, ast.Attribute)
                         and f.attr in ("__setattr__", "__delattr__")))
            if named and any(isinstance(a, ast.Constant) and a.value == "_objects"
                             for a in node.args):
                kinds.append("rebind")
        for kind in kinds:
            out.append((node.lineno, cls, func, kind))
        for child in ast.iter_child_nodes(node):
            visit(child, cls, func)

    visit(tree, None, None)
    return out


def _sources():
    files = sorted((PROJECT_ROOT / "engine").rglob("*.py"))
    files += [PROJECT_ROOT / "App.py", PROJECT_ROOT / "tools" / "mission_harness.py"]
    return files


def test_get_class_object_list_does_not_import_the_facade_per_call():
    """Final-review fix: GetClassObjectList is the AI's hot path; the facade
    is fetched once into a module global, not imported on every call (a
    top-level import would cycle through App)."""
    src = (PROJECT_ROOT / "engine" / "appc" / "sets.py").read_text()
    method = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "GetClassObjectList")
    imported = [a.name for n in ast.walk(method)
                if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names]
    assert "set_index" not in imported


def test_objects_dict_has_one_writer():
    bad, door_hits = [], []
    for path in _sources():
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, cls, func, kind in _writes(tree):
            if kind == "item" and rel == "engine/appc/sets.py" and func in _DOORS:
                door_hits.append(func)
            elif kind == "rebind" and (rel, cls, func) in _REBIND_ALLOWED:
                pass
            else:
                bad.append(f"{rel}:{line} {cls}.{func} ({kind})")
    assert not bad, "a second write path into SetClass._objects: " + ", ".join(bad)
    assert set(door_hits) == _DOORS  # the guard still sees the three doors


def _lines(src):
    return [(line, kind) for line, _c, _f, kind in _writes(ast.parse(src))]


def test_the_writer_guard_catches_each_item_mutation():
    src = (
        "def f(s, k):\n"
        "    s._objects[k] = 1\n"
        "    del s._objects[k]\n"
        "    s._objects.pop(k)\n"
        "    s._objects.clear()\n"
        "    s._objects.update({})\n"
        "    s._objects.setdefault(k, 1)\n"
        "    s._objects.popitem()\n"
        "    s._objects.get(k)\n"
        "    s.__dict__['_objects'][k] = 1\n"
        "    s.__dict__['_objects'].pop(k)\n"
    )
    assert _lines(src) == [(n, "item") for n in (2, 3, 4, 5, 6, 7, 8, 10, 11)]


def test_the_writer_guard_catches_each_rebind():
    src = (
        "def f(s, d):\n"
        "    s._objects = {}\n"
        "    s._objects: dict = {}\n"
        "    s._objects |= d\n"
        "    del s._objects\n"
        "    a, s._objects = 1, {}\n"
        "    setattr(s, '_objects', {})\n"
        "    object.__setattr__(s, '_objects', {})\n"
        "    delattr(s, '_objects')\n"
        "    s.__dict__['_objects'] = {}\n"
        "    del s.__dict__['_objects']\n"
        "    x = s.__dict__['_objects']\n"
        "    getattr(s, '_objects')\n"
    )
    assert _lines(src) == [(n, "rebind") for n in range(2, 12)]


def test_the_writer_guard_allows_only_the_listed_rebinds():
    src = (
        "class SetClass:\n"
        "    def __init__(self):\n"
        "        self._objects = {}\n"
        "    def Other(self):\n"
        "        self._objects = {}\n"
    )
    hits = [(c, f) for _l, c, f, _k in _writes(ast.parse(src))]
    assert hits == [("SetClass", "__init__"), ("SetClass", "Other")]
    assert ("engine/appc/sets.py", "SetClass", "Other") not in _REBIND_ALLOWED


# Recorded at 738b126bd, when contact_index kept its own buckets.
EXPECTED_PUSHES = [
    ("PushSet", ["A"], []),
    "--nebula",
    ("PushSet", ["A"], ["Neb"]),
    "--torpedo",
    "--second and third ship",
    ("PushSet", ["A", "B"], ["Neb"]),
    ("PushSet", ["A", "B", "C"], ["Neb"]),
    "--same ship added again under its own identifier",
    "--remove, delete",
    ("PushSet", ["B", "C"], ["Neb"]),
    ("PushSet", ["B", "C"], []),
    "--absent names",
    "--forget_set, reset",
    ("OtherSet", ["A"], []),
    ("OtherSet", [], []),
    ("PushSet", ["B", "C", "A"], []),
    ("PushSet", [], []),
]


def test_push_set_members_sees_the_same_lists_at_the_same_points(monkeypatch):
    """The native combat mirror holds each set's ship and nebula lists. Which
    door pushes them, in which order, and what lists they carry, was recorded
    from contact_index's own buckets before they moved onto the set index;
    the move must not change a single entry."""
    from engine.appc import native_combat
    from engine.appc.projectiles import Torpedo
    seen = []
    real = native_combat.push_set_members

    def spy(pSet):
        seen.append((pSet.GetName(),
                     [o.GetName() for o in contact_index.ships_in(pSet)],
                     [o.GetName() for o in contact_index.nebulae_in(pSet)]))
        return real(pSet)

    pSet = SetClass()
    pSet.SetName("PushSet")
    other = SetClass()
    other.SetName("OtherSet")
    a, b, c = _ship("A"), _ship("B"), _ship("C")
    neb = App.MetaNebula_Create(0.6, 0.35, 0.72, 145.0, 10.5, "i.tga", "e.tga")
    neb.SetName("Neb")
    monkeypatch.setattr(native_combat, "push_set_members", spy)

    pSet.AddObjectToSet(a, "A")
    seen.append("--nebula")
    pSet.AddObjectToSet(neb, "Neb")
    seen.append("--torpedo")
    pSet.AddObjectToSet(Torpedo(), "Torp")
    seen.append("--second and third ship")
    pSet.AddObjectToSet(b, "B")
    pSet.AddObjectToSet(c, "C")
    seen.append("--same ship added again under its own identifier")
    pSet.AddObjectToSet(a, "A")
    seen.append("--remove, delete")
    pSet.RemoveObjectFromSet("A")
    pSet.DeleteObjectFromSet("Neb")
    seen.append("--absent names")
    pSet.RemoveObjectFromSet("Nope")
    pSet.DeleteObjectFromSet("Nope")
    seen.append("--forget_set, reset")
    other.AddObjectToSet(a, "A")
    contact_index.forget_set(other)
    pSet.AddObjectToSet(a, "A")
    contact_index.reset()

    assert seen == EXPECTED_PUSHES


def test_drift_case_an_overwritten_identifier_drops_the_old_ship():
    """Recorded drift case 1: contact_index's own bucket kept the replaced
    ship forever; the set index mirrors the dict slot."""
    s = SetClass()
    old, new = _ship("Old"), _ship("New")
    s.AddObjectToSet(old, "Slot")
    s.AddObjectToSet(new, "Slot")
    assert contact_index.ships_in(s) == (new,)
    assert contact_index.sets_holding(old) == []


def test_drift_case_an_object_under_a_second_identifier_stays_listed():
    """Recorded drift case 2: one removal used to drop the ship from the
    contact bucket although the set still held it under another name."""
    s = SetClass()
    a = _ship("A")
    s.AddObjectToSet(a, "One")
    s.AddObjectToSet(a, "Two")
    s.RemoveObjectFromSet("One")
    assert contact_index.ships_in(s) == (a,)
    assert contact_index.sets_holding(a) == [s]
    s.RemoveObjectFromSet("Two")
    assert contact_index.ships_in(s) == ()


def test_drift_case_a_hidden_entry_shown_again_keeps_its_slot():
    """Recorded drift case 3: after a hide (contact_index.reset /
    forget_set), an entry shown again by an overwrite takes its ORIGINAL
    slot position, as the dict does; the old buckets appended it at the end,
    which gave (X, Y) here. The index answers (Y, X)."""
    s = SetClass()
    x, y = _ship("X"), _ship("Y")
    s.AddObjectToSet(y, "Y")
    contact_index.forget_set(s)
    s.AddObjectToSet(x, "X")
    s.AddObjectToSet(y, "Y")  # re-added under its old name: an overwrite
    assert contact_index.ships_in(s) == (y, x)
    assert s.GetClassObjectList(App.CT_SHIP) == [y, x]


def test_reset_and_forget_hide_the_view_but_not_the_class_lists():
    s, t = SetClass(), SetClass()
    a, b = _ship("A"), _ship("B")
    s.AddObjectToSet(a, "A")
    t.AddObjectToSet(b, "B")
    contact_index.forget_set(s)
    assert contact_index.ships_in(s) == ()
    assert contact_index.ships_in(t) == (b,)
    contact_index.reset()
    assert contact_index.ships_in(t) == ()
    assert s.GetClassObjectList(App.CT_SHIP) == [a]
    assert t.GetClassObjectList(App.CT_SHIP) == [b]
    c = _ship("C")
    s.AddObjectToSet(c, "C")
    assert contact_index.ships_in(s) == (c,)
    t.RemoveObjectFromSet("B")  # a hidden entry: nothing to change
    assert contact_index.ships_in(t) == ()
    assert t.GetClassObjectList(App.CT_SHIP) == []
