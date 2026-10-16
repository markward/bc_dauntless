"""One rule for "which articulated part is this AUTHORED point on".

Hardpoint mounts (where a weapon is drawn and fires from), the subsystems a
severed part takes with it, and emitter + running lights all ask the same
question, so they all go through `part_severance.part_for_mount`. It asks the
model's own geometry (`host_io.model_nearest_part`: the part whose rest-pose
triangles are nearest) because box containment cannot answer it on the LC
Intrepid: the hull's box spans the nacelles, and a nacelle's box covers the
hull-mounted ventral aft phasers. Weapon-HIT attribution keeps the box rule.
"""
import pytest

from engine import host_io, host_loop
from engine.appc import articulated_part, articulation, part_pose, part_severance

# Measured on LCintrepid.nif (ship units, node transforms applied).
_BOXES = {
    "hull": ((-0.663, -1.71, -0.326), (0.663, 1.71, 0.326)),
    "wing left": ((-0.724, -1.556, -0.217), (-0.331, -0.585, -0.0700)),
    "wing right": ((0.331, -1.556, -0.217), (0.724, -0.585, -0.0700)),
}
PORT_WARP = (-0.63, -1.1, -0.15)                # on the port nacelle
PORT_NACELLE_LIGHT = (-0.631987, -1.41707, -0.069732)   # on its dorsal skin
VENTRAL_AFT_PORT = (-0.383, -1.23692, -0.175237)       # hull-mounted phaser
_LEAF = "intrepidfixture"
_MODEL = 77


def _truth(point):
    """Stand-in for the native nearest-triangle query on this hull: the
    nacelles are outboard of |x| 0.5, the phaser strips are on the hull."""
    return "wing left" if point[0] < -0.5 else (
        "wing right" if point[0] > 0.5 else "hull")


def _rig():
    rig = []
    for name, x, angle in (("wing left", -0.323, 40.0), ("wing right", 0.323, -40.0)):
        p = articulated_part.ArticulatedPartProperty(name)
        anchor = (x, -1.2446, -0.1434)
        p.SetAnchor(*anchor)
        p.SetStatePose("warp", *part_pose.pose_to6(
            part_pose.hinge_pose(anchor, (0.0, 1.0, 0.0), angle)))
        rig.append(p)
    return tuple(rig)


@pytest.fixture
def native(monkeypatch):
    calls = []

    def nearest(model, point):
        calls.append((model, tuple(point)))
        return _truth(point) if model == _MODEL else ""

    monkeypatch.setitem(articulated_part._BY_LEAF, _LEAF, _rig())
    monkeypatch.setitem(articulation._derived_boxes, _LEAF, _BOXES)
    monkeypatch.setitem(articulation._leaf_models, _LEAF, _MODEL)
    monkeypatch.setattr(host_io, "model_nearest_part", nearest)
    return calls


class _Sub:
    def __init__(self, name, pos):
        self.name, self._pos, self.condition = name, pos, 1.0

    def GetPosition(self):
        from engine.appc.math import TGPoint3
        p = TGPoint3()
        p.SetXYZ(*self._pos)
        return p

    def SetCondition(self, c):
        self.condition = c


class _Ship:
    def __init__(self, subs=()):
        self._articulation_leaf = _LEAF
        self._subs = list(subs)

    def _iter_subsystems(self):
        return iter(self._subs)


def _warp_pose():
    return articulation.target_pose(articulation.rig_for(_LEAF)[0], "warp")


# ── the rule itself ──────────────────────────────────────────────────────────

def test_box_rule_gets_these_points_wrong():
    """Why this exists: the weapon-hit rule leaves the warp mount and the
    phaser unattributed and gives the nacelle light to the hull."""
    articulation._derived_boxes[_LEAF] = _BOXES
    try:
        assert part_severance.part_for_point(_LEAF, PORT_WARP) is None
        assert part_severance.part_for_point(_LEAF, VENTRAL_AFT_PORT) is None
        assert part_severance.part_for_point(_LEAF, PORT_NACELLE_LIGHT) == "hull"
    finally:
        articulation._derived_boxes.pop(_LEAF, None)


def test_the_model_geometry_decides(native):
    assert part_severance.part_for_mount(_LEAF, PORT_WARP) == "wing left"
    assert part_severance.part_for_mount(_LEAF, PORT_NACELLE_LIGHT) == "wing left"
    assert part_severance.part_for_mount(_LEAF, VENTRAL_AFT_PORT) == "hull"


def test_answers_are_cached_per_leaf_and_point(native):
    for _ in range(3):
        part_severance.part_for_mount(_LEAF, PORT_WARP)
    assert len(native) == 1


