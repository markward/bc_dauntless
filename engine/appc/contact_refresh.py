"""When the player's contact list must be re-derived.

`host_loop._pump_contacts` used to run `perception.perceived_by(player)` +
`set_contacts` + `ResetAffiliationColors` every frame. It now re-derives
membership and verdicts only when this flag is set (or when its own
(menu, player, set) key changes), and otherwise refreshes the records'
distances from positions. The current target's identified /
subsystems_targetable are re-checked every frame by the pump itself.

Who marks it (each a direct hook, never an event-manager listener: the
mission swap clears g_kEventManager's handlers):

- the player's sensor sweep (`sensor_contacts._sweep`, BC's 1.0 s game-time
  `sweep_period_s`): the floor for everything that has no event -- range and
  cloak-bubble crossings, sensor damage, media, IsTargetable, regrouping;
- a ship's death (`ship_lifecycle` "destroyed", subscribed below), and an
  IsDying() flip (`DamageableObject.SetDying` / `SetLifeTime`);
- a set's contact view changing (`set_index._push`);
- a cloak transition (`CloakingSubsystem._fire`, which the native completion
  `native_subsystems._cloak_done` also reaches);
- an identification commit (`sensor_identification._identify_one`) or a lost
  track (`sensor_contacts._lose_track`, `on_exited_set`);
- `Game.SetPlayer`, `STTargetMenu.ClearTargetList`, and run()'s target
  identity compare.

A mark only sets a flag, so it is safe inside a set door or an event handler.
Spec: docs/superpowers/specs/2026-11-08-perf-tier1-design.md §2.1;
cadence: docs/reference/engine/perf-cadences-and-latency.md.
"""
from __future__ import annotations

from engine.appc import ship_lifecycle

# Dirty at import, so the first pump of a session is a full rebuild.
_dirty = True
# Marks per reason since the last reset: a debug counter only.
counts: dict = {}


def mark_dirty(reason: str) -> None:
    """The contact list must be re-derived on the next pump."""
    global _dirty
    _dirty = True
    counts[reason] = counts.get(reason, 0) + 1


def consume() -> bool:
    """Return whether the list was marked, and clear the mark."""
    global _dirty
    was = _dirty
    _dirty = False
    return was


def reset() -> None:
    """Mission swap / per-test reset: the next pump is a full rebuild."""
    global _dirty
    _dirty = True
    counts.clear()


def _on_lifecycle(event: str, ship) -> None:
    if event == "destroyed":
        mark_dirty("destroyed")


# Once, at import, like engine.systems.home_stations: ship_lifecycle.reset()
# keeps subscribers.
ship_lifecycle.subscribe(_on_lifecycle)
