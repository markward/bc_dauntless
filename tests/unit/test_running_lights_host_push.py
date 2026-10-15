"""Host-loop running-light wiring (running-lights spec §4.3)."""
import pytest

import App
from engine import host_loop
from engine.appc import running_light_dials
from engine.appc.math import TGPoint3
from engine.appc.properties import TGModelPropertySet
from engine.appc.subsystems import CloakingSubsystem


class _FakeRenderer:
    def __init__(self):
        self.lights = {}
        self.levels = None
        self.dials = None
        self.calls = []
    def set_running_lights(self, iid, lights, phase):
        self.lights[iid] = (list(lights), phase)
        self.calls.append(iid)
    def set_running_light_levels(self, levels):
        self.levels = list(levels)
    def set_running_light_dials(self, size_gu_per_radius, min_px, intensity):
        self.dials = (size_gu_per_radius, min_px, intensity)


class _Ship:
    def __init__(self, n_lights=2, name="USS Voyager", cloak=None, power=None):
        self._pset = TGModelPropertySet()
        for i in range(n_lights):
            p = App.BlinkingLightProperty_Create("L%d" % i)
            pt = TGPoint3(); pt.SetXYZ(float(i), 0.0, 0.0)
            p.SetPosition(pt)
            self._pset.AddToSet("Scene Root", p)
        self._name, self._cloak, self._power = name, cloak, power
    def GetPropertySet(self): return self._pset
    def GetName(self): return self._name
    def GetCloakingSubsystem(self): return self._cloak
    def GetPowerSubsystem(self): return self._power
    def IsDying(self): return 0
    def IsDead(self): return 0


class _Session:
    def __init__(self, mapping):
        self.ship_instances = dict(mapping)
        self.ship_running_lights = {}
        self.ship_running_light_specs = {}
        self.scope_hidden = set()


def test_register_sends_lights_once_with_phase():
    r = _FakeRenderer()
    ship = _Ship(n_lights=2)
    s = _Session({ship: 7})
    host_loop._register_running_lights(r, s, ship, 7)
    lights, phase = r.lights[7]
    assert len(lights) == 2 and len(lights[0]) == 9
    assert s.ship_running_lights == {7: phase}


def test_register_unlit_ship_sends_nothing():
    r = _FakeRenderer()
    ship = _Ship(n_lights=0)
    s = _Session({ship: 7})
    host_loop._register_running_lights(r, s, ship, 7)
    assert r.lights == {}
    assert s.ship_running_lights == {}


def test_push_sends_levels_and_dials_for_lit_ships():
    r = _FakeRenderer()
    lit, unlit = _Ship(2, name="A"), _Ship(0, name="B")
    s = _Session({lit: 1, unlit: 2})
    host_loop._register_running_lights(r, s, lit, 1)
    host_loop._register_running_lights(r, s, unlit, 2)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(1, 1.0)]
    assert r.dials == tuple(running_light_dials.current().values())


def test_push_scope_hidden_ship_is_dark():
    r = _FakeRenderer()
    ship = _Ship(2)
    s = _Session({ship: 3})
    host_loop._register_running_lights(r, s, ship, 3)
    s.scope_hidden.add(3)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(3, 0.0)]


def test_push_reads_cloak_fraction():
    c = CloakingSubsystem("Cloak")
    c.StartCloaking()
    c.Update(c._transition_duration * 0.5)
    frac = c.GetTransitionFraction()
    r = _FakeRenderer()
    ship = _Ship(2, cloak=c)
    s = _Session({ship: 4})
    host_loop._register_running_lights(r, s, ship, 4)
    host_loop._push_running_lights(r, s)
    assert r.levels[0][1] == pytest.approx(1.0 - frac)


def test_push_ship_without_cloak_or_power_subsystem_is_lit():
    r = _FakeRenderer()
    ship = _Ship(1, cloak=None, power=None)
    s = _Session({ship: 5})
    host_loop._register_running_lights(r, s, ship, 5)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(5, 1.0)]


def test_push_with_no_lit_ships_sends_nothing():
    r = _FakeRenderer()
    host_loop._push_running_lights(r, _Session({}))
    assert r.levels is None and r.dials is None


def test_push_drops_a_lit_iid_whose_ship_is_gone():
    r = _FakeRenderer()
    ship = _Ship(1)
    s = _Session({ship: 6})
    host_loop._register_running_lights(r, s, ship, 6)
    s.ship_instances.clear()        # removed without the pop (defensive)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(6, 0.0)]