def test_without_a_loaded_model_it_falls_back_to_the_box_rule(native, monkeypatch):
    monkeypatch.delitem(articulation._leaf_models, _LEAF)
    for p in (PORT_WARP, VENTRAL_AFT_PORT, PORT_NACELLE_LIGHT):
        assert part_severance.part_for_mount(_LEAF, p) == \
            part_severance.part_for_point(_LEAF, p)
    assert native == []


def test_an_empty_native_answer_falls_back_and_is_not_cached(native, monkeypatch):
    monkeypatch.setitem(articulation._leaf_models, _LEAF, 999)   # not _MODEL
    assert part_severance.part_for_mount(_LEAF, PORT_NACELLE_LIGHT) == "hull"
    assert part_severance.part_for_mount(_LEAF, PORT_NACELLE_LIGHT) == "hull"
    assert len(native) == 2


def test_realizing_an_instance_records_the_leafs_model(monkeypatch):
    monkeypatch.setitem(articulation._derived_boxes, _LEAF, _BOXES)
    monkeypatch.setattr(host_io, "instance_model", lambda iid: 55)
    articulation._leaf_models.pop(_LEAF, None)
    try:
        articulation.part_boxes_for(_LEAF, iid=object())
        assert articulation._leaf_models[_LEAF] == 55
    finally:
        articulation._leaf_models.pop(_LEAF, None)


# ── every consumer uses it ───────────────────────────────────────────────────

def test_a_nacelle_mount_follows_the_nacelle_and_a_hull_mount_stays(native):
    ship = _Ship()
    articulation.force_part_pose(ship, "wing left", _warp_pose())
    moved = articulation.part_transform_point(ship, PORT_WARP)
    assert moved == pytest.approx(part_pose.apply(_warp_pose(), PORT_WARP))
    assert articulation.part_transform_point(ship, VENTRAL_AFT_PORT) == VENTRAL_AFT_PORT


def test_a_severed_nacelle_takes_its_own_subsystems_not_the_hulls(native):
    warp = _Sub("Port Warp", PORT_WARP)
    phaser = _Sub("Ventral Aft Port", VENTRAL_AFT_PORT)
    ship = _Ship([warp, phaser])
    killed = part_severance._destroy_subsystems_on_part(ship, "wing left")
    assert killed == [warp]
    assert phaser.condition == 1.0


def test_lights_use_the_same_rule(native):
    ship = _Ship()
    articulation.force_part_pose(ship, "wing left", _warp_pose())
    assert host_loop._part_pose_at(ship, None, PORT_NACELLE_LIGHT) is not None
    assert host_loop._part_pose_at(ship, None, VENTRAL_AFT_PORT) is None


# ── Target offsets: only AUTHORED offsets use the mount rule ─────────────────
# A Manual Aim offset is a per-tick cursor pick, pulled back to rest with the
# BOX rule (`rest_point_for_live_point`). Pushing it forward with the MESH rule
# broke the round trip (the aim landed off the cursor on a folded nacelle) and
# scanned the model + grew `_mount_parts` every tick. A subsystem lock's
# offset IS an authored mount, so it keeps the shared rule.

class _Target(_Ship):
    def GetWorldLocation(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        from engine.appc.math import TGMatrix3
        return TGMatrix3()

    def GetScale(self):
        return 1.0

    def GetHull(self):
        return None


def _world(target, point):
    from engine.appc.math import TGPoint3
    from engine.appc.subsystems import target_offset_world
    w = target_offset_world(target, TGPoint3(*point))
    return (w.x, w.y, w.z)


def test_a_manual_pick_on_a_folded_nacelle_round_trips_to_the_cursor(native):
    target = _Target([_Sub("Port Warp", PORT_WARP)])
    articulation.force_part_pose(target, "wing left", _warp_pose())
    # Drawn nacelle surface, at the warp pose: the rest point is inside both
    # the hull and the nacelle boxes, the mesh says nacelle.
    pick = part_pose.apply(_warp_pose(), (-0.6, -1.0, -0.15))
    rest = part_severance.rest_point_for_live_point(target, pick)
    assert _world(target, rest) == pytest.approx(pick)


def test_manual_offsets_never_scan_the_model_or_grow_the_cache(native):
    target = _Target([_Sub("Port Warp", PORT_WARP)])
    articulation.force_part_pose(target, "wing left", _warp_pose())
    for i in range(50):
        _world(target, (-0.6 + i * 0.001, -1.0, -0.15))
    assert native == []
    assert part_severance._mount_parts == {}


def test_a_subsystem_lock_offset_follows_its_part_by_the_mount_rule(native):
    target = _Target([_Sub("Port Warp", PORT_WARP)])
    articulation.force_part_pose(target, "wing left", _warp_pose())
    assert _world(target, PORT_WARP) == pytest.approx(
        part_pose.apply(_warp_pose(), PORT_WARP))


def test_a_target_without_subsystems_is_never_an_authored_mount():
    class _Planet:
        pass
    assert part_severance.is_authored_mount(_Planet(), PORT_WARP) is False
