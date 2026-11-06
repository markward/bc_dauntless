"""The target panel's subsystem family tree.

A *family* is a top-level ship subsystem the player can lock or open;
its *members* are its targetable, living descendants (each phaser
bank, each torpedo tube). The hull is never a family. A family's `state`
is its OWN condition, not an aggregate of its members (spec §4.3).

Reads state only through public getters; nothing is cached here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import engine.dev_mode as dev_mode
from engine.appc.target_menu import _has_targetable_descendant, _is_targetable
from engine.appc.subsystems import HullSubsystem, ShipSubsystem
from engine.ui import subsystem_icons


@dataclass(frozen=True)
class Member:
    name: str
    state: str
    icon_key: str
    x_px: float
    y_px: float


@dataclass(frozen=True)
class Family:
    name: str
    state: str
    icon_key: str
    lockable: bool
    x_px: float
    y_px: float
    members: tuple


def subsystem_state(sub) -> str:
    """Predicate ladder: destroyed, disabled, damaged, else healthy."""
    try:
        if hasattr(sub, "IsDestroyed") and sub.IsDestroyed():
            return "destroyed"
        if hasattr(sub, "IsDisabled") and sub.IsDisabled():
            return "disabled"
        if hasattr(sub, "IsDamaged") and sub.IsDamaged():
            return "damaged"
    except Exception as _e:
        dev_mode.log_swallowed("subsystem health state", _e)
    return "healthy"


def _own_state(sub) -> str:
    """A family's state from ITS OWN condition pool, never its children's.

    Weapon-system parents override IsDamaged/IsDisabled/IsDestroyed to
    aggregate their emitters; the family block must not (spec §4.3), so the
    base-class predicates are called directly.
    """
    try:
        if ShipSubsystem.IsDestroyed(sub):
            return "destroyed"
        if ShipSubsystem.IsDisabled(sub):
            return "disabled"
        if ShipSubsystem.IsDamaged(sub):
            return "damaged"
    except Exception as _e:
        dev_mode.log_swallowed("family health state", _e)
    return "healthy"


def _pos(sub) -> tuple:
    try:
        pos = sub.GetPosition2D()
        if isinstance(pos, tuple) and len(pos) == 2:
            return float(pos[0]), float(pos[1])
    except Exception as _e:
        dev_mode.log_swallowed("subsystem position", _e)
    return 0.0, 0.0


def _name(sub) -> str:
    return sub.GetName() if hasattr(sub, "GetName") else ""


def _alive(sub) -> bool:
    return not (hasattr(sub, "IsDestroyed") and sub.IsDestroyed())


def _targetable_descendants(sub) -> list:
    """Every targetable descendant of ``sub`` (living or not), depth-first in
    child order; non-targetable levels are walked through."""
    out = []
    n = sub.GetNumChildSubsystems() if hasattr(sub, "GetNumChildSubsystems") else 0
    for i in range(n):
        child = sub.GetChildSubsystem(i)
        if child is None:
            continue
        if _is_targetable(child):
            out.append(child)
        out.extend(_targetable_descendants(child))
    return out


def _family_for(sub) -> Optional[Family]:
    descendants = _targetable_descendants(sub)
    members = []
    if descendants:
        # A group: kept only while a targetable descendant survives.
        for d in descendants:
            if not _alive(d):
                continue
            x, y = _pos(d)
            members.append(Member(_name(d), subsystem_state(d),
                                  subsystem_icons.icon_key_for(d), x, y))
        if not members:
            return None
    elif not _is_targetable(sub) or not _alive(sub):
        return None
    x, y = _pos(sub)
    return Family(_name(sub), _own_state(sub),
                  subsystem_icons.icon_key_for(sub), bool(_is_targetable(sub)),
                  x, y, tuple(members))


def build_families(ship) -> tuple:
    import App
    out = []
    it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
    try:
        sub = ship.GetNextSubsystemMatch(it)
        while sub is not None:
            if (not isinstance(sub, HullSubsystem)
                    and (_is_targetable(sub) or _has_targetable_descendant(sub))):
                fam = _family_for(sub)
                if fam is not None:
                    out.append(fam)
            sub = ship.GetNextSubsystemMatch(it)
    finally:
        ship.EndGetSubsystemMatch(it)
    return tuple(out)
