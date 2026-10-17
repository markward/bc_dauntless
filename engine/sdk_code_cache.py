"""Compiled-code cache for the SDK loader.

Both SDK loader twins (tools/mission_harness.py, the production loader, and
tests/conftest.py) parse each script and run the Python 1.5 compat transforms
before compiling. That is pure in the file's bytes and in which sibling files
exist (the implicit-relative-import rewrite looks them up), so the code
object is reused while neither has changed. Every load still EXECUTES the
code into its own module dict: only the parse/transform/compile is shared.

The validity stamp is (mtime_ns, size) of the file plus the mtime_ns of each
sibling directory; a directory's mtime moves when an entry is added, removed
or renamed, which covers a sibling appearing. One entry per (path, module
name) -- a changed file replaces its entry rather than accumulating.
"""
from __future__ import annotations

import os
from typing import Callable, Iterable

_cache: dict = {}


def _stamp(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def compiled(path, fullname: str, fixer_key, sibling_dirs: Iterable,
             build: Callable[[], object]):
    """The code object for `path`, from `build()` on a miss.

    `fixer_key` is whatever else the transforms were parameterised by (the
    implicit-relative fixer's package and self name).
    """
    validity = (_stamp(path), fixer_key,
                tuple((str(d), _stamp(d)) for d in sibling_dirs))
    key = (str(path), fullname)
    hit = _cache.get(key)
    if hit is not None and hit[0] == validity:
        return hit[1]
    code = build()
    _cache[key] = (validity, code)
    return code


def clear() -> None:
    _cache.clear()
