"""Manual Aim (BC "mouse pick fire", H key).

Spec: docs/superpowers/specs/2026-09-15-manual-aim-pick-fire-design.md
"""
import math

from engine.appc.math import TGPoint3


# ── Task 1: ShipClass target-offset state ────────────────────────────────────

def _ship_with_locked_subsystem():
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import ShipSubsystem
    ship = ShipClass()
    sub = ShipSubsystem("Warp Core")
    sub._position = TGPoint3(0.5, -2.0, 1.5)
    ship.SetTargetSubsystem(sub)
    return ship


def test_manual_offset_overrides_the_subsystem_offset_while_in_use():
    ship = _ship_with_locked_subsystem()
    ship.set_manual_target_offset(TGPoint3(3.0, 4.0, 5.0))

    assert ship.is_using_target_offset() is True
    o = ship.GetTargetOffsetTG()
    assert (o.x, o.y, o.z) == (3.0, 4.0, 5.0)


def test_get_target_offset_returns_a_copy_not_the_stored_point():
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    ship.set_manual_target_offset(TGPoint3(1.0, 2.0, 3.0))
    o = ship.GetTargetOffsetTG()
    o.x = 99.0
    assert ship.GetTargetOffsetTG().x == 1.0


def test_use_target_offset_zero_reverts_to_the_locked_subsystem():
    """E3M1.FixTargeting: UseTargetOffsetTG(0) == 'fix the targeted
    location to match the targeted subsystem'."""
    ship = _ship_with_locked_subsystem()
    ship.set_manual_target_offset(TGPoint3(3.0, 4.0, 5.0))

    ship.UseTargetOffsetTG(0)

    assert ship.is_using_target_offset() is False
    o = ship.GetTargetOffsetTG()
    assert (o.x, o.y, o.z) == (0.5, -2.0, 1.5)


def test_use_target_offset_one_without_a_stored_offset_is_not_in_use():
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    ship.UseTargetOffsetTG(1)
    assert ship.is_using_target_offset() is False
    o = ship.GetTargetOffsetTG()
    assert (o.x, o.y, o.z) == (0.0, 0.0, 0.0)


def test_changing_target_clears_the_manual_offset():
    """The offset is target-local; it cannot survive a retarget."""
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    a = ShipClass()
    b = ShipClass()
    ship.SetTarget(a)
    ship.set_manual_target_offset(TGPoint3(1.0, 1.0, 1.0))

    ship.SetTarget(a)                       # same object: keeps it
    assert ship.is_using_target_offset() is True
    ship.SetTarget(b)                       # different object: clears
    assert ship.is_using_target_offset() is False


# ── Task 2: weapon systems read the live offset ──────────────────────────────

def test_weapon_system_uses_the_ships_live_offset_while_manual_aim_is_on():
    """StartFiring captures the offset ONCE (_held_offset); with the cursor
    moving every frame, a torpedo fired mid-hold must read the ship's
    CURRENT offset, not the one captured at keydown."""
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import TorpedoSystem
    ship = ShipClass()
    sys_ = TorpedoSystem("Torpedoes")
    sys_.SetParentShip(ship)

    sys_._held_offset = TGPoint3(0.0, 0.0, 0.0)          # captured at keydown
    assert sys_._live_held_offset() is sys_._held_offset  # off: held wins

    ship.set_manual_target_offset(TGPoint3(2.0, 0.0, 7.0))
    live = sys_._live_held_offset()
    assert (live.x, live.y, live.z) == (2.0, 0.0, 7.0)

    ship.UseTargetOffsetTG(0)
    assert sys_._live_held_offset() is sys_._held_offset


def test_live_offset_tolerates_a_parent_without_the_manual_aim_api():
    """Legacy fakes / no parent: fall back to _held_offset, never raise."""
    from engine.appc.subsystems import TorpedoSystem
    sys_ = TorpedoSystem("Torpedoes")
    sys_._held_offset = "held"
    assert sys_._live_held_offset() == "held"
    class _Bare: pass
    sys_.SetParentShip(_Bare())
    assert sys_._live_held_offset() == "held"


