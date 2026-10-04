"""Spawned ship names. The OBJECT name stays BC-style and unique ("Galaxy-1"):
SDK scripts and AI find ships by it. The DISPLAY name is the named ship, with an
ordinal on repeats. Spec §4.6 / D9."""
from __future__ import annotations

from typing import Optional


def object_name(title: str, n: int) -> str:
    return "%s-%d" % (title, n)


def with_ordinals(names: list) -> list:
    seen: dict = {}
    out: list = []
    for name in names:
        if name is None:
            out.append(None)
            continue
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else "%s (%d)" % (name, seen[name]))
    return out
