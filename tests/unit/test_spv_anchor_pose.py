"""The SPV draws the pose it is TOLD to -- defaulting to the model's own NIF
pose, so mounts are edited in the frame they are stored in.

The hologram re-draws the LIVE player instance and honours node_overrides by
design (hologram_pass.cc:51-56 -- it must, or pins on an articulated part land
wrong). Opening the SPV freezes the sim but does not reset the pose, so
without a forced push the hologram keeps whatever pose was last pushed: a Bird
of Prey opened at green alert is drawn wings-up and every mount authored
through it is ~0.9 ship units out.

THREE layers, and the splits matter -- each one shipped broken on its own:

  * `articulation.force_pose(ship, state)` -- WHAT pose, written once at the
    SPV's event edges into `ship._articulation_angles`, the single dict every
    reader of a live pose consults. Applying the forced pose in the render
    sweep instead drew the wings down while every cannon pin floated at its
    stale raised position; see "ONE SOURCE OF TRUTH" below.
  * `_sync_ship_articulation` -- pushing that pose into the node override.
  * `_sync_spv_articulation` + its call site in `run()` -- whether the push
    happens at all on a frozen frame. The SPV freezes the sim, and this
    originally sat under `if not pause.sim_frozen:`. See "THE GUARD" below.
"""
import math

import pytest

from engine.appc import articulation


class _Session:
    def __init__(self, ships=()):
        self.ship_articulation = {}
        self.ship_instances = {ship: 7 + i for i, ship in enumerate(ships)}


class _Panel:
    """Stand-in for the `ShipPropertyViewerPanel` local that `run()` holds --
    the sweep is handed the panel, not the module, because that is what is in
    scope at the call site."""

    def __init__(self, is_open=True):
        self._open = is_open

    def is_open(self):
        return self._open


class _Ship:
    """`deflection` is a test convenience, not a production concept any
    more: it scales each part's authored "cruise" angle (the fully-deflected,
    up/cold pose) into `_articulation_angles`, the ONLY thing
    `_sync_ship_articulation` (via `articulation.angle_for_part`) reads.
    Building the dict here, rather than going through `tick_ship`, is
    deliberate for the tests in this file: they are about a FIXED pose and
    the render-sync's own guard/force_state logic, not about motion over
    time."""

    def __init__(self, deflection=1.0):
        self._articulation_leaf = "birdofprey"
        self._articulation_angles = {
            p.GetName(): p.angle_for("cruise") * deflection
            for p in articulation.rig_for("birdofprey")
        }


@pytest.fixture
def pushes(monkeypatch):
    """Record every set_instance_node_rotation the sync makes."""
    from engine import host_io
    seen = []
    monkeypatch.setattr(
        host_io, "set_instance_node_rotation",
        lambda iid, node, pivot, axis, theta: seen.append((node, theta)))
    return seen


def test_the_fixture_ship_actually_articulates(pushes):
    """Guard. If the BoP rig ever stops resolving, every test below would pass
    vacuously by pushing nothing at all."""
    from engine import host_loop
    host_loop._sync_ship_articulation(_Session(), _Ship(deflection=1.0), 7)
    assert pushes, "the fixture must push a real pose, or the tests prove nothing"
    assert any(theta != 0.0 for _node, theta in pushes)


def test_the_anchor_pose_pushes_ZERO_rotation_on_every_part(pushes):
    """THE POINT. Not 'pushes nothing' -- pushing nothing would leave the
    previous articulated pose standing in node_overrides.

    The anchor pose now arrives the same way every other pose does: written
    into `_articulation_angles` by `force_pose`, then read back out by the
    sync. There is no second, render-side forcing path to test."""
    from engine import host_loop
    ship = _Ship(deflection=1.0)
    articulation.force_pose(ship, None)
    host_loop._sync_ship_articulation(_Session(), ship, 7)
    assert pushes, "the rest pose must be pushed, not merely not-overwritten"
    assert all(theta == 0.0 for _node, theta in pushes), pushes