# ── Task 3: phaser aim point ─────────────────────────────────────────────────

def _galaxy_target_at(x, y, z):
    from engine.appc.ships import ShipClass_Create
    t = ShipClass_Create("Galaxy")
    t.SetTranslateXYZ(x, y, z)
    return t


def test_phaser_aim_point_is_the_locked_subsystem_when_no_manual_offset():
    from engine.host_loop import _phaser_aim_point
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import ShipSubsystem
    ship = ShipClass()
    target = _galaxy_target_at(0.0, 100.0, 0.0)
    sub = ShipSubsystem("Bridge")
    sub._position = TGPoint3(0.0, 0.0, 4.0)
    sub.SetParentShip(target)
    ship.SetTarget(target)
    ship.SetTargetSubsystem(sub)

    point, from_sub = _phaser_aim_point(ship, target)

    assert from_sub is sub
    expect = sub.GetWorldLocation()
    assert (point.x, point.y, point.z) == (expect.x, expect.y, expect.z)


def test_phaser_aim_point_is_target_centre_with_no_lock():
    from engine.host_loop import _phaser_aim_point
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    target = _galaxy_target_at(0.0, 100.0, 0.0)
    point, from_sub = _phaser_aim_point(ship, target)
    assert from_sub is None
    assert (point.x, point.y, point.z) == (0.0, 100.0, 0.0)


def test_phaser_aim_point_uses_the_manual_offset_rotated_and_scaled():
    """Manual offset is target-local & unscaled: world = pos + R·(o·scale).
    Yaw the target 90° about Z so a body +X offset lands on world +Y."""
    from engine.host_loop import _phaser_aim_point
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import ShipSubsystem
    from engine.appc.math import TGMatrix3
    ship = ShipClass()
    target = _galaxy_target_at(0.0, 100.0, 0.0)
    rot = TGMatrix3()
    rot.MakeZRotation(math.pi / 2.0)
    target.SetMatrixRotation(rot)               # copied into the transform store
    sub = ShipSubsystem("Bridge")
    sub._position = TGPoint3(0.0, 0.0, 4.0)
    sub.SetParentShip(target)
    ship.SetTarget(target)
    ship.SetTargetSubsystem(sub)
    ship.set_manual_target_offset(TGPoint3(2.0, 0.0, 0.0))

    point, from_sub = _phaser_aim_point(ship, target)

    assert from_sub is None                       # cursor pick, not the lock
    scale = float(target.GetScale())
    assert abs(point.x - 0.0) < 1e-6
    assert abs(point.y - (100.0 + 2.0 * scale)) < 1e-6
    assert abs(point.z - 0.0) < 1e-6


def test_advance_combat_routes_phaser_damage_at_the_manual_offset(monkeypatch):
    """End-to-end through the damage tick: the fallback point handed to
    combat._resolve_hit_point is the manual offset's world position."""
    from engine import host_loop
    import engine.appc.combat as combat_mod
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import PhaserSystem, PhaserBank
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sys_ = PhaserSystem("Phasers")
    sys_._max_condition = 100.0
    sys_._condition = 100.0
    sys_._disabled_percentage = 0.75
    sys_.TurnOn()
    b = PhaserBank("Bank0")
    b._max_charge = 5.0; b._charge_level = 5.0; b._min_firing_charge = 3.0
    b._max_damage = 1.0; b._max_damage_distance = 1000.0
    b._max_condition = 100.0; b._condition = 100.0; b._disabled_percentage = 0.25
    sys_.AddChildSubsystem(b)
    ship.SetPhaserSystem(sys_)
    target = _galaxy_target_at(0.0, 100.0, 0.0)
    ship.SetTarget(target)
    ship.set_manual_target_offset(TGPoint3(0.0, 0.0, 5.0))
    sys_.StartFiring(target=target, offset=ship.GetTargetOffsetTG())
    assert b.IsFiring() == 1

    seen = []
    real = combat_mod._resolve_hit_point
    def spy(*a, **kw):
        seen.append(kw["fallback_point"])
        return real(*a, **kw)
    monkeypatch.setattr(combat_mod, "_resolve_hit_point", spy)
    monkeypatch.setattr(combat_mod, "apply_hit", lambda *a, **kw: None)

    host_loop._advance_combat([ship, target], dt=1.0 / 60, ship_instances=None)

    assert seen, "damage tick never resolved a hit point"
    fp = seen[0]
    scale = float(target.GetScale())
    assert abs(fp.x) < 1e-6 and abs(fp.y - 100.0) < 1e-6
    assert abs(fp.z - 5.0 * scale) < 1e-6


