"""Developer-only forced glow-state preview flags.

Single source of truth for the Developer Options -> Lighting toggles that
force every subsystem's glow state to a fixed value, so damage lighting
(dim/flicker/blow-out) can be previewed without actually damaging anything.
Mirrors ``engine/dev_combat_cheats.py``'s seam shape: this module imports
only ``dev_mode`` (plus ``subsystem_glow`` for its state constants);
``subsystem_glow.glow_state`` lazily imports this module. Neither side is a
hard dependency of the other beyond that.

Only one forced state is active at a time: "damaged" maps to
``subsystem_glow.DISABLED`` (dim + flicker) and "disabled" maps to
``subsystem_glow.DESTROYED`` (blown out). Setting one clears the other.

``forced_glow_state()`` ANDs the stored flag with ``dev_mode.is_enabled()``,
same defense-in-depth as the combat cheats: even if a flag were somehow left
set, production (dev mode off) is byte-identical to today's real
classification. This is purely visual -- it never touches ``IsDisabled()``/
``IsDestroyed()`` or any other real subsystem state.

Spec: docs/superpowers/specs/2026-08-05-dev-forced-glow-state-toggles-design.md
"""
from engine import dev_mode
from engine.appc import subsystem_glow

_forced_state = None  # None | subsystem_glow.DISABLED | subsystem_glow.DESTROYED


def set_systems_damaged(on: bool) -> None:
    global _forced_state
    _forced_state = subsystem_glow.DISABLED if on else None


def set_systems_disabled(on: bool) -> None:
    global _forced_state
    _forced_state = subsystem_glow.DESTROYED if on else None


def forced_glow_state():
    """The forced glow state, or None when dev mode is off or nothing is forced."""
    return _forced_state if dev_mode.is_enabled() else None


def systems_damaged_active() -> bool:
    return forced_glow_state() == subsystem_glow.DISABLED


def systems_disabled_active() -> bool:
    return forced_glow_state() == subsystem_glow.DESTROYED


def reset() -> None:
    """Clear the forced state. Used by tests; not wired to runtime teardown."""
    global _forced_state
    _forced_state = None
