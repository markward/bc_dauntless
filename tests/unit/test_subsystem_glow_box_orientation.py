"""Box glow regions read + resolve an optional (forward, up) orientation."""
from engine.appc import subsystem_glow as sg


class _Prop:
    def __init__(self, data): self._data = data


def _box_prop(orientation=None):
    # Data-bag as read_indexed_setter_args expects: Set<F>(*args) -> key
    # (F, args[:-1]) = value args[-1].
    data = {
        ("GlowRegionShape", (0,)): "Box",
        ("GlowRegionPosition", (0, 0.0, 0.0)): 0.0,
        ("GlowRegionScale", (0, 0.2, 0.2)): 0.05,
    }
    if orientation is not None:
        (fx, fy, fz), (ux, uy, uz) = orientation
        data[("GlowRegionOrientation", (0, fx, fy, fz, ux, uy))] = uz
    return _Prop(data)


def test_box_without_orientation_reads_none():
    regions = sg.baked_glow_regions(_box_prop())
    assert regions[0]["shape"] == "Box"
    assert regions[0].get("orientation") is None


def test_box_with_orientation_reads_basis():
    ori = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))   # forward=+X, up=+Z
    regions = sg.baked_glow_regions(_box_prop(ori))
    assert regions[0]["orientation"] == ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))


def test_resolve_box_op_carries_identity_by_default():
    op = sg.resolve_baked_region(
        {"shape": "Box", "position": (0.0, 0.0, 0.0), "scale": (0.2, 0.2, 0.05)},
        (0.0, 0.0, 0.0))
    # ("box", center, half_extents, forward, up)
    assert op[0] == "box"
    assert op[3] == (0.0, 1.0, 0.0) and op[4] == (0.0, 0.0, 1.0)


def test_resolve_box_op_carries_orientation():
    op = sg.resolve_baked_region(
        {"shape": "Box", "position": (0.0, 0.0, 0.0), "scale": (0.2, 0.2, 0.05),
         "orientation": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))},
        (0.0, 0.0, 0.0))
    assert op[3] == (1.0, 0.0, 0.0) and op[4] == (0.0, 0.0, 1.0)


def test_box_with_malformed_orientation_falls_back_to_none():
    # A hand-authored SetGlowRegionOrientation with wrong arity (5 args) must
    # not raise out of baked_glow_regions — it degrades to no orientation.
    prop = _Prop({
        ("GlowRegionShape", (0,)): "Box",
        ("GlowRegionScale", (0, 0.2, 0.2)): 0.05,
        ("GlowRegionOrientation", (0, 1.0, 0.0, 0.0)): 0.0,   # 5 trailing args
    })
    regions = sg.baked_glow_regions(prop)   # must not raise
    assert regions[0].get("orientation") is None