# ── Task 4: cursor ray ───────────────────────────────────────────────────────

def _dist_point_to_ray(p, origin, d):
    v = (p[0] - origin[0], p[1] - origin[1], p[2] - origin[2])
    t = v[0] * d[0] + v[1] * d[1] + v[2] * d[2]
    c = (origin[0] + d[0] * t, origin[1] + d[1] * t, origin[2] + d[2] * t)
    return math.sqrt(sum((p[i] - c[i]) ** 2 for i in range(3)))


def test_cursor_ray_inverts_project_for_off_centre_points():
    """Round trip: project a world point with the SPV projection the reticle
    uses, feed the pixel back through cursor_ray, and the ray must pass
    through the point (this is what makes the pick land where the cursor
    is drawn). Off-axis camera so no axis-aligned shortcut passes."""
    from engine.manual_aim import AimCamera, cursor_ray
    from engine.ui.ship_property_viewer import project
    cam = AimCamera(eye=(10.0, -50.0, 20.0), target=(0.0, 100.0, 0.0),
                    up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(60.0),
                    near=1.0, far=5000.0)
    viewport = (1600, 900)
    for world in ((0.0, 100.0, 0.0), (30.0, 140.0, -12.0), (-25.0, 80.0, 18.0)):
        sx, sy, _d, visible = project(world, cam, viewport)
        assert visible
        origin, direction = cursor_ray((sx, sy), viewport, cam)
        assert origin == cam.eye()
        assert abs(math.sqrt(sum(c * c for c in direction)) - 1.0) < 1e-9
        assert _dist_point_to_ray(world, origin, direction) < 1e-6


def test_cursor_ray_centre_pixel_is_the_camera_forward():
    from engine.manual_aim import AimCamera, cursor_ray
    cam = AimCamera(eye=(0.0, 0.0, 0.0), target=(0.0, 100.0, 0.0),
                    up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(45.0),
                    near=1.0, far=5000.0)
    _o, d = cursor_ray((400.0, 300.0), (800, 600), cam)
    assert abs(d[0]) < 1e-9 and abs(d[1] - 1.0) < 1e-9 and abs(d[2]) < 1e-9


def test_cursor_ray_rejects_degenerate_inputs():
    from engine.manual_aim import AimCamera, cursor_ray
    cam = AimCamera(eye=(0.0, 0.0, 0.0), target=(0.0, 100.0, 0.0),
                    up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(45.0),
                    near=1.0, far=5000.0)
    assert cursor_ray((1.0, 1.0), (0, 600), cam) is None
    same = AimCamera(eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, 0.0),
                     up=(0.0, 0.0, 1.0), fov_y_rad=1.0, near=1.0, far=10.0)
    assert cursor_ray((1.0, 1.0), (800, 600), same) is None


# ── Task 5: per-tick pick / revert ───────────────────────────────────────────

class _Tcw:
    def __init__(self, on): self._on = on
    def GetMousePickFire(self): return 1 if self._on else 0


