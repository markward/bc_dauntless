"""Developer toggle for the planet geosphere (spec
docs/superpowers/specs/2026-10-06-planet-geosphere-design.md §4.5).

On (default): planet/moon NIFs load as the geosphere variant -- icosphere LODs
picked per camera, sphere-mapped normal + UV. Off: BC's own 673-vertex mesh.
Read at USE by host_loop._load_planet_model, so it applies to planets realized
after toggling. Exists for live A/B comparison only; not persisted.
"""

_enabled = True


def enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)
