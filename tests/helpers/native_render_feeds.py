"""What the native render feeds draw, read back as named fields.

The beam and torpedo render feeds have no Python copy (phase 6 follow-up 4):
`native_combat.beam_feed` / `torpedo_feed` write straight into the host's
render vectors. These helpers run a feed and read those vectors back
(`phaser_beams_debug`, `tractor_beams_debug`, `torpedoes_debug`,
`dynamic_lights_debug`), one dict per item, keyed like the descriptor dicts
`set_phaser_beams` / `set_torpedoes` / `set_dynamic_lights` take. Every
float has been through float32, so compare with pytest.approx.
"""
from engine import host_io
from engine.appc import native_combat as nc

BEAM_FIELDS = (
    ("emitter", 3), ("target", 3), ("color", 4), ("width", 1),
    ("u_tiles", 1), ("num_sides", 1), ("taper_radius", 1),
    ("taper_ratio", 1), ("taper_min_length", 1), ("taper_max_length", 1),
    ("perimeter_tile", 1), ("texture_speed", 1), ("end_width_scale", 1))
TORPEDO_FIELDS = (
    "position", "core_texture", "core_color", "core_size_a", "core_size_b",
    "glow_texture", "glow_color", "glow_size_a", "glow_size_b", "glow_size_c",
    "flares_texture", "flares_color", "num_flares", "flares_size_a",
    "flares_size_b", "age", "id", "is_disruptor", "forward", "shell_color",
    "bolt_core_color", "bolt_length", "bolt_width")
LIGHT_FIELDS = (
    "position", "position_b", "color", "radius", "intensity", "direction",
    "spot_tan_x", "up", "spot_tan_y", "instance_index",
    "instance_generation")


def _host():
    h = host_io._h
    assert h is not None, "premise: the native host module"
    return h


def _beam(row):
    out, i = {}, 0
    for name, n in BEAM_FIELDS:
        out[name] = tuple(row[i:i + n]) if n > 1 else row[i]
        i += n
    return out


def beams(ships, ship_instances=None):
    """Run the beam feed over `ships`: (phaser dicts, tractor dicts)."""
    assert nc.beam_feed(list(ships), ship_instances) is True
    h = _host()
    return ([_beam(r) for r in h.phaser_beams_debug()],
            [_beam(r) for r in h.tractor_beams_debug()])


def torpedoes(ship_instances=None, ship_emitters=None, player=None):
    """Run the torpedo feed: (torpedo dicts, dynamic-light dicts). The
    lights are the whole blended list (explosion and emitter lights too)."""
    assert nc.torpedo_feed(ship_instances if ship_instances is not None
                           else {}, ship_emitters or {}, player) is True
    h = _host()
    return ([dict(zip(TORPEDO_FIELDS, r)) for r in h.torpedoes_debug()],
            [dict(zip(LIGHT_FIELDS, r)) for r in h.dynamic_lights_debug()])


def clear():
    """Empty the four render vectors (so nothing outlives the test)."""
    h = host_io._h
    if h is None:
        return
    h.set_phaser_beams([])
    h.set_tractor_beams([])
    h.set_torpedoes([])
    h.set_dynamic_lights([])
