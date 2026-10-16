"""Dotted module names Dauntless claims outright (spec 2026-10-16 §8.1).

Both _SDKFinders (tools/mission_harness.py, tests/conftest.py) call
claimed_spec() after the project-root shims and BEFORE the mod overlay, so a
mod's own copy of a claimed package never loads. Only the claimed prefix is
taken: `Custom` itself and every other `Custom.*` still resolve from mods and
the SDK -- a root-level Custom/__init__.py would have shadowed them all.

A claimed name we do not provide (NanoFX's effect modules, its warp AI, ...)
still imports: it becomes an "unsupported" package whose every name is a callable
object that logs once when called and returns None. Never a truthy stub (the
objects are falsy, spec §8.5).
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# folded dotted prefix -> directory serving it
_CLAIMS = {"custom.nanofxv2": _HERE / "fx_api"}

_noted: list = []


def _note_unsupported(qualname: str) -> None:
    if qualname in _noted:
        return
    _noted.append(qualname)
    print("[legacy-fx] NanoFX effect API not supported: %s" % qualname, file=sys.stderr)


def unsupported_calls() -> list:
    return sorted(_noted)


def reset() -> None:
    _noted.clear()


class _UnsupportedName:
    """Callable AND attribute-chainable: `from pkg import X` binds this when X
    is not a provided submodule, and X.f() must still be a logged no-op."""

    def __init__(self, qualname):
        self._qualname = qualname

    def __call__(self, *_args, **_kwargs):
        _note_unsupported(self._qualname)
        return None

    def __bool__(self):
        return False   # never a truthy stub (spec §8.5)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _UnsupportedName("%s.%s" % (self._qualname, name))


class _UnsupportedModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _UnsupportedName("%s.%s" % (self.__name__, name))


class _UnsupportedLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return _UnsupportedModule(spec.name)

    def exec_module(self, module):
        module.__path__ = []   # a package, so deeper imports reach us too


def claimed_spec(fullname: str):
    folded = fullname.lower()
    for prefix, base in _CLAIMS.items():
        if folded != prefix and not folded.startswith(prefix + "."):
            continue
        rest = fullname.split(".")[len(prefix.split(".")):]
        target = base.joinpath(*rest)
        init = target / "__init__.py"
        if init.is_file():
            return importlib.util.spec_from_file_location(
                fullname, init, submodule_search_locations=[str(target)])
        module_file = target.with_suffix(".py")
        if rest and module_file.is_file():
            return importlib.util.spec_from_file_location(fullname, module_file)
        return importlib.machinery.ModuleSpec(fullname, _UnsupportedLoader(),
                                              is_package=True)
    return None
