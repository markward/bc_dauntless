"""Developer toggle for planet atmospheres (spec
docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md §4).

On (default): a planet whose catalogue entry resolves gets its atmosphere
shell pushed via renderer.set_instance_atmosphere. Off: every planet is
airless, regardless of the catalogue. Read at USE by
host_loop._apply_planet_atmosphere, so it applies to planets realized after
toggling. Exists for live A/B comparison only; not persisted.
"""

_enabled = True


def enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)
