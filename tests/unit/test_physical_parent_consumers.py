"""Mounts, target offsets, severance and running lights honour a SET physical
parent, and change nothing for a subsystem without one (spec sections 5, 6, 8).
"""
import pytest

from engine import host_loop
from engine.appc import articulation, part_pose, part_severance, physical_parents
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import TGModelProperty
from engine.appc.running_lights import RunningLightSpec
from engine.appc.subsystems import subsystem_world_position, target_offset_world

LEAF = "birdofprey"
BOXES = {n: ((-1, -1, -1), (1, 1, 1))
         for n in ("birdofprey", "head", "left wing", "left wing01")}
IMPULSE = (-0.235, -0.219, -0.047)
CANNON = (-1.009, 0.450, -0.670)
LIGHT = (0.0, 0.5, 0.0)


class _Sub:
    def __init__(self, name, pos, parent=None):
        self._p = TGPoint3(*pos)
        self._prop = TGModelProperty(name)
        self._prop.SetPhysicalParent(parent)
        self.condition = 100.0

    def GetPosition(self):
        return self._p

    def GetProperty(self):
        return self._prop

    def SetCondition(self, v):
        self.condition = float(v)

    def _climb_to_ship(self):
        return None


class _Ship:
    def __init__(self, subs=(), poses=True):
        self._articulation_leaf = LEAF
        self._subs = list(subs)
        self._articulation_poses = {}
        if poses:
            self._articulation_poses = {
                p.GetName(): part_pose.interpolate(
                    part_pose.IDENTITY, p.pose_for("cruise"), p.anchor, 1.0)
                for p in articulation.rig_for(LEAF)}

    def _iter_subsystems(self):
        return list(self._subs)

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        return TGMatrix3()

    def GetScale(self):
        return 1.0


@pytest.fixture(autouse=True)
def rig(monkeypatch):
    physical_parents.reset()
    monkeypatch.setitem(articulation._derived_boxes, LEAF, BOXES)

    def mount(leaf, point, iid=None):
        point = tuple(round(v, 6) for v in point)
        if point == IMPULSE or point[0] < -0.9:
            return "left wing"
        return "birdofprey"

    monkeypatch.setattr(part_severance, "part_for_mount", mount)
    yield
    physical_parents.reset()


def _xyz(p):
    return (p.x, p.y, p.z)


def _pose_of(ship, name):
    return articulation.pose_for_part(
        ship, next(p for p in articulation.rig_for(LEAF) if p.GetName() == name))


def test_unset_mount_unchanged():
    ship = _Ship()
    sub = _Sub("Impulse Engines", IMPULSE)
    expected = part_pose.apply(_pose_of(ship, "left wing"), IMPULSE)
    assert expected != pytest.approx(IMPULSE)
    assert _xyz(subsystem_world_position(sub, ship)) == pytest.approx(expected)


def test_set_mount_ignores_wing_pose():
    sub = _Sub("Impulse Engines", IMPULSE, "birdofprey")
    assert _xyz(subsystem_world_position(sub, _Ship())) == pytest.approx(IMPULSE)


def test_set_mount_follows_named_wing():
    ship = _Ship()
    sub = _Sub("Warp Core", LIGHT, "left wing")
    expected = part_pose.apply(_pose_of(ship, "left wing"), LIGHT)
    assert expected != pytest.approx(LIGHT)
    assert _xyz(subsystem_world_position(sub, ship)) == pytest.approx(expected)


def test_target_offset_uses_locked_subsystems_parent():
    ship = _Ship()
    sub = _Sub("Warp Core", LIGHT, "left wing")
    ship._subs = [sub]
    expected = part_pose.apply(_pose_of(ship, "left wing"), LIGHT)
    got = target_offset_world(ship, sub.GetPosition())
    assert _xyz(got) == pytest.approx(expected)


def test_severing_wing_spares_set_body_systems():
    impulse = _Sub("Impulse Engines", IMPULSE, "birdofprey")
    cannon = _Sub("Port Cannon", CANNON)
    ship = _Ship(subs=(impulse, cannon))
    part_severance.sever(ship, None, "left wing")
    assert impulse.condition == 100.0
    assert cannon.condition == 0.0


