import math
from engine.appc.math import TGPoint3, TGMatrix3
from engine.ui.ship_property_viewer import subsystem_world_position


class _FakeShip:
    def __init__(self, loc, rot):
        self._loc, self._rot = loc, rot
    def GetWorldLocation(self):
        return self._loc
    def GetWorldRotation(self):
        return self._rot


class _FakeSub:
    """Subsystem with a model-local mount and a parent ship."""
    def __init__(self, pos, ship):
        self._pos, self._ship = pos, ship
    def GetPosition(self):
        return None if self._pos is None else TGPoint3(*self._pos)
    def _climb_to_ship(self):
        return self._ship


def test_world_position_identity_rotation_adds_offset():
    ship = _FakeShip(TGPoint3(10.0, 0.0, 0.0), TGMatrix3())  # identity
    sub = _FakeSub((0.0, 1.0, 0.5), ship)
    w = subsystem_world_position(sub)
    assert (round(w.x, 5), round(w.y, 5), round(w.z, 5)) == (10.0, 1.0, 0.5)


def test_world_position_yaw_rotates_offset_columnvec():
    rot = TGMatrix3(); rot.MakeZRotation(math.pi / 2.0)  # +90 deg about Z
    ship = _FakeShip(TGPoint3(0.0, 0.0, 0.0), rot)
    sub = _FakeSub((0.0, 1.0, 0.0), ship)   # body +Y
    w = subsystem_world_position(sub)
    # Column-vector R.(0,1,0): +Y maps to -X for a +90 deg Z rotation.
    assert round(w.x, 5) == -1.0 and round(w.y, 5) == 0.0


def test_world_position_none_mount_returns_ship_location():
    ship = _FakeShip(TGPoint3(3.0, 4.0, 5.0), TGMatrix3())
    sub = _FakeSub(None, ship)
    w = subsystem_world_position(sub)
    assert (w.x, w.y, w.z) == (3.0, 4.0, 5.0)


from engine.ui.ship_property_viewer import OrbitCamera, project


def test_orbit_camera_eye_in_front_at_zero_angles():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    eye = cam.eye()
    # At yaw=pitch=0 the eye sits on +/-Y (BC forward) looking back at origin,
    # distance 10 -> one axis is +/-10, others ~0.
    assert round(max(abs(eye[0]), abs(eye[1]), abs(eye[2])), 4) == 10.0


def test_project_point_at_target_lands_at_screen_centre():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    sx, sy, depth, visible = project((0.0, 0.0, 0.0), cam, (800, 600))
    assert visible is True
    assert abs(sx - 400.0) < 0.5 and abs(sy - 300.0) < 0.5


def test_project_point_behind_camera_not_visible():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    # A point far on the far side beyond the target, behind the eye direction.
    far_behind = tuple(c * 1000.0 for c in cam.eye())
    sx, sy, depth, visible = project(far_behind, cam, (800, 600))
    assert visible is False


def test_extreme_pitch_clamp_matches_near_limit_reference():
    """Any pitch beyond _MAX_PITCH (e.g. from mouse drag past vertical) flips
    cos(pitch) negative, mirroring the horizontal axis and placing off-center
    points hundreds of pixels from where the clamp-limited camera would put
    them.  The clamp in eye() must cap all such inputs at _MAX_PITCH, so an
    off-center point always projects to the same finite coords as the reference
    camera sitting exactly at the clamp limit.

    Note: cos(pi/2) in Python floats is ~6e-17, not 0, so the basis is not
    truly degenerate at pi/2 exactly; the real regression case is any value
    *past* pi/2, hence pitch = pi/2 + 0.01 here."""
    import math as _m
    from engine.ui.ship_property_viewer import _MAX_PITCH
    off_center = (3.0, 0.0, 0.0)
    over_pitch = _m.pi / 2.0 + 0.01   # past vertical — cos goes negative
    cam_extreme = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0,
                              yaw=0.0, pitch=over_pitch)
    cam_ref = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0,
                          yaw=0.0, pitch=_MAX_PITCH)
    ex = project(off_center, cam_extreme, (800, 600))
    ref = project(off_center, cam_ref, (800, 600))
    # Finite (not NaN) and identical to the clamp-limit reference.
    assert ex[0] == ex[0] and ex[1] == ex[1]   # not NaN
    assert ex[3] is True
    assert abs(ex[0] - ref[0]) < 1e-6 and abs(ex[1] - ref[1]) < 1e-6