def test_mission_session_teardown_clears_running_lights():
    class _R:
        def destroy_instance(self, iid):
            pass
    sess = host_loop.MissionSession(mission_name="t")
    sess.ship_running_lights[9] = 1.0
    sess.teardown(_R())
    assert sess.ship_running_lights == {}


# ── Ships whose hull the host loop hides (final review C1) ───────────────────
# The pass ignores inst->visible (lights keep fading through a cloak), so any
# OTHER hide the host loop applies must be mirrored as level 0 here, or the
# lights float on their own: the bridge-view player hide would put the
# player's forward blinkers mid-viewscreen.

class _VisRenderer(_FakeRenderer):
    """Adds the visibility/transform surface the hide writers call."""
    def __init__(self):
        super().__init__()
        self.visible = {}
    def set_visible(self, iid, v):
        self.visible[iid] = v
    def set_world_transform(self, iid, m):
        pass
    def set_emissive_scale(self, iid, s):
        pass
    def nebula_lightning_enabled(self):
        return False


def test_bridge_view_player_lights_are_dark():
    r = _VisRenderer()
    ship = _Ship(2)
    s = _Session({ship: 3})
    host_loop._register_running_lights(r, s, ship, 3)
    hidden = host_loop._apply_bridge_player_visibility(
        r, 3, is_bridge=True, spv_open=False)
    assert r.visible == {3: False}, "premise: bridge view hides the hull"
    host_loop._push_running_lights(r, s, hidden_iids=hidden)
    assert r.levels == [(3, 0.0)]


def test_player_outside_bridge_view_keeps_its_lights():
    r = _VisRenderer()
    ship = _Ship(2)
    s = _Session({ship: 3})
    host_loop._register_running_lights(r, s, ship, 3)
    hidden = host_loop._apply_bridge_player_visibility(
        r, 3, is_bridge=False, spv_open=False)
    host_loop._push_running_lights(r, s, hidden_iids=hidden)
    assert r.levels == [(3, 1.0)]


def test_bridge_view_with_spv_open_does_not_darken_the_lights():
    """The SPV owns visibility while open, so the bridge writer hides nothing
    and the lights must not be darkened on its behalf."""
    r = _VisRenderer()
    ship = _Ship(2)
    s = _Session({ship: 3})
    host_loop._register_running_lights(r, s, ship, 3)
    hidden = host_loop._apply_bridge_player_visibility(
        r, 3, is_bridge=True, spv_open=True)
    host_loop._push_running_lights(r, s, hidden_iids=hidden)
    assert r.levels == [(3, 1.0)]


class _StreakingWarp:
    def __init__(self, streak):
        self._streak = streak
    def is_active(self):
        return True
    def streak_intensity(self):
        return self._streak


def _sync_with_warp(monkeypatch, r, session, streak):
    from engine import warp_vfx
    from engine.core.transform_buffer import TransformBuffer
    monkeypatch.setattr(warp_vfx, "get", lambda: _StreakingWarp(streak))
    host_loop._sync_instance_transforms(
        r, session, None, TransformBuffer(), 1.0,
        game_time=1.0, model_scale=1.0)


def test_warp_hidden_ship_lights_are_dark_until_the_hide_ends(monkeypatch):
    monkeypatch.setattr(host_loop, "_warp_hidden", False)
    r = _VisRenderer()
    ship = App.ShipClass_Create()
    ship.SetName("Hidden in warp")
    p = App.BlinkingLightProperty_Create("L0")
    pt = TGPoint3(); pt.SetXYZ(0.0, 1.0, 0.0)
    p.SetPosition(pt)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    sess = host_loop.MissionSession(mission_name="t")
    sess.ship_instances[ship] = 5
    host_loop._register_running_lights(r, sess, ship, 5)

    _sync_with_warp(monkeypatch, r, sess, streak=1.0)
    assert r.visible == {5: False}, "premise: the warp transit hid the hull"
    host_loop._push_running_lights(r, sess)
    assert r.levels == [(5, 0.0)]

    # Stop frame: the hide is lifted, so are the lights.
    _sync_with_warp(monkeypatch, r, sess, streak=0.0)
    assert r.visible == {5: True}
    host_loop._push_running_lights(r, sess)
    assert r.levels == [(5, 1.0)]


