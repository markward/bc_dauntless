"""Catch the test that mutates an engine class and leaves it changed.

A test that writes `ShipClass.GetRadius = lambda ...` and never puts it back
changes ShipClass for the rest of the pytest process; the damage surfaces far
away (an hour later, ~190 failures in unrelated native-combat files). The
autouse `_guard_engine_classes` fixture in tests/conftest.py runs this guard
around every test: `sync()` at setup, `check()` at teardown, and FAILS the test
whose own window changed a class.

What is compared: the OWN `__dict__` of every class defined in an imported
module of the guarded packages (default `engine`), and only entries whose old
or new value is callable or a descriptor (function, property, classmethod,
staticmethod, anything whose type has `__get__`), by identity -- including such
an entry being added or deleted. Plain data attributes are ignored: engine code
legitimately mutates class-level caches and counters at run time.

Why per-test windows, not one baseline for the process: a module- or
session-scoped fixture may patch a class before its first test and restore it
after its last. A process-wide baseline would take the patched state as truth
and then "restore" the patch once the fixture had cleaned up. `sync()` accepts
whatever happened between tests; only changes made inside a test's own window
(after every earlier fixture set up, before monkeypatch and the test's own
fixtures tore down) are blamed on it.

Reloads: `importlib.reload` makes NEW class objects in the same module object;
a `del sys.modules[...]` + re-import makes a new module object. Both are picked
up on the next sync/check (the module attribute no longer is the class we
tracked, or the module object changed) and the new classes are baselined at
first sight. The old class objects stay tracked; they are simply never
changed.

Cost: one C-level identity sweep per class (`map(d.get, names)` against the
snapshot tuple) when nothing changed; the precise per-attribute diff runs only
for a class whose dict differs.
"""
from collections import namedtuple
from itertools import repeat
from operator import is_
import sys

import pytest

_MISSING = object()

Mutation = namedtuple("Mutation", "cls attr old new")


def _guarded(value):
    """Callable or descriptor: the values whose replacement changes behaviour."""
    return value is not _MISSING and (
        callable(value) or hasattr(type(value), "__get__"))


def _describe(value):
    if value is _MISSING:
        return "<absent>"
    target = getattr(value, "__func__", value)  # classmethod/staticmethod
    if isinstance(value, property) and value.fget is not None:
        target = value.fget
    module = getattr(target, "__module__", None)
    qualname = getattr(target, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str):
        kind = type(value).__name__
        prefix = "" if kind in ("function", "type") else kind + " "
        return "%s%s.%s" % (prefix, module, qualname)
    text = repr(value)
    return text if len(text) <= 80 else text[:77] + "..."


def _inherited(cls, name):
    for base in cls.__mro__[1:]:
        if name in vars(base):
            return vars(base)[name]
    return _MISSING


def format_mutation(m):
    old = m.old
    if old is _MISSING:
        old = _inherited(m.cls, m.attr)  # an added override: show what it hid
    return "%s.%s.%s (was %s, now %s)" % (
        m.cls.__module__, m.cls.__qualname__, m.attr,
        _describe(old), _describe(m.new))


def fail_on_mutations(mutations):
    """pytest.fail naming every mutation; no-op when there are none."""
    if not mutations:
        return
    lines = ["engine class mutated and not restored: " + format_mutation(m)
             for m in mutations]
    lines.append("(the guard has restored the original; use monkeypatch, or "
                 "mark a deliberate change @pytest.mark.mutates_engine_classes)")
    pytest.fail("\n".join(lines), pytrace=False)


class _Snap:
    __slots__ = ("cls", "names", "values")

    def __init__(self, cls):
        self.cls = cls
        self.take()

    def take(self):
        d = vars(self.cls)
        self.names = tuple(d)
        self.values = tuple(d.values())

    def unchanged(self):
        d = vars(self.cls)
        return len(d) == len(self.names) and all(
            map(is_, map(d.get, self.names, repeat(_MISSING)), self.values))

    def diff(self):
        """Mutations of callable/descriptor entries since the snapshot."""
        d = vars(self.cls)
        old = dict(zip(self.names, self.values))
        out = []
        for name, before in old.items():
            now = d.get(name, _MISSING)
            if now is not before and (_guarded(before) or _guarded(now)):
                out.append(Mutation(self.cls, name, before, now))
        for name, now in d.items():
            if name not in old and _guarded(now):
                out.append(Mutation(self.cls, name, _MISSING, now))
        return out


class EngineClassGuard:
    def __init__(self, packages=("engine",)):
        self.packages = tuple(packages)
        self._prefixes = tuple(p + "." for p in self.packages)
        self._modules = {}   # name -> (module object, [(attr, class)])
        self._snaps = {}     # id(class) -> _Snap (keeps the class alive)

    # ── tracking ────────────────────────────────────────────────────────
    def _ours(self, name):
        return name in self.packages or name.startswith(self._prefixes)

    def _track(self, cls):
        if id(cls) not in self._snaps:
            self._snaps[id(cls)] = _Snap(cls)

    def _scan(self, name, module):
        found = []
        for attr, value in list(vars(module).items()):
            if isinstance(value, type) and value.__module__ == name:
                found.append((attr, value))
                self._track(value)
        self._modules[name] = (module, found)

    def _refresh(self):
        """Track modules imported (or replaced, or reloaded) since last time."""
        for name, module in list(sys.modules.items()):
            if module is None or not self._ours(name):
                continue
            seen = self._modules.get(name)
            if seen is None or seen[0] is not module:
                self._scan(name, module)
                continue
            md = vars(module)
            for attr, cls in seen[1]:
                if md.get(attr) is not cls:   # reloaded in place
                    self._scan(name, module)
                    break

    # ── per-test window ─────────────────────────────────────────────────
    def sync(self):
        """Start a test window: accept every change made since the last one."""
        self._refresh()
        for snap in self._snaps.values():
            if not snap.unchanged():
                snap.take()

    def check(self):
        """End a test window: return the mutations made inside it, after
        restoring each one so a polluter cannot cascade into later tests."""
        mutations = []
        for snap in list(self._snaps.values()):
            if snap.unchanged():
                continue
            found = snap.diff()
            for m in found:
                try:
                    if m.old is _MISSING:
                        delattr(m.cls, m.attr)
                    else:
                        setattr(m.cls, m.attr, m.old)
                except (AttributeError, TypeError):
                    pass
            mutations.extend(found)
            snap.take()   # data drift is accepted; guarded entries restored
        self._refresh()   # first sight of modules imported during the test
        return mutations
