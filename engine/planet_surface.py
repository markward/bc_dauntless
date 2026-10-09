"""Developer toggle for planet surface detail (spec
docs/superpowers/specs/2026-10-08-planet-surface-detail-design.md §7).

On (default): a planet whose catalogue entry resolves a `surface` block gets
its detail params pushed via renderer.set_instance_surface. Off: every planet
renders with no surface detail, regardless of the catalogue. Read at USE by
host_loop._apply_planet_surface, so it applies to planets realized after
toggling. Exists for live A/B comparison only; not persisted.
"""

_enabled = True


def enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)