def test_the_render_sync_does_not_mutate_the_ship(pushes):
    """_sync_ship_articulation is READ-ONLY on game state -- a mutation in the
    render path is what once gave the player's phasers half a second aiming at
    a destroyed subsystem. `force_pose` is the mutation, and it is an
    EVENT-EDGE call on the sim side, not a per-frame one."""
    from engine import host_loop
    ship = _Ship(deflection=1.0)
    articulation.force_pose(ship, None)
    before = dict(ship._articulation_angles)
    host_loop._sync_ship_articulation(_Session(), ship, 7)
    assert ship._articulation_angles == before


def test_the_change_guard_still_fires_on_the_open_and_close_edges(pushes):
    """The sync is guarded on CHANGE so a settled ship costs one float compare.
    Forcing the anchor pose must not defeat that, and must not be defeated BY
    it: opening the SPV has to push once, and closing has to push the live
    pose back."""
    from engine import host_loop
    session, ship = _Session(), _Ship(deflection=1.0)

    host_loop._sync_ship_articulation(session, ship, 7)            # live
    live = list(pushes); pushes.clear()
    assert live

    articulation.force_pose(ship, None)                            # SPV opens
    host_loop._sync_ship_articulation(session, ship, 7)
    assert pushes, "the open edge must re-push"
    assert all(theta == 0.0 for _n, theta in pushes)
    pushes.clear()

    host_loop._sync_ship_articulation(session, ship, 7)
    assert pushes == [], "a settled forced pose must not re-push every frame"

    ship._articulation_angles = _Ship(deflection=1.0)._articulation_angles
    host_loop._sync_ship_articulation(session, ship, 7)
    assert pushes, "the close edge must restore the live pose"
    assert any(theta != 0.0 for _n, theta in pushes)


def test_a_severed_part_stays_severed_while_forced(pushes, monkeypatch):
    """A severed part is HIDDEN through the same node_overrides slot this
    rotation writes. Pushing a rest rotation onto it would snap the wing back
    onto the hull and then erase the hide for good."""
    from engine import host_loop
    from engine.appc import part_severance
    monkeypatch.setattr(part_severance, "is_detached",
                        lambda s, node: node == "left wing")
    ship = _Ship(deflection=1.0)
    articulation.force_pose(ship, None)
    host_loop._sync_ship_articulation(_Session(), ship, 7)
    assert pushes, "the other wing must still be posed"
    assert all(node != "left wing" for node, _t in pushes)


def test_an_unrigged_ship_is_untouched(pushes):
    from engine import host_loop
    ship = _Ship()
    ship._articulation_leaf = ""
    articulation.force_pose(ship, None)
    host_loop._sync_ship_articulation(_Session(), ship, 7)
    assert pushes == []


# ---------------------------------------------------------------------------
# THE GUARD (final review, Finding 1). Everything above enters at
# `_sync_ship_articulation`, two levels below the `if not pause.sim_frozen:`
# that -- until this fix -- skipped the whole articulation sweep on exactly
# the frames the SPV is open for: opening the SPV sets `pause._open`, which
# sets `sim_frozen`. A green suite never saw it.
# ---------------------------------------------------------------------------

def _guarded_and_free_articulation_calls():
    """(guarded, free) call names in `host_loop.run` that reach
    `_sync_ship_articulation`, split by whether they sit inside
    `if not pause.sim_frozen:`.

    STRUCTURAL, deliberately. `run()` is one ~2100-line function that needs a
    live renderer, a CEF view and the native host in scope; there is no seam
    to execute a single frame of it from a test. What IS checkable -- and is
    the actual defect -- is the NESTING: some call reaching the articulation
    sweep has to exist outside that guard, or the SPV can never force a pose.
    """
    import ast
    import inspect
    from engine import host_loop

    tree = ast.parse(inspect.getsource(host_loop.run))

    def _is_sim_frozen_guard(node):
        t = node.test
        return (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)
                and isinstance(t.operand, ast.Attribute)
                and t.operand.attr == "sim_frozen")

    guarded_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_sim_frozen_guard(node):
            for body_stmt in node.body:
                for inner in ast.walk(body_stmt):
                    guarded_nodes.add(id(inner))

    reaching = {"_sync_ship_articulation", "_sync_instance_transforms",
                "_sync_spv_articulation"}
    guarded, free = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
        if name not in reaching:
            continue
        (guarded if id(node) in guarded_nodes else free).append(name)
    return guarded, free


