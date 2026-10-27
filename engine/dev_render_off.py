"""Switch render features off at boot, for perf A/B runs. Developer mode only.

    DAUNTLESS_DEV_RENDER_OFF=rock_puffs,volumetric_nebulae

Each name turns one feature off, as its Developer Options or Configuration
toggle would, so an unattended capture (perf-register.md B1) can be repeated
with one feature missing and compared against the same run with everything on
(perf-register.md P-1). An unknown name is refused rather than ignored: a typo
would otherwise measure the unchanged scene and read as "this feature is free".

host_loop applies the list twice: before the boot mission loads, because
the planet flags are read when a planet is realised, and again after the
saved settings, which would otherwise switch MSAA, dust, the nebulae and the
lens flares back on. Every step is idempotent. Not persisted.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Mapping

ENV = "DAUNTLESS_DEV_RENDER_OFF"


def _planet(module_name: str) -> Callable:
    def _off(_r) -> None:
        import importlib
        importlib.import_module("engine." + module_name).set_enabled(False)
    return _off


def _shuttle_service_off() -> None:
    from engine.systems import shuttle_service
    shuttle_service.set_enabled(False)


# name -> how to turn it off, given engine.renderer (or a stand-in).
_FEATURES: Dict[str, Callable] = {
    # Improved Space's two halves. The nebula flag also gates the system
    # nebula pass's profile push (host_loop._system_nebula_gate).
    "volumetric_nebulae": lambda r: r.set_volumetric_nebulae_enabled(False),
    "procedural_sky": lambda r: r.set_procedural_sky_enabled(False),
    # Rock fields: the master (near band, specks, puffs, far tier) and parts.
    "rock_fields": lambda r: r.far_set_enabled(False),
    "rock_puffs": lambda r: r.rock_puffs_set_enabled(False),
    "rock_specks": lambda r: r.rock_specks_set_enabled(False),
    "minor_rocks": lambda r: r.minors_set_enabled(False),
    # Planets: read at realisation (host_loop._apply_planet_*).
    "planet_geosphere": _planet("planet_geosphere"),
    "planet_atmosphere": _planet("planet_atmosphere"),
    "planet_surface": _planet("planet_surface"),
    # Off restores the classic per-sun billboard flares, as the setting does.
    "modern_lens_flare": lambda r: r.set_hdr_lens_flare_enabled(False),
    "shadows": lambda r: r.set_shadows_enabled(False),
    "dust": lambda r: r.set_dust_enabled(False),
    "dof": lambda r: r.set_dof_enabled(False),
    "running_lights": lambda r: r.running_lights_set_enabled(False),
    # The space pass's multisampled phase 1; SMAA is left as the setting has it.
    "msaa": lambda r: r.set_msaa_samples(0),
    # Python state, not a pass: the Tau Ceti shuttle service, for its
    # with/without cost capture (docs/reference/engine/home-stations.md).
    "shuttle_service": lambda _r: _shuttle_service_off(),
}


def known() -> List[str]:
    return list(_FEATURES)


def from_env(environ: Mapping[str, str], developer: bool) -> List[str]:
    """The names to switch off, in order. [] outside developer mode. Raises
    ValueError on an unknown name."""
    if not developer:
        return []
    names = [n.strip() for n in environ.get(ENV, "").split(",") if n.strip()]
    unknown = [n for n in names if n not in _FEATURES]
    if unknown:
        raise ValueError("%s: unknown feature(s) %s; known: %s"
                         % (ENV, ", ".join(unknown), ", ".join(known())))
    return names


def apply(names: List[str], r) -> None:
    """Turn each named feature off through `r` (engine.renderer)."""
    for name in names:
        _FEATURES[name](r)
