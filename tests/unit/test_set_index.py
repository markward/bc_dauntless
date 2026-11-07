"""The native set index (engine/appc/set_index.py) answers
SetClass.GetClassObjectList exactly as the old scan of `SetClass._objects`
did: same objects, same order, a new list each call.

Spec: docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md
§4.1; plan docs/superpowers/plans/2026-11-07-phase6-ai-p1-set-index.md.
"""
import ast
import gc
import sys
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
                     contact_index.ships_in(s)))

    mod = types.ModuleType("_tsi_exit")
    mod.Exited = exited
    monkeypatch.setitem(sys.modules, "_tsi_exit", mod)
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_EXITED_SET, s, "_tsi_exit.Exited")

    s.DeleteObjectFromSet("Leaver")

    assert len(seen) == 1
    class_list, contacts = seen[0]
    assert any(o is ship for o in class_list)
    assert all(o is not ship for o in contacts)
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


def _clear_everything_but_the_index(monkeypatch):
    """Other registries hold ships too until the per-test reset: the
    mission-scoped ones (host_loop.reset_mission_state, run here with the set
    index's own reset neutralised), the contact buckets and the global id
    registry (both cleared by tests/conftest.py between tests). After this
    only the index can be keeping them alive."""
    import engine.host_loop as hl
    from engine.core import ids
    monkeypatch.setattr(set_index, "reset", lambda: None)
    hl.reset_mission_state(None)
    monkeypatch.undo()
    contact_index.reset()
    ids._registry.clear()
    gc.collect()


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


def test_reset_releases_every_reference(monkeypatch):
    s, a, b = _populated()
    refs = [weakref.ref(o) for o in (s, a, b)]
    del s, a, b
    _clear_everything_but_the_index(monkeypatch)
    assert all(r() is not None for r in refs)  # the index alone holds them
    set_index.reset()
    gc.collect()
    assert [r() for r in refs] == [None, None, None]
    assert _h.set_index_held_refs() == 0


def test_forget_set_releases_every_reference(monkeypatch):
    s, a, b = _populated()
    refs = [weakref.ref(o) for o in (s, a, b)]
    _clear_everything_but_the_index(monkeypatch)
    set_index.forget_set(s)
    del s, a, b
    gc.collect()
    assert [r() for r in refs] == [None, None, None]


def test_a_removed_object_is_released(monkeypatch):
    s = SetClass()
    a, b = _ship("A"), _ship("B")
    s.AddObjectToSet(a, "A")
    s.AddObjectToSet(b, "B")
    s.AddObjectToSet(_ship("C"), "B")  # the overwrite drops b
    s.RemoveObjectFromSet("A")
    refs = [weakref.ref(o) for o in (a, b)]
    del a, b
    _clear_everything_but_the_index(monkeypatch)
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


# ── Review Focus 5: one writer of SetClass._objects ──────────────────────────

_MUTATORS = {"pop", "clear", "update", "setdefault", "popitem"}
_DOORS = {"AddObjectToSet", "RemoveObjectFromSet", "DeleteObjectFromSet"}


def _is_objects(node):
    return isinstance(node, ast.Attribute) and node.attr == "_objects"


def _writes(tree):
    """(line, function) for every mutation of an attribute `_objects`."""
    out = []

    def visit(node, func):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node.name
        hit = False
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            targets = (node.targets if isinstance(node, (ast.Assign, ast.Delete))
                       else [node.target])
            for t in targets:
                if isinstance(t, ast.Subscript) and _is_objects(t.value):
                    hit = True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in _MUTATORS and _is_objects(node.func.value)):
            hit = True
        if hit:
            out.append((node.lineno, func))
        for child in ast.iter_child_nodes(node):
            visit(child, func)

    visit(tree, None)
    return out


def _sources():
    files = sorted((PROJECT_ROOT / "engine").rglob("*.py"))
    files += [PROJECT_ROOT / "App.py", PROJECT_ROOT / "tools" / "mission_harness.py"]
    return files


def test_objects_dict_has_one_writer():
    sets_py = PROJECT_ROOT / "engine" / "appc" / "sets.py"
    bad, door_hits = [], []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, func in _writes(tree):
            if path == sets_py and func in _DOORS:
                door_hits.append(func)
            else:
                bad.append(f"{path.relative_to(PROJECT_ROOT)}:{line} ({func})")
    assert not bad, "a second write path into SetClass._objects: " + ", ".join(bad)
    assert set(door_hits) == _DOORS  # the guard still sees the three doors


def test_the_writer_guard_catches_each_mutation():
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
    )
    assert [line for line, _ in _writes(ast.parse(src))] == [2, 3, 4, 5, 6, 7, 8]