def test_the_articulation_sweep_runs_while_the_sim_is_FROZEN():
    """THE POINT of the whole branch. Opening the SPV freezes the sim, so an
    articulation push that only happens under `if not pause.sim_frozen:`
    never happens while the viewer is open -- the anchor pose is never forced
    and Preview can never move a wing."""
    guarded, free = _guarded_and_free_articulation_calls()
    assert guarded or free, "no articulation call found in run() at all"
    assert free, (
        "every call reaching _sync_ship_articulation in run() is nested "
        "inside `if not pause.sim_frozen:` (%r) -- the SPV forces its pose "
        "on exactly the frames that block is skipped" % (guarded,))


# ---------------------------------------------------------------------------
# `_sync_spv_articulation` -- the sweep the call site above must reach. It
# pushes the ship's LIVE angles, exactly like the unfrozen path; it knows
# nothing about the forced state. The forcing happened earlier, at the SPV's
# event edge, in the shared dict.
# ---------------------------------------------------------------------------

@pytest.fixture
def dev_on(monkeypatch):
    from engine import dev_mode
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)


def test_the_sweep_pushes_the_ANCHOR_pose_the_edge_forced(pushes, dev_on):
    """Every part at angle 0 -- the frame a hardpoint mount is stored in."""
    from engine import host_loop
    ship = _Ship(deflection=1.0)
    articulation.force_pose(ship, None)          # the SPV's open edge
    host_loop._sync_spv_articulation(_Session([ship]), _Panel())
    assert pushes, "the anchor pose must be PUSHED, not merely not-overwritten"
    assert all(theta == 0.0 for _n, theta in pushes), pushes


def test_the_sweep_pushes_the_PREVIEWED_state(pushes, dev_on):
    """Preview is not a lock toggle and a button highlight -- clicking it has
    to move the wings, through this same path."""
    from engine import host_loop
    ship = _Ship(deflection=0.0)          # live pose is the NIF pose
    articulation.set_dev_override("cruise")
    articulation.force_pose(ship, "cruise")      # the SPV's Preview edge
    host_loop._sync_spv_articulation(_Session([ship]), _Panel())
    assert pushes
    expected = sorted(
        math.radians(p.angle_for("cruise"))
        for p in articulation.rig_for("birdofprey"))
    assert sorted(theta for _n, theta in pushes) == pytest.approx(expected)
    assert any(theta != 0.0 for _n, theta in pushes)


def test_the_sweep_is_INERT_in_production(pushes, monkeypatch):
    """Not --developer: the SPV cannot be open, and nothing may be pushed."""
    from engine import host_loop
    from engine import dev_mode
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    host_loop._sync_spv_articulation(_Session([_Ship(deflection=1.0)]),
                                     _Panel())
    assert pushes == []


def test_the_sweep_is_inert_while_the_viewer_is_CLOSED(pushes, dev_on):
    from engine import host_loop
    host_loop._sync_spv_articulation(_Session([_Ship(deflection=1.0)]),
                                     _Panel(is_open=False))
    assert pushes == []


def test_the_sweep_keeps_a_SEVERED_part_hidden(pushes, dev_on, monkeypatch):
    """The hide and this rotation share one node_overrides slot; re-posing a
    severed wing snaps it back onto the hull."""
    from engine import host_loop
    from engine.appc import part_severance
    monkeypatch.setattr(part_severance, "is_detached",
                        lambda s, node: node == "left wing")
    host_loop._sync_spv_articulation(_Session([_Ship(deflection=1.0)]),
                                     _Panel())
    assert pushes, "the other wing must still be posed"
    assert all(node != "left wing" for node, _t in pushes)


