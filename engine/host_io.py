"""Pythonic wrapper around the _dauntless_host extension module (non-render).

Sibling of engine.renderer, covering the *non-render* surface of
_dauntless_host: window/input polling, per-frame VFX descriptor lists, and the
hit/damage feedback bindings. Application code should import from here, not from
_dauntless_host directly.

This is the same manifest-validated pattern renderer.py uses, for the same
reason: `host_bindings.cc` compiles into *both* build/dauntless and the
_dauntless_host module, so a forgotten `cmake --build` leaves a stale .so where
an entire feature silently no-ops while every test stays green.
validate_bindings() (below) checks the live module against this manifest at
real-host boot to catch that loudly.

The manifest is hand-maintained but kept honest by
tests/unit/test_host_io_binding_manifest.py, which derives ground truth from
this file's own `_h.NAME` references — you cannot add or remove a wrapper
without updating the manifest, or the gate goes red.

Headless / not-built is a *different* condition from a stale build: the
extension may be legitimately absent (unit tests, headless import contexts). We
import it guarded and every wrapper treats `_h is None` as a no-op / safe
default WITHOUT raising. validate_bindings() is the single check point for the
stale-build case; it is never invoked at import time.
"""
import logging
from typing import List, Optional, Tuple

from engine import input_map

try:
    import _dauntless_host as _h
except ImportError:
    _h = None  # bindings module not built; headless — wrappers no-op.

_logger = logging.getLogger(__name__)


# ── Native-binding manifest ──────────────────────────────────────────────────
# REQUIRED: called hard (`_h.NAME(...)`). A missing one is a broken/stale build —
#   the façade crashes the moment that code path runs.
_REQUIRED_BINDINGS = frozenset({
    "key_state", "key_pressed", "mouse_button_pressed", "mouse_button_released",
    "consume_mouse_delta", "set_cursor_locked", "framebuffer_size", "window_size",
    "set_torpedoes", "set_shockwaves", "set_hit_vfx", "set_particle_emitters",
    "set_phaser_beams", "set_tractor_beams",
    "shield_hit", "world_to_body", "damage_decal_add", "hull_carve_add",
    "ray_trace_mesh",
})

# OPTIONAL: soft-guarded (`getattr(_h, "NAME", None)` / `hasattr(_h, "NAME")`).
# Empty for now — no non-render binding degrades to a warned no-op yet.
_OPTIONAL_BINDINGS = frozenset()


def validate_bindings(*, strict: bool = False) -> List[str]:
    """Check the live `_h` module against the binding manifest at real-host boot.

    Returns the sorted list of every missing binding name (empty == clean) so it
    is assertable without scraping log output. Catches a stale/incomplete .so
    loudly at startup rather than as a silently-dead feature mid-mission.

    Required-missing → logged at ERROR (always); raises RuntimeError if `strict`.
    Optional-missing → logged at WARNING (only under --developer); never raises.

    The `keys` submodule is treated as a required entry: input verification
    depends on it, and an editing slip in host_bindings.cc dropping it must be
    caught rather than silently break key binding validation.

    When `_h is None` (headless / not built) there is nothing to validate, so
    this returns []. That is a legitimately different condition from a stale
    build and must never raise here.

    Invoked only from the real-host boot path; never at import time.
    """
    if _h is None:
        return []

    missing_required = sorted(n for n in _REQUIRED_BINDINGS if not hasattr(_h, n))
    if not hasattr(_h, "keys"):
        missing_required = sorted(missing_required + ["keys"])
    missing_optional = sorted(n for n in _OPTIONAL_BINDINGS if not hasattr(_h, n))

    if missing_required:
        _logger.error(
            "_dauntless_host is missing required binding(s) — stale/incomplete "
            "native module; rebuild with `cmake --build build -j`: %s",
            ", ".join(missing_required),
        )
    if missing_optional:
        # Lazy import avoids any import-order coupling; dev_mode imports
        # _dauntless_host, not host_io, so there is no cycle either way.
        from engine import dev_mode
        if dev_mode.is_enabled():
            _logger.warning(
                "_dauntless_host is missing optional binding(s) — the matching "
                "features will silently no-op: %s",
                ", ".join(missing_optional),
            )

    if missing_required and strict:
        raise RuntimeError(
            "missing required _dauntless_host bindings (rebuild the native "
            "module with `cmake --build build -j`): " + ", ".join(missing_required)
        )
    return sorted(set(missing_required) | set(missing_optional))