def _aim_fixture():
    """Player at origin looking +Y (camera = chase, behind the player), a
    Galaxy 100 GU ahead, cursor at screen centre, camera noted."""
    from engine import manual_aim
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import ShipSubsystem
    manual_aim.reset()
    player = ShipClass()
    target = _galaxy_target_at(0.0, 100.0, 0.0)
    sub = ShipSubsystem("Bridge")
    sub._position = TGPoint3(0.0, 0.0, 4.0)
    sub.SetParentShip(target)
    player.SetTarget(target)
    player.SetTargetSubsystem(sub)
    cam = manual_aim.AimCamera(eye=(0.0, -20.0, 5.0), target=(0.0, 100.0, 0.0),
                               up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(45.0),
                               near=1.0, far=5000.0)
    return manual_aim, player, target, cam


def test_update_stores_the_hull_hit_as_a_target_local_unscaled_offset():
    manual_aim, player, target, cam = _aim_fixture()
    traced = []
    def ray_trace(iid, origin, direction, max_dist):
        traced.append((iid, origin, direction, max_dist))
        return ((0.0, 90.0, 5.0), (0.0, -1.0, 0.0), 90.0)   # hull hit, world

    live = manual_aim.update(player=player, tcw=_Tcw(True),
                             ship_instances={target: 7}, is_exterior=True,
                             cursor_fb=(400.0, 300.0), viewport_fb=(800, 600),
                             cam=cam, ray_trace=ray_trace)

    assert live is True
    assert traced[0][0] == 7                       # traced the TARGET's hull
    assert traced[0][1] == cam.eye()
    assert traced[0][3] == cam.far
    assert player.is_using_target_offset()
    o = player.GetTargetOffsetTG()
    scale = float(target.GetScale())
    assert abs(o.x - 0.0) < 1e-6
    assert abs(o.y - (-10.0 / scale)) < 1e-6         # 90 - 100, unscaled
    assert abs(o.z - (5.0 / scale)) < 1e-6


def test_update_reverts_to_the_subsystem_when_the_cursor_leaves_the_hull():
    manual_aim, player, target, cam = _aim_fixture()
    kw = dict(player=player, tcw=_Tcw(True), ship_instances={target: 7},
              is_exterior=True, cursor_fb=(400.0, 300.0),
              viewport_fb=(800, 600), cam=cam)
    manual_aim.update(ray_trace=lambda *a: ((0.0, 90.0, 5.0), (0.0, -1.0, 0.0), 90.0), **kw)
    assert player.is_using_target_offset()

    live = manual_aim.update(ray_trace=lambda *a: None, **kw)   # miss

    assert live is False
    assert player.is_using_target_offset() is False
    o = player.GetTargetOffsetTG()
    assert (o.x, o.y, o.z) == (0.0, 0.0, 4.0)      # back on the lock


def test_update_is_inert_when_the_flag_is_off_or_the_view_is_not_exterior():
    manual_aim, player, target, cam = _aim_fixture()
    calls = []
    hit = lambda *a: (calls.append(a) or ((0.0, 90.0, 5.0), (0.0, -1.0, 0.0), 90.0))
    base = dict(player=player, ship_instances={target: 7},
                cursor_fb=(400.0, 300.0), viewport_fb=(800, 600), cam=cam,
                ray_trace=hit)
    assert manual_aim.update(tcw=_Tcw(False), is_exterior=True, **base) is False
    assert manual_aim.update(tcw=_Tcw(True), is_exterior=False, **base) is False
    assert calls == []                              # never traced
    assert player.is_using_target_offset() is False


def test_update_drops_a_live_offset_when_the_flag_turns_off():
    manual_aim, player, target, cam = _aim_fixture()
    player.set_manual_target_offset(TGPoint3(1.0, 1.0, 1.0))
    manual_aim.update(player=player, tcw=_Tcw(False), ship_instances={target: 7},
                      is_exterior=True, cursor_fb=(0.0, 0.0), viewport_fb=(800, 600),
                      cam=cam, ray_trace=lambda *a: None)
    assert player.is_using_target_offset() is False