def test_run_feeds_both_hull_hides_to_the_running_light_push():
    """Source-order guard (run() is one monolithic loop; cf.
    tests/host/test_scene_reconcile_ordering.py): the bridge-view hide's
    result reaches _push_running_lights, and the warp hide (inside
    _sync_instance_transforms) has run before it."""
    import inspect
    src = inspect.getsource(host_loop.run)
    push = src.find("_push_running_lights(r, session, "
                    "hidden_iids=_bridge_hidden_iids)")
    bridge = src.find("_bridge_hidden_iids = _apply_bridge_player_visibility(")
    warp = src.find("_sync_instance_transforms(")
    assert push >= 0, "run() must pass the bridge-view hide to the push"
    assert 0 <= bridge < push
    assert 0 <= warp < push


# ── Articulated parts (lights ride the part they sit on) ──────────────────────
# The conftest seeds a frozen Bird of Prey rig ("left wing", "left wing01") and
# its per-part boxes under leaf "birdofprey"; a ship double opts in by setting
# `_articulation_leaf`, exactly as the part-articulation suite does.

_WING_LIGHT = (-0.6, 0.0, -0.2)      # inside the "left wing" box only
_BODY_LIGHT = (0.0, 0.0, 0.0)        # inside the hull-body box only


class _RiggedShip(_Ship):
    def __init__(self, positions, name="IKS Rigged"):
        super().__init__(n_lights=0, name=name)
        for i, pos in enumerate(positions):
            p = App.BlinkingLightProperty_Create("R%d" % i)
            pt = TGPoint3(); pt.SetXYZ(*pos)
            p.SetPosition(pt)
            self._pset.AddToSet("Scene Root", p)
        self._articulation_leaf = "birdofprey"


def _wing_pose():
    from engine.appc import part_pose
    return part_pose.hinge_pose((-0.16, 0.0, 0.05), (0.0, 1.0, 0.0), 45.0)


def _sent_positions(r, iid):
    return [tuple(l[:3]) for l in r.lights[iid][0]]


def test_light_on_a_posed_part_is_sent_at_the_posed_position():
    from engine.appc import articulation, part_pose
    r = _FakeRenderer()
    ship = _RiggedShip([_WING_LIGHT, _BODY_LIGHT])
    s = _Session({ship: 11})
    host_loop._register_running_lights(r, s, ship, 11)
    articulation.force_part_pose(ship, "left wing", _wing_pose())
    host_loop._push_running_lights(r, s)
    wing, body = _sent_positions(r, 11)
    assert wing == pytest.approx(part_pose.apply(_wing_pose(), _WING_LIGHT))
    assert wing != pytest.approx(_WING_LIGHT)
    assert body == pytest.approx(_BODY_LIGHT)


def test_a_pose_change_resends_once_and_a_steady_pose_sends_nothing():
    from engine.appc import articulation
    r = _FakeRenderer()
    ship = _RiggedShip([_WING_LIGHT])
    s = _Session({ship: 12})
    host_loop._register_running_lights(r, s, ship, 12)
    host_loop._push_running_lights(r, s)          # rest pose: matches spawn send
    assert r.calls == [12]
    articulation.force_part_pose(ship, "left wing", _wing_pose())
    host_loop._push_running_lights(r, s)
    assert r.calls == [12, 12]
    host_loop._push_running_lights(r, s)          # pose unchanged
    assert r.calls == [12, 12]


def test_a_part_already_posed_at_spawn_is_sent_posed():
    from engine.appc import articulation, part_pose
    r = _FakeRenderer()
    ship = _RiggedShip([_WING_LIGHT])
    articulation.force_part_pose(ship, "left wing", _wing_pose())
    s = _Session({ship: 13})
    host_loop._register_running_lights(r, s, ship, 13)
    assert _sent_positions(r, 13)[0] == pytest.approx(
        part_pose.apply(_wing_pose(), _WING_LIGHT))


def test_lights_on_a_severed_part_are_dropped():
    from engine.appc import part_severance
    r = _FakeRenderer()
    ship = _RiggedShip([_WING_LIGHT, _BODY_LIGHT])
    s = _Session({ship: 14})
    host_loop._register_running_lights(r, s, ship, 14)
    part_severance.detached_parts(ship).add("left wing")
    host_loop._push_running_lights(r, s)
    assert _sent_positions(r, 14) == [pytest.approx(_BODY_LIGHT)]


def test_unrigged_ship_is_never_resent():
    r = _FakeRenderer()
    ship = _Ship(n_lights=2)
    s = _Session({ship: 15})
    host_loop._register_running_lights(r, s, ship, 15)
    for _ in range(3):
        host_loop._push_running_lights(r, s)
    assert r.calls == [15]