def verify_keys() -> None:
    """Validate the host `keys` submodule against engine.input_map's table.

    GLFW codes are stable, but this guards against the host submodule ever
    diverging (e.g. an editing slip in host_bindings.cc). Non-fatal: mismatches
    are logged, never raised. No-op when headless or when the submodule is
    absent (validate_bindings reports the latter as a missing required entry).
    """
    if _h is None or not hasattr(_h, "keys"):
        return
    mismatches = input_map.verify_against_host(_h.keys)
    if mismatches:
        _logger.warning(
            "engine.input_map disagrees with _dauntless_host.keys on %d key(s): %s",
            len(mismatches), mismatches,
        )


# ── Window / input polling ───────────────────────────────────────────────────

def key_state(key: int) -> bool:
    if _h is None:
        return False
    return _h.key_state(key)


def key_pressed(key: int) -> bool:
    if _h is None:
        return False
    return _h.key_pressed(key)


def mouse_button_pressed(button: int) -> bool:
    if _h is None:
        return False
    return _h.mouse_button_pressed(button)


def mouse_button_released(button: int) -> bool:
    if _h is None:
        return False
    return _h.mouse_button_released(button)


def consume_mouse_delta() -> Tuple[float, float]:
    if _h is None:
        return (0.0, 0.0)
    return _h.consume_mouse_delta()


def set_cursor_locked(locked: bool) -> None:
    if _h is None:
        return
    _h.set_cursor_locked(locked)


def framebuffer_size() -> Tuple[int, int]:
    if _h is None:
        return (0, 0)
    return _h.framebuffer_size()


def window_size() -> Tuple[int, int]:
    if _h is None:
        return (0, 0)
    return _h.window_size()


# ── Per-frame VFX descriptor lists ───────────────────────────────────────────

def set_torpedoes(torpedoes: list) -> None:
    if _h is None:
        return
    _h.set_torpedoes(torpedoes)


def set_shockwaves(shockwaves: list) -> None:
    if _h is None:
        return
    _h.set_shockwaves(shockwaves)


def set_hit_vfx(vfx: list) -> None:
    if _h is None:
        return
    _h.set_hit_vfx(vfx)


def set_particle_emitters(emitters: list) -> None:
    if _h is None:
        return
    _h.set_particle_emitters(emitters)


def set_phaser_beams(beams: list) -> None:
    if _h is None:
        return
    _h.set_phaser_beams(beams)


def set_tractor_beams(beams: list) -> None:
    if _h is None:
        return
    _h.set_tractor_beams(beams)


# ── Hit / damage feedback ────────────────────────────────────────────────────

def shield_hit(
    instance_id: int,
    point: Tuple[float, float, float],
    rgba: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    intensity: float = 1.0,
) -> None:
    if _h is None:
        return
    _h.shield_hit(instance_id, point, rgba, intensity)


def world_to_body(
    instance_id: int,
    world_point: Tuple[float, float, float],
    world_normal: Tuple[float, float, float],
) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    if _h is None:
        return None
    return _h.world_to_body(instance_id, world_point, world_normal)


def damage_decal_add(
    instance_id: int,
    world_point: Tuple[float, float, float],
    world_normal: Tuple[float, float, float],
    radius: float,
    intensity: float,
    weapon_class: int,
    time: float,
) -> None:
    if _h is None:
        return
    _h.damage_decal_add(instance_id, world_point, world_normal, radius,
                        intensity, weapon_class, time)


def hull_carve_add(
    instance_id: int,
    world_point: Tuple[float, float, float],
    world_normal: Tuple[float, float, float],
    influ_radius: float,
    strength: float,
    time: float,
    floor_radius: float = 0.0,
    radius_modifier: float = 1.0,
) -> None:
    if _h is None:
        return
    _h.hull_carve_add(instance_id, world_point, world_normal, influ_radius,
                     strength, time, floor_radius, radius_modifier)


def ray_trace_mesh(
    instance_id: int,
    origin: Tuple[float, float, float],
    direction: Tuple[float, float, float],
    max_dist: float,
) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float], float]]:
    if _h is None:
        return None
    return _h.ray_trace_mesh(instance_id, origin, direction, max_dist)
