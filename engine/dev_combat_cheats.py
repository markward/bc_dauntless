"""Developer-only combat cheat flags.

Single source of truth for the Developer Options → Combat toggles.
Each flag defaults Off. ``combat.apply_hit`` reads the ``*_active()``
getters; ``DeveloperOptionsPanel`` writes them via the setters. Neither
side imports the other — this module is the seam.

Every ``*_active()`` getter ANDs the stored flag with
``dev_mode.is_enabled()``. Gating inside the getter is defense-in-depth:
even if a flag were somehow set in a production build, combat behaviour
cannot change.

Spec: docs/superpowers/specs/2026-06-08-developer-options-menu-design.md
"""
from engine import dev_mode

_god_mode: bool = False
_double_player_weapons: bool = False
_disable_npc_shields: bool = False
_disable_collisions: bool = False


def set_god_mode(on: bool) -> None:
    global _god_mode
    _god_mode = bool(on)


def set_double_player_weapons(on: bool) -> None:
    global _double_player_weapons
    _double_player_weapons = bool(on)


def set_disable_npc_shields(on: bool) -> None:
    global _disable_npc_shields
    _disable_npc_shields = bool(on)


def set_disable_collisions(on: bool) -> None:
    global _disable_collisions
    _disable_collisions = bool(on)


def god_mode_active() -> bool:
    return _god_mode and dev_mode.is_enabled()


def double_player_weapons_active() -> bool:
    return _double_player_weapons and dev_mode.is_enabled()


def disable_npc_shields_active() -> bool:
    return _disable_npc_shields and dev_mode.is_enabled()


def disable_collisions_active() -> bool:
    return _disable_collisions and dev_mode.is_enabled()


def reset() -> None:
    """Clear all flags. Used by tests; not wired to runtime teardown."""
    global _god_mode, _double_player_weapons, _disable_npc_shields
    global _disable_collisions
    _god_mode = False
    _double_player_weapons = False
    _disable_npc_shields = False
    _disable_collisions = False