def test_running_light_set_part_follows_it():
    ship = _Ship()
    spec = RunningLightSpec(pos=LIGHT, rgb=(1, 1, 1), size=1.0, period=1.0,
                            duration=0.5, name="nav", physical_parent="left wing")
    (t,) = host_loop._articulated_running_lights(ship, None, [spec])
    assert t[:3] == pytest.approx(part_pose.apply(_pose_of(ship, "left wing"), LIGHT))
    plain = RunningLightSpec(pos=LIGHT, rgb=(1, 1, 1), size=1.0, period=1.0,
                             duration=0.5, name="nav")
    (u,) = host_loop._articulated_running_lights(ship, None, [plain])
    assert u[:3] == pytest.approx(LIGHT)


def test_running_light_honours_save_without_respawn(monkeypatch):
    """The spawn-time specs (what the host keeps and re-resolves every frame)
    see a running light SET in the SPV and Saved, with the overlay gone."""
    import App
    import engine.ui.ship_property_viewer_panel as mod
    from engine.appc import running_lights
    from engine.appc.properties import TGModelPropertySet
    from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

    class _LitShip(_Ship):
        def __init__(self):
            super().__init__()
            self._pset = TGModelPropertySet()
            nav = App.BlinkingLightProperty_Create("nav")
            pt = TGPoint3()
            pt.SetXYZ(*LIGHT)
            nav.SetPosition(pt)
            self._pset.AddToSet("Scene Root", nav)

        def GetPropertySet(self):
            return self._pset

    class _Target:
        def write(self, leaf, edits):
            pass

    monkeypatch.setattr(mod, "build_descriptors", lambda ship: [])
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: LEAF)
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    ship = _LitShip()
    poses = dict(ship._articulation_poses)
    specs = running_lights.lights_for(ship)          # captured at spawn
    (t,) = host_loop._articulated_running_lights(ship, None, specs)
    assert t[:3] == pytest.approx(LIGHT)              # Auto: the body

    p = ShipPropertyViewerPanel(ship_getter=lambda: ship)
    p.open()
    p._model_part_nodes = [{"name": n, "candidate": True} for n in BOXES]
    assert p.dispatch_event(
        'physical/move:{"key": "light:nav", "part": "left wing"}') is True
    assert p.dispatch_event("save") is True
    p.close()
    physical_parents.clear_preview()
    ship._articulation_poses = poses                  # the SPV forced rest

    (t,) = host_loop._articulated_running_lights(ship, None, specs)
    assert t[:3] == pytest.approx(
        part_pose.apply(_pose_of(ship, "left wing"), LIGHT))


def test_running_light_spec_tuple_unchanged():
    spec = RunningLightSpec(pos=(1, 2, 3), rgb=(4, 5, 6), size=7.0, period=8.0,
                            duration=9.0, name="x", physical_parent="p")
    assert spec.as_tuple() == (1, 2, 3, 4, 5, 6, 7.0, 8.0, 9.0)


def test_emitter_light_ignores_subsystem_parent(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("emitter light consulted a physical parent")

    # The ship really owns a subsystem SET to the body, while the light's own
    # position lies on the left wing: the light must follow its own position.
    sub = _Sub("Impulse Engines", IMPULSE, "birdofprey")
    ship = _Ship(subs=[sub])
    assert physical_parents.property_of(sub) is not None
    monkeypatch.setattr(physical_parents, "part_for_property", boom)
    spec = {"position": IMPULSE}
    d = host_loop._articulate_emitter_light(ship, None, spec, {"position": IMPULSE})
    assert d["position"] == pytest.approx(part_pose.apply(_pose_of(ship, "left wing"), IMPULSE))


def test_unrigged_ship_never_resolves(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("resolver ran on an unrigged ship")

    monkeypatch.setattr(physical_parents, "part_for_property", boom)
    monkeypatch.setattr(part_severance, "part_for_mount", boom)
    ship = _Ship(poses=False)
    ship._articulation_leaf = "unriggedleaf"
    sub = _Sub("Impulse Engines", IMPULSE, "left wing")
    assert _xyz(subsystem_world_position(sub, ship)) == pytest.approx(IMPULSE)
    spec = RunningLightSpec(pos=LIGHT, rgb=(1, 1, 1), size=1.0, period=1.0,
                            duration=0.5, name="n", physical_parent="left wing")
    (t,) = host_loop._articulated_running_lights(ship, None, [spec])
    assert t[:3] == pytest.approx(LIGHT)


def test_none_prop_takes_the_geometric_rule():
    assert physical_parents.property_of(object()) is None
    assert physical_parents.part_for_property(LEAF, None, IMPULSE) == "left wing"
