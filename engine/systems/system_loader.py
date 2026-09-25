"""Entering a star system loads every one of its regions (spec §3).

Level-triggered: each tick the host asks ensure_loaded(player). When the
player's set is a mapped region of a system not yet loaded, each region of
that system whose set does not exist is created through BC's own region
module -- Systems.<System>.<Region>.Initialize() -- so Plan 1's wrap applies
the map before anything realizes it. Sets that already exist (a mission made
them, or we did earlier) are adopted, never re-created. Nothing is unloaded
until the mission changes: that is BC's own bound (the mission-swap
_sets.clear()), and leaving a system is not a lifetime event.

One broken region module must not strand the player or stop its siblings
loading: its failure is printed loudly and the loop continues.
"""
from __future__ import annotations

import importlib

_loaded: str | None = None


def reset() -> None:
    global _loaded
    _loaded = None


def loaded_system() -> str | None:
    return _loaded


def ensure_loaded(player) -> list:
    global _loaded
    from engine.systems import frames, resolve
    f = frames.frame_of(frames.containing_set(player))
    if f is None or f.key[0] != "system":
        return []
    system = f.key[1]
    if system == _loaded:
        return []
    import App
    created = []
    for region in resolve.regions_of(system):
        if App.g_kSetManager.GetSet(region) is not None:
            continue
        qual = f"Systems.{system}.{region}"
        try:
            importlib.import_module(qual).Initialize()
        except Exception as exc:  # noqa: BLE001 -- one region never strands the rest
            print(f"[systems] could not load region {region!r} ({qual}): "
                  f"{type(exc).__name__}: {exc}", flush=True)
            continue
        if App.g_kSetManager.GetSet(region) is not None:
            created.append(region)
    _loaded = system
    return created