from engine.ui.ship_property_viewer import build_descriptors


class _StubSubsystem:
    def __init__(self, name, pos, cls_icon, disabled=False, condition=1.0):
        self._name, self._pos, self._icon = name, pos, cls_icon
        self._disabled, self._condition = disabled, condition
        self.parent_ship = None
    def GetName(self): return self._name
    def GetPosition(self):
        return None if self._pos is None else TGPoint3(*self._pos)
    def _climb_to_ship(self): return self.parent_ship
    def IsDisabled(self): return self._disabled
    def GetCondition(self): return self._condition


class _StubShip:
    def __init__(self, subs):
        self._subs = subs
        for s in subs:
            s.parent_ship = self
    def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
    def GetWorldRotation(self): return TGMatrix3()
    def __iter__(self): return iter(self._subs)


def test_build_descriptors_skips_subsystems_without_mount(monkeypatch):
    import engine.ui.ship_property_viewer as spv
    monkeypatch.setattr(spv, "_icon_id_for", lambda sub: 2)        # Phaser
    monkeypatch.setattr(spv, "_iter_subsystems", lambda ship: list(ship))
    mounted = _StubSubsystem("Dorsal Phaser 1", (0.0, 1.0, 0.5), 2)
    floating = _StubSubsystem("Abstract System", None, 6)
    ship = _StubShip([mounted, floating])
    descs = build_descriptors(ship)
    assert [d["name"] for d in descs] == ["Dorsal Phaser 1"]
    d = descs[0]
    assert d["icon_id"] == 2
    assert d["world_pos"] == (0.0, 1.0, 0.5)
    assert d["state"] in ("healthy", "damaged", "disabled", "destroyed")
    assert d["properties"]["name"] == "Dorsal Phaser 1"


from engine.ui.ship_property_viewer import _state_for


class _StateStub:
    """Minimal subsystem stub for testing _state_for predicate ladder."""
    def __init__(self, destroyed=False, disabled=False, damaged=False):
        self._destroyed, self._disabled, self._damaged = destroyed, disabled, damaged
    def IsDestroyed(self): return self._destroyed
    def IsDisabled(self): return self._disabled
    def IsDamaged(self): return self._damaged


def test_state_for_destroyed():
    assert _state_for(_StateStub(destroyed=True)) == "destroyed"


def test_state_for_disabled():
    assert _state_for(_StateStub(disabled=True)) == "disabled"


def test_state_for_damaged():
    assert _state_for(_StateStub(damaged=True)) == "damaged"


def test_state_for_healthy():
    assert _state_for(_StateStub()) == "healthy"


def test_state_for_destroyed_takes_priority_over_disabled():
    """IsDestroyed beats IsDisabled when both are True."""
    assert _state_for(_StateStub(destroyed=True, disabled=True)) == "destroyed"


from engine.ui.ship_property_viewer import pick_pin, PIN_RADIUS_PX


def test_pick_returns_nearest_pin_within_radius():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    descs = [
        {"name": "A", "world_pos": (0.0, 0.0, 0.0)},   # screen centre
        {"name": "B", "world_pos": (3.0, 0.0, 0.0)},   # off to one side
    ]
    idx = pick_pin(400.0, 300.0, descs, cam, (800, 600))
    assert idx == 0


def test_pick_returns_none_when_click_misses_all_pins():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    descs = [{"name": "A", "world_pos": (0.0, 0.0, 0.0)}]
    idx = pick_pin(400.0 + PIN_RADIUS_PX + 50.0, 300.0, descs, cam, (800, 600))
    assert idx is None