# ---------------------------------------------------------------------------
# ONE SOURCE OF TRUTH (live bug, Mark's pass). The wings drew DOWN correctly
# while the disruptor-cannon pins floated in space at their RAISED positions.
#
# The mesh read the sweep's FORCED pose; every mount read
# `ship._articulation_angles`, which `tick_ship` owns -- and `tick_ship` never
# runs while the SPV is open, because the SPV freezes the sim. So the two
# halves resolved different angles for the same part.
#
# Each test above pins ONE side. That is exactly how this got through, so the
# test below pins the AGREEMENT.
# ---------------------------------------------------------------------------

def test_the_MOUNT_and_the_MESH_resolve_the_SAME_angle(pushes, dev_on):
    """THE LINCHPIN. Whatever pose the viewer is showing, the angle a mount
    resolves through `angle_for_part` must be the angle the render sweep
    pushes into the node override -- for every part, at any instant."""
    from engine import host_loop
    ship = _Ship(deflection=1.0)          # live angles: cruise, +/-45 deg
    host_loop._sync_spv_articulation(_Session([ship]), _Panel())

    drawn = dict(pushes)
    assert drawn, "nothing was pushed; the test would prove nothing"
    for part in articulation.rig_for("birdofprey"):
        mount = articulation.angle_for_part(ship, part)
        assert drawn[part.GetName()] == pytest.approx(math.radians(mount)), (
            "part %r: mesh drawn at %r rad, mount resolved at %r deg"
            % (part.GetName(), drawn[part.GetName()], mount))


def test_they_STILL_agree_once_the_anchor_pose_is_forced(pushes, dev_on):
    """The same assertion on the other side of the edge. Both must be zero --
    not 'the mesh is zero and the mount is whatever it was'."""
    from engine import host_loop
    ship = _Ship(deflection=1.0)
    articulation.force_pose(ship, None)
    host_loop._sync_spv_articulation(_Session([ship]), _Panel())

    drawn = dict(pushes)
    assert drawn
    for part in articulation.rig_for("birdofprey"):
        assert articulation.angle_for_part(ship, part) == 0.0
        assert drawn[part.GetName()] == 0.0


# The starboard wingtip disruptor cannon, as `hardpoint_overrides` authors it
# -- the mount whose pin Mark saw floating off the wing.
WINGTIP_CANNON = (1.008, 0.450, -0.670)


class _PosedShip(_Ship):
    """`_Ship` plus the world transform `subsystem_world_position` needs.
    Identity rotation at the origin, so a world position IS the body offset
    and the test can assert on it without unwinding anything."""

    def GetWorldLocation(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        from engine.appc.math import TGMatrix3
        return TGMatrix3()


class _Cannon:
    def __init__(self, pos):
        from engine.appc.math import TGPoint3
        self._p = TGPoint3(*pos)

    def GetPosition(self):
        return self._p


def test_the_wingtip_PIN_lands_on_the_wingtip(pushes, dev_on):
    """Mark's screenshot, at the level he saw it: the hull drew its wings
    DOWN while the disruptor-cannon pins floated in space at their RAISED
    positions. A pin is `subsystems.subsystem_world_position`, which reaches
    the same `_articulation_angles` the mesh does."""
    from engine import host_loop
    from engine.appc import subsystems
    ship = _PosedShip(deflection=1.0)         # live: wings up, +/-45
    articulation.force_pose(ship, None)       # the SPV's open edge
    host_loop._sync_spv_articulation(_Session([ship]), _Panel())

    assert all(theta == 0.0 for _n, theta in pushes), "the mesh must be at rest"
    pin = subsystems.subsystem_world_position(_Cannon(WINGTIP_CANNON), ship)
    assert (pin.x, pin.y, pin.z) == pytest.approx(WINGTIP_CANNON), (
        "the mesh is in its NIF pose, so the mount must be too")
