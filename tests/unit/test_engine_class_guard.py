"""The engine class guard (tests/helpers/engine_class_guard.py, wired as the
autouse `_guard_engine_classes` fixture in tests/conftest.py) fails the test
that mutates an engine class and leaves it changed.

Why: tests/integration/conftest.py's target_ship_at and
test_engagement_distance_diag assigned `ShipClass.GetRadius = lambda ...`
and never put it back. ShipClass stayed modified for the rest of the process
and the damage surfaced an hour later as ~190 failures in unrelated
native-combat files. The guard pins the blame on the polluting test instead.

These drive the guard's check directly (a fresh EngineClassGuard per test, so
the conftest instance only ever sees the restored state), plus one check that
the real fixture is ordered to tear down AFTER monkeypatch.
"""
import importlib
import sys
import textwrap

import pytest

from engine.appc.objects import ObjectClass
from engine.appc.ships import ShipClass
from tests.helpers.engine_class_guard import (
    EngineClassGuard, fail_on_mutations, format_mutation)


def _guard():
    g = EngineClassGuard()
    g.sync()
    return g


def test_bare_class_assignment_is_reported_and_restored():
    g = _guard()
    assert "GetRadius" not in vars(ShipClass)
    stand_in = lambda self: 1.0  # noqa: E731
    try:
        ShipClass.GetRadius = stand_in
        mutations = g.check()
    finally:
        if vars(ShipClass).get("GetRadius") is stand_in:
            del ShipClass.GetRadius
    assert len(mutations) == 1
    text = format_mutation(mutations[0])
    assert "engine.appc.ships.ShipClass.GetRadius" in text
    # Inherited before the assignment: name where it really resolved.
    assert "was engine.appc.objects.ObjectClass.GetRadius" in text
    assert "<lambda>" in text
    # The guard put it back (deleted the added override).
    assert "GetRadius" not in vars(ShipClass)
    assert ShipClass.GetRadius is ObjectClass.GetRadius


def test_replaced_own_method_is_reported_and_restored():
    g = _guard()
    original = vars(ObjectClass)["GetRadius"]
    try:
        ObjectClass.GetRadius = lambda self: 2.0
        mutations = g.check()
    finally:
        ObjectClass.GetRadius = original
    assert [m.attr for m in mutations] == ["GetRadius"]
    assert mutations[0].cls is ObjectClass
    assert vars(ObjectClass)["GetRadius"] is original


def test_deleted_method_is_reported_and_restored():
    g = _guard()
    original = vars(ObjectClass)["GetRadius"]
    try:
        del ObjectClass.GetRadius
        mutations = g.check()
    finally:
        if "GetRadius" not in vars(ObjectClass):
            ObjectClass.GetRadius = original
    assert [m.attr for m in mutations] == ["GetRadius"]
    assert vars(ObjectClass)["GetRadius"] is original


def test_monkeypatch_that_is_undone_is_not_reported(monkeypatch):
    g = _guard()
    monkeypatch.setattr(ShipClass, "GetRadius", lambda self: 3.0)
    monkeypatch.undo()
    assert g.check() == []


def test_monkeypatch_left_for_the_fixture_does_not_trip_the_real_guard(
        monkeypatch, request):
    # The conftest guard must tear down AFTER monkeypatch has undone this:
    # pytest sets fixtures up in `fixturenames` order and tears them down in
    # reverse, so the guard has to come first. If it did not, this test would
    # ERROR at teardown.
    names = request.fixturenames
    assert names.index("_guard_engine_classes") < names.index("monkeypatch")
    monkeypatch.setattr(ShipClass, "GetRadius", lambda self: 4.0)


def test_data_attribute_changes_are_not_reported():
    g = _guard()
    had = "_ecg_probe" in vars(ShipClass)
    try:
        ShipClass._ecg_probe = 5                 # added data
        ObjectClass._ecg_probe_counter = [1, 2]  # added data, other class
        assert g.check() == []
        ShipClass._ecg_probe = 6                 # changed data
        assert g.check() == []
    finally:
        if not had:
            del ShipClass._ecg_probe
        del ObjectClass._ecg_probe_counter
    assert g.check() == []                      # deleted data


def test_data_attribute_replaced_by_a_function_is_reported():
    g = _guard()
    ShipClass._ecg_probe_value = 1
    try:
        g.sync()
        ShipClass._ecg_probe_value = lambda self: 1
        mutations = g.check()
        assert [m.attr for m in mutations] == ["_ecg_probe_value"]
        assert vars(ShipClass)["_ecg_probe_value"] == 1
    finally:
        del ShipClass._ecg_probe_value


def test_changes_between_tests_are_accepted_by_sync():
    # A module-scoped fixture may patch a class before the test window and
    # restore it after: sync() (run at each test's setup) re-baselines, so
    # only changes made INSIDE the window are blamed on the test.
    g = _guard()
    stand_in = lambda self: 5.0  # noqa: E731
    try:
        ShipClass.GetRadius = stand_in
        g.sync()
        assert g.check() == []
        del ShipClass.GetRadius
        g.sync()
        assert g.check() == []
    finally:
        if vars(ShipClass).get("GetRadius") is stand_in:
            del ShipClass.GetRadius


