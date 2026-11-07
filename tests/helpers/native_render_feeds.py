"""What the native render feeds draw, read back: named fields and packed bytes.

The beam and torpedo render feeds have no Python copy (phase 6 follow-up 4):
`native_combat.beam_feed` / `torpedo_feed` write straight into the host's
render vectors. These helpers run a feed and read those vectors back
(`phaser_beams_debug`, `tractor_beams_debug`, `torpedoes_debug`,
`dynamic_lights_debug`).

Each feed's field order is defined ONCE, here (BEAM_FIELDS, TORPEDO_FIELDS,
LIGHT_FIELDS: the native descriptor structs' order). Both the named dicts
(keyed like the descriptor dicts `set_phaser_beams` / `set_torpedoes` /
`set_dynamic_lights` take; every float has been through float32, so compare
with pytest.approx) and the packed bytes the render goldens digest are built
from them. Packing, so a compare is bitwise and -0.0 / NaN cannot hide in a
float ==: a float is float32 bits ("<f"), an int "<i", a bool one byte
("<B"), a string a "<i" utf-8 byte length and then the bytes.
"""
import struct

from engine import host_io
from engine.appc import native_combat as nc

# (name, kind, default when a descriptor dict omits it; None: required).
# kind: "f" float32, "fN" N float32s, "i" int32, "b" bool byte, "s" string.
BEAM_FIELDS = (
    ("emitter", "f3", None), ("target", "f3", None), ("color", "f4", None),
    ("width", "f", None), ("u_tiles", "f", 1.0), ("num_sides", "i", 6),
    ("taper_radius", "f", 0.01), ("taper_ratio", "f", 0.25),
    ("taper_min_length", "f", 5.0), ("taper_max_length", "f", 30.0),
    ("perimeter_tile", "f", 1.0), ("texture_speed", "f", 0.0),
    ("end_width_scale", "f", 1.0))
TORPEDO_FIELDS = (
    ("position", "f3", None), ("core_texture", "s", None),
    ("core_color", "f4", None), ("core_size_a", "f", None),
    ("core_size_b", "f", None), ("glow_texture", "s", None),
    ("glow_color", "f4", None), ("glow_size_a", "f", None),
    ("glow_size_b", "f", None), ("glow_size_c", "f", None),
    ("flares_texture", "s", None), ("flares_color", "f4", None),
    ("num_flares", "i", None), ("flares_size_a", "f", None),
    ("flares_size_b", "f", None), ("age", "f", None), ("id", "i", None),
    ("is_disruptor", "b", None), ("forward", "f3", None),
    ("shell_color", "f4", None), ("bolt_core_color", "f4", None),
    ("bolt_length", "f", None), ("bolt_width", "f", None))
# A light dict's defaults depend on the dict (light_values).
LIGHT_FIELDS = (
    ("position", "f3", None), ("position_b", "f3", None),
    ("color", "f3", None), ("radius", "f", None), ("intensity", "f", None),
    ("direction", "f3", None), ("spot_tan_x", "f", None),
    ("up", "f3", None), ("spot_tan_y", "f", None),
    ("instance_index", "i", None), ("instance_generation", "i", None))


def _width(kind):
    return int(kind[1:]) if kind[0] == "f" and len(kind) > 1 else 1


# phaser_beams_debug() rows are FLAT (one value per float).
BEAM_ROW_LEN = sum(_width(k) for _n, k, _d in BEAM_FIELDS)


def f32(x):
    """`x` rounded through float32, as the render vectors hold it."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _pack_one(kind, v):
    if kind == "s":
        b = v.encode("utf-8")
        return struct.pack("<i", len(b)) + b
    if kind == "i":
        return struct.pack("<i", v)
    if kind == "b":
        return struct.pack("<B", 1 if v else 0)
    if kind == "f":
        return struct.pack("<f", v)
    return b"".join(struct.pack("<f", x) for x in v)


def pack(fields, values):
    """`values` (one per field, in `fields` order) as bytes."""
    values = list(values)
    assert len(values) == len(fields), (len(values), len(fields))
    return b"".join(_pack_one(k, v) for (_n, k, _d), v in zip(fields, values))


def beam_values(row):
    """A flat phaser_beams_debug() row, one value per field."""
    assert len(row) == BEAM_ROW_LEN, len(row)
    out, i = [], 0
    for _name, kind, _d in BEAM_FIELDS:
        n = _width(kind)
        out.append(tuple(row[i:i + n]) if n > 1 else row[i])
        i += n
    return out


def as_dict(fields, values):
    return {name: v for (name, _k, _d), v in zip(fields, values)}


def beam_dict(row):
    return as_dict(BEAM_FIELDS, beam_values(row))


def beam_bytes(row):
    return pack(BEAM_FIELDS, beam_values(row))


def beam_dict_values(d):
    """A `set_phaser_beams` dict's values, the binding's defaults applied."""
    return [d[n] if dflt is None else d.get(n, dflt)
            for n, _k, dflt in BEAM_FIELDS]


def torpedo_dict_values(d):
    """A `set_torpedoes` dict's values (every key required)."""
    return [d[n] for n, _k, _d in TORPEDO_FIELDS]


def light_values(d):
    """A `set_dynamic_lights` dict's values, the binding's defaults applied:
    no position_b is a point light (the position), no direction / up the
    zero / +Y vectors, no cone -1, no instance_id (0, 0)."""
    iid = d.get("instance_id")
    dflt = {"position_b": d["position"], "direction": (0.0, 0.0, 0.0),
            "spot_tan_x": -1.0, "up": (0.0, 1.0, 0.0), "spot_tan_y": -1.0,
            "instance_index": iid.index if iid is not None else 0,
            "instance_generation": iid.generation if iid is not None else 0}
    return [d[n] if d.get(n) is not None else dflt[n]
            for n, _k, _d in LIGHT_FIELDS]


def drop_from_frames(monkeypatch, pset):
    """`pset` left out of the frames table the native feeds are sent
    (native_combat._beam_frames), so its items are skipped as "frames"."""
    gone = nc._slot_of(pset)
    assert gone is not None, "premise: the set has a row"
    table = nc._beam_frames

    def without(*a, **k):
        t = table(*a, **k)
        assert gone in t, "premise: the set is in the table"
        del t[gone]
        return t

    monkeypatch.setattr(nc, "_beam_frames", without)


def _host():
    h = host_io._h
    assert h is not None, "premise: the native host module"
    return h


def beams(ships, ship_instances=None):
    """Run the beam feed over `ships`: (phaser dicts, tractor dicts)."""
    assert nc.beam_feed(list(ships), ship_instances) is True
    h = _host()
    return ([beam_dict(r) for r in h.phaser_beams_debug()],
            [beam_dict(r) for r in h.tractor_beams_debug()])


def torpedoes(ship_instances=None, ship_emitters=None, player=None):
    """Run the torpedo feed: (torpedo dicts, dynamic-light dicts). The
    lights are the whole blended list (explosion and emitter lights too)."""
    assert nc.torpedo_feed(ship_instances if ship_instances is not None
                           else {}, ship_emitters or {}, player) is True
    h = _host()
    return ([as_dict(TORPEDO_FIELDS, r) for r in h.torpedoes_debug()],
            [as_dict(LIGHT_FIELDS, r) for r in h.dynamic_lights_debug()])


def clear():
    """Empty the four render vectors (so nothing outlives the test)."""
    h = host_io._h
    if h is None:
        return
    h.set_phaser_beams([])
    h.set_tractor_beams([])
    h.set_torpedoes([])
    h.set_dynamic_lights([])
