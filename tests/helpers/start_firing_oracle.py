"""Differential oracle: WeaponSystem.StartFiring's Python body as it stood
at 52e5211b2 (`_start_firing_py` in engine/appc/weapon_subsystems.py), before
the engine kept no Python copy of ported methods.

A VERBATIM copy, adapted only so its module-level names are read off
``engine.appc.weapon_subsystems`` at call time (``ws.<name>``): the tests
patch gates there and the native body calls them back at the same place. Do
not "fix" anything here: it is the reference the native body must equal.
"""
from engine.appc import native_combat
from engine.appc import weapon_subsystems as ws


def start_firing_py(self, target=None, offset=None) -> None:
    if not self.IsOn():
        return
    # Disabled-weapons gate: when every child reports disabled (Project 2
    # aggregation), the parent IsDisabled is 1 — block fire. Spec §4.2.
    if ws._is_offline(self):
        return
    # Cloak gate: a cloaked / cloaking ship cannot fire (BC rule).
    if ws._cloak_blocks_fire(self):
        return
    # Warp-in gate: an arriving ship holds fire until it has landed.
    if ws._dewarp_blocks_fire(self):
        return
    # Detectability gate: never fire (nor play warm-up SFX) at a target the
    # ship can't detect — cloaked, nebula-hidden, or out of sensor range.
    if ws._target_undetectable(self, target):
        return
    # Engageability gate (per-class hook, e.g. PhaserSystem's global fire
    # range): an out-of-range trigger must NOT latch _fire_held.
    if (target is not None and hasattr(self, "_can_engage")
            and not self._can_engage(self.GetParentShip(), target)):
        return
    self._add_target(target)
    self._held_target = target
    self._held_offset = offset
    self._fire_held = True
    self.SetForceUpdate(1)
    # One immediate update (dt 0), walked by the native K1 kernel.
    native_combat.k1_system(self, 0.0)