def test_teardown_and_removal_drop_the_articulation_record():
    class _R:
        def destroy_instance(self, iid):
            pass
    sess = host_loop.MissionSession(mission_name="t")
    sess.ship_running_light_specs[9] = ((), ())
    sess.teardown(_R())
    assert sess.ship_running_light_specs == {}


# ── Intrepid-shaped rig: nacelle lights authored ON the skin ─────────────────
# Boxes measured from LCintrepid.nif (node transforms applied, ship units).
# The hull box spans the full saucer width, so it CONTAINS every nacelle light;
# the dorsal nacelle light sits 0.0003 above the nacelle box's top face and the
# ventral one on its bottom face. "Inside exactly one box" attribution handed
# both to the hull, so they never moved when the nacelles folded for warp.

_INTREPID_BOXES = {
    "hull": ((-0.663, -1.71, -0.326), (0.663, 1.71, 0.326)),
    "wing left": ((-0.724, -1.556, -0.217), (-0.331, -0.585, -0.0700)),
    "wing right": ((0.331, -1.556, -0.217), (0.724, -0.585, -0.0700)),
}
_PORT_DORSAL_NACELLE = (-0.631987, -1.417070, -0.069732)
_PORT_VENTRAL_NACELLE = (-0.630074, -1.416740, -0.217036)
_AFT_HULL_LIGHT = (-0.146119, -1.638580, -0.114352)


def _intrepid_rig():
    from engine.appc import part_pose
    from engine.appc.articulated_part import ArticulatedPartProperty
    rig = []
    for name, x, angle in (("wing left", -0.323, 40.0), ("wing right", 0.323, -40.0)):
        p = ArticulatedPartProperty(name)
        anchor = (x, -1.2446, -0.1434)
        p.SetAnchor(*anchor)
        p.SetStatePose("warp", *part_pose.pose_to6(
            part_pose.hinge_pose(anchor, (0.0, 1.0, 0.0), angle)))
        rig.append(p)
    return tuple(rig)


@pytest.fixture
def intrepid_leaf(monkeypatch):
    from engine.appc import articulated_part, articulation
    monkeypatch.setitem(articulated_part._BY_LEAF, "intrepidfixture", _intrepid_rig())
    monkeypatch.setitem(articulation._derived_boxes, "intrepidfixture", _INTREPID_BOXES)
    return "intrepidfixture"


def test_nacelle_lights_on_the_skin_fold_with_the_nacelle(intrepid_leaf):
    from engine.appc import articulation, part_pose
    r = _FakeRenderer()
    ship = _RiggedShip([_PORT_DORSAL_NACELLE, _PORT_VENTRAL_NACELLE, _AFT_HULL_LIGHT])
    ship._articulation_leaf = intrepid_leaf
    s = _Session({ship: 21})
    host_loop._register_running_lights(r, s, ship, 21)
    part = articulation.parts_for_ship(ship)[0]
    warp = articulation.target_pose(part, "warp")
    articulation.force_part_pose(ship, "wing left", warp)
    host_loop._push_running_lights(r, s)
    dorsal, ventral, aft = _sent_positions(r, 21)
    assert dorsal == pytest.approx(part_pose.apply(warp, _PORT_DORSAL_NACELLE))
    assert ventral == pytest.approx(part_pose.apply(warp, _PORT_VENTRAL_NACELLE))
    assert aft == pytest.approx(_AFT_HULL_LIGHT)          # hull light stays put


def test_surface_attribution_prefers_the_smallest_containing_box(intrepid_leaf):
    from engine.appc.part_severance import part_for_surface_point
    assert part_for_surface_point(intrepid_leaf, _PORT_DORSAL_NACELLE) == "wing left"
    assert part_for_surface_point(intrepid_leaf, _PORT_VENTRAL_NACELLE) == "wing left"
    assert part_for_surface_point(intrepid_leaf, _AFT_HULL_LIGHT) == "hull"
    assert part_for_surface_point(intrepid_leaf, (0.0, 0.0, 5.0)) is None


def test_hit_attribution_is_unchanged_for_the_same_points(intrepid_leaf):
    """Weapon-hit attribution keeps its own rule (inside exactly one box wins;
    a point just off the nacelle's skin is the hull's); only authored skin
    points use the smallest-box rule."""
    from engine.appc.part_severance import part_for_point
    assert part_for_point(intrepid_leaf, _PORT_VENTRAL_NACELLE) == "hull"
    assert part_for_point(intrepid_leaf, _PORT_DORSAL_NACELLE) == "hull"