def test_update_only_picks_the_targeted_ship_never_a_bystander():
    """Assumption 2 in the spec: no retarget on hover. A hit on another
    ship's instance is not even attempted -- only the target's iid is traced."""
    manual_aim, player, target, cam = _aim_fixture()
    other = _galaxy_target_at(0.0, 60.0, 0.0)
    traced = []
    def ray_trace(iid, *a):
        traced.append(iid)
        return None
    manual_aim.update(player=player, tcw=_Tcw(True),
                      ship_instances={target: 7, other: 8}, is_exterior=True,
                      cursor_fb=(400.0, 300.0), viewport_fb=(800, 600),
                      cam=cam, ray_trace=ray_trace)
    assert traced == [7]
    assert player.GetTarget() is target


def test_update_with_no_target_or_no_instance_reverts_without_tracing():
    manual_aim, player, target, cam = _aim_fixture()
    player.set_manual_target_offset(TGPoint3(1.0, 1.0, 1.0))
    traced = []
    manual_aim.update(player=player, tcw=_Tcw(True), ship_instances={},
                      is_exterior=True, cursor_fb=(400.0, 300.0),
                      viewport_fb=(800, 600), cam=cam,
                      ray_trace=lambda *a: traced.append(a))
    assert traced == [] and player.is_using_target_offset() is False
    player.SetTarget(None)
    assert manual_aim.update(player=player, tcw=_Tcw(True), ship_instances={target: 7},
                             is_exterior=True, cursor_fb=(400.0, 300.0),
                             viewport_fb=(800, 600), cam=cam,
                             ray_trace=lambda *a: traced.append(a)) is False
    assert traced == []


def test_note_camera_is_data_only_and_read_by_update_by_default():
    manual_aim, player, target, cam = _aim_fixture()
    assert manual_aim.last_camera() is None
    manual_aim.note_camera(cam.eye(), cam.target, cam.up(), cam.fov_y_rad, cam.near, cam.far)
    noted = manual_aim.last_camera()
    assert noted.eye() == cam.eye() and noted.far == cam.far
    assert player.is_using_target_offset() is False           # no mutation
    seen = []
    manual_aim.update(player=player, tcw=_Tcw(True), ship_instances={target: 7},
                      is_exterior=True, cursor_fb=(400.0, 300.0),
                      viewport_fb=(800, 600),
                      ray_trace=lambda iid, o, d, m: seen.append(o) or None)
    assert seen == [cam.eye()]                                 # used the noted cam


def test_host_io_cursor_pos_is_none_headless(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.cursor_pos() is None


# ── Task 6: host-loop wiring (source-level guard; the loop body is not
#    unit-callable). Ordering is the point: the pick is a SIM-side mutation
#    that runs next to the key pollers, and the camera note is RENDER-side
#    data only, after r.set_camera.

def _host_loop_src():
    import inspect
    from engine import host_loop
    return inspect.getsource(host_loop)


def test_host_loop_runs_manual_aim_update_in_the_sim_block():
    src = _host_loop_src()
    i_poll = src.index("_poll_fire_keys(_h, input_map)")
    i_upd = src.index("manual_aim.update(")
    i_weap = src.index("_advance_weapons(_ships_this_tick, TICK_DT)")
    assert i_poll < i_upd < i_weap, "update must run after the key pollers and before the weapon tick"
    body = src[i_upd: i_upd + 400]
    assert "is_exterior=view_mode.is_exterior" in body
    assert "tcw=" in body and "player=player" in body


def test_host_loop_notes_the_camera_after_the_exterior_set_camera():
    src = _host_loop_src()
    anchor = "r.set_camera(eye=eye, target=target, up=up_vec,\n                             fov_y_rad=director.fov_y_rad,\n                             near=1.0, far=5000.0)"
    i_cam = src.index(anchor)
    i_note = src.index("manual_aim.note_camera(eye, target, up_vec, director.fov_y_rad, 1.0, 5000.0)")
    assert i_cam < i_note < i_cam + 600


def test_host_loop_resets_manual_aim_on_tcw_reset():
    src = _host_loop_src()
    i_tcw = src.index("_TCW._instance = None")
    i_reset = src.index("manual_aim.reset()")
    assert i_tcw < i_reset < i_tcw + 400
