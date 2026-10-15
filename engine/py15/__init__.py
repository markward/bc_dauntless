"""Load mod scripts shipped only as Python 1.5 bytecode (``.pyc``).

BC's ``stbc.exe`` embeds Python 1.5 and imports ``.pyc`` directly, so some
mods ship no source (the LC Intrepid Pack's two torpedo projectiles). The
SDK loader in both tools/mission_harness.py and tests/conftest.py calls
``load_tree`` for a mod ``.pyc`` and then treats the tree exactly like one
parsed from source.

Nothing derived from a mod is ever written anywhere: the tree goes straight
to ``compile()``. Spec:
docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md
"""
from __future__ import annotations

import ast

from .lift import Py15Unsupported, lift
from .marshal15 import is_py15_pyc

__all__ = ["Py15Unsupported", "is_py15_pyc", "lift", "lift_file", "load_tree"]

# Paths already reported, so each unloadable file is named exactly once.
_reported: set = set()


def lift_file(path) -> ast.Module:
    """lift() on a file, with the path attached to any refusal."""
    with open(path, "rb") as f:
        data = f.read()
    try:
        return lift(data)
    except Py15Unsupported as exc:
        exc.path = str(path)
        raise


def load_tree(path, fullname: str) -> ast.Module:
    """The module AST the SDK loader compiles for a mod ``.pyc``.

    On refusal, prints ONE production log line per file (not only under
    --developer: a player whose mod weapon turned into a photon deserves to
    be told why) and re-raises, so the import fails like any other and
    callers with a fallback (the projectile and torpedo-ammo resolvers)
    use it."""
    try:
        return lift_file(path)
    except Py15Unsupported as exc:
        key = str(path)
        if key not in _reported:
            _reported.add(key)
            print("[sdk-loader] mod module %s (%s) is Python 1.5 bytecode this "
                  "engine cannot load yet: %s; importers fall back where they "
                  "can" % (fullname, key, exc), flush=True)
        raise