def test_fail_on_mutations_fails_naming_each_attribute():
    g = _guard()
    try:
        ShipClass.GetRadius = lambda self: 6.0
        mutations = g.check()
    finally:
        vars(ShipClass).get("GetRadius") and delattr(ShipClass, "GetRadius")
    with pytest.raises(pytest.fail.Exception) as info:
        fail_on_mutations(mutations)
    msg = str(info.value)
    assert "engine class mutated and not restored" in msg
    assert "engine.appc.ships.ShipClass.GetRadius" in msg
    assert "monkeypatch" in msg
    fail_on_mutations([])  # nothing to report: no failure


@pytest.fixture
def probe_pkg(tmp_path, monkeypatch):
    """A throwaway package the guard is pointed at, so a REAL
    importlib.reload can run without reloading (and splitting the class
    identity of) a module the rest of the suite imports."""
    pkg = tmp_path / "_ecg_probe_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text(textwrap.dedent("""
        class Widget:
            def spin(self):
                return 1
    """))
    monkeypatch.syspath_prepend(str(tmp_path))
    yield "_ecg_probe_pkg"
    for name in list(sys.modules):
        if name == "_ecg_probe_pkg" or name.startswith("_ecg_probe_pkg."):
            del sys.modules[name]


def test_reloaded_module_neither_crashes_nor_false_reports(probe_pkg):
    mod = importlib.import_module(probe_pkg + ".mod")
    g = EngineClassGuard(packages=(probe_pkg,))
    g.sync()
    old_cls = mod.Widget
    importlib.reload(mod)                     # same module object, new class
    assert mod.Widget is not old_cls
    assert g.check() == []
    # The NEW class is tracked from here on.
    mod.Widget.spin = lambda self: 2
    assert [(m.cls, m.attr) for m in g.check()] == [(mod.Widget, "spin")]


def test_replaced_module_object_is_rebaselined(probe_pkg):
    mod = importlib.import_module(probe_pkg + ".mod")
    g = EngineClassGuard(packages=(probe_pkg,))
    g.sync()
    del sys.modules[probe_pkg + ".mod"]
    fresh = importlib.import_module(probe_pkg + ".mod")
    assert fresh is not mod
    assert g.check() == []
    fresh.Widget.spin = lambda self: 3
    assert [(m.cls, m.attr) for m in g.check()] == [(fresh.Widget, "spin")]


def test_newly_imported_module_is_tracked(probe_pkg):
    g = EngineClassGuard(packages=(probe_pkg,))
    g.sync()
    mod = importlib.import_module(probe_pkg + ".mod")  # imported after sync
    assert g.check() == []
    mod.Widget.spin = lambda self: 4
    assert [(m.cls, m.attr) for m in g.check()] == [(mod.Widget, "spin")]


_E2E_PROBE = '''
import pytest
from engine.appc.ships import ShipClass

def test_polluter():
    ShipClass.GetRadius = lambda self: 1.0

def test_after_polluter_sees_it_restored():
    assert "GetRadius" not in vars(ShipClass)

def test_monkeypatched(monkeypatch):
    monkeypatch.setattr(ShipClass, "GetRadius", lambda self: 2.0)

@pytest.mark.mutates_engine_classes
def test_marked():
    ShipClass.GetRadius = lambda self: 3.0

def test_after_marked_sees_the_change_kept(monkeypatch):
    assert "GetRadius" in vars(ShipClass)
    monkeypatch.delattr(ShipClass, "GetRadius")
'''


def test_real_fixture_errors_the_polluting_test_only(tmp_path):
    # End to end through the real autouse fixture: a pytest subprocess with
    # tests/conftest.py loaded as a plugin runs a probe file. Only the bare
    # assignment is an ERROR (the gate's `^ERROR <nodeid>` line), the
    # monkeypatched and the marked tests pass, and the next test runs on the
    # restored class.
    import os
    import subprocess
    from pathlib import Path

    probe = tmp_path / "test_ecg_probe.py"
    probe.write_text(_E2E_PROBE)
    root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tests.conftest",
         "-p", "no:cacheprovider", "-q", "-rfE", "-W", "ignore", str(probe)],
        cwd=root, capture_output=True, text=True, timeout=300,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    out = proc.stdout + proc.stderr
    errors = [ln for ln in out.splitlines() if ln.startswith("ERROR ")]
    assert len(errors) == 1, out
    assert errors[0].endswith("::test_polluter"), out
    assert ("engine class mutated and not restored: "
            "engine.appc.ships.ShipClass.GetRadius (was "
            "engine.appc.objects.ObjectClass.GetRadius, now "
            "test_ecg_probe.test_polluter.<locals>.<lambda>)") in out
    # test_polluter itself passes; its teardown is the one ERROR.
    assert "5 passed, 1 error" in out, out
