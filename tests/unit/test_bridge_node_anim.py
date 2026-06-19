import math
from engine.bridge_node_anim import (
    BridgeNodeAnimController, mat_mul, mat_inverse_rigid, identity4,
)


def _rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [c, -s, 0, 0,  s, c, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1]


def _trans(x, y, z):
    return [1, 0, 0, x,  0, 1, 0, y,  0, 0, 1, z,  0, 0, 0, 1]


class _FakeRenderer:
    def __init__(self, seat_rest, seat_animated):
        self._rest = seat_rest
        self._anim = seat_animated
        self.node_clips = []        # (iid, path, loop, reverse)
        self.stopped = []
        self.world_sets = {}        # officer_iid -> 16 floats
    def play_instance_node_clip(self, iid, path, loop=False, reverse=False):
        self.node_clips.append((iid, path, loop, reverse))
    def stop_instance_node_anim(self, iid):
        self.stopped.append(iid)
    def instance_node_world(self, iid, node_name, animated=True):
        return self._anim if animated else self._rest
    def set_world_transform(self, iid, mat):
        self.world_sets[iid] = list(mat)


class _Officer:
    def __init__(self, iid):
        self._render_instance = iid


def test_rest_delta_is_identity_leaves_officer_unchanged():
    # seat animated == seat rest -> R_delta = I -> coupling = identity.
    seat = _trans(0, 5, 0)
    r = _FakeRenderer(seat_rest=seat, seat_animated=seat)
    ctrl = BridgeNodeAnimController(bridge_iid_getter=lambda: 1)
    off = _Officer(7)
    ctrl.turn_chair(off, {"clip_nif": "db_chair_H_face_capt.nif",
                          "seat_node": "console seat 01"}, renderer=r)
    ctrl.update(r)
    # Officer world set to identity (within tolerance).
    got = r.world_sets[7]
    for i, v in enumerate(identity4()):
        assert abs(got[i] - v) < 1e-6


def test_chair_rotation_rotates_officer_about_seat_pivot():
    # Seat rotates 90deg about Z at pivot (0,5,0). Officer should be rotated
    # about that pivot, NOT about the origin.
    pivot = (0.0, 5.0, 0.0)
    seat_rest = _trans(*pivot)
    seat_anim = mat_mul(_trans(*pivot), _rot_z(90))   # rotate in place at pivot
    r = _FakeRenderer(seat_rest=seat_rest, seat_animated=seat_anim)
    ctrl = BridgeNodeAnimController(bridge_iid_getter=lambda: 1)
    off = _Officer(7)
    ctrl.turn_chair(off, {"clip_nif": "c.nif", "seat_node": "console seat 01"},
                    renderer=r)
    ctrl.update(r)
    coupling = r.world_sets[7]
    # The pivot point must be a fixed point of the coupling transform.
    px, py, pz = pivot
    tx = coupling[0]*px + coupling[1]*py + coupling[2]*pz + coupling[3]
    ty = coupling[4]*px + coupling[5]*py + coupling[6]*pz + coupling[7]
    assert abs(tx - px) < 1e-5 and abs(ty - py) < 1e-5


def test_turn_chair_plays_forward_clip_on_bridge_instance():
    r = _FakeRenderer(_trans(0,0,0), _trans(0,0,0))
    ctrl = BridgeNodeAnimController(bridge_iid_getter=lambda: 9,
                                    asset_resolver=lambda p: "/abs/" + p)
    ctrl.turn_chair(_Officer(7), {"clip_nif": "c.nif",
                                  "seat_node": "console seat 01"}, renderer=r)
    assert r.node_clips[-1] == (9, "/abs/c.nif", False, False)


def test_unturn_reverses_then_reset_clears():
    r = _FakeRenderer(_trans(0,0,0), _trans(0,0,0))
    ctrl = BridgeNodeAnimController(bridge_iid_getter=lambda: 9)
    off = _Officer(7)
    ctrl.turn_chair(off, {"clip_nif": "c.nif", "seat_node": "s"}, renderer=r)
    ctrl.unturn_chair(off, {"clip_nif": "c.nif", "seat_node": "s"}, renderer=r)
    assert r.node_clips[-1] == (9, "c.nif", False, True)   # reverse
    ctrl.reset(renderer=r)
    assert 9 in r.stopped


def test_no_bridge_instance_is_graceful():
    r = _FakeRenderer(_trans(0,0,0), _trans(0,0,0))
    ctrl = BridgeNodeAnimController(bridge_iid_getter=lambda: None)
    ctrl.turn_chair(_Officer(7), {"clip_nif": "c.nif", "seat_node": "s"},
                    renderer=r)
    ctrl.update(r)            # no crash, nothing set
    assert r.world_sets == {}


# ---------------------------------------------------------------------------
# Regression: _discover_seat_node must read the "node" key emitted by the
# real native binding (host_bindings.cc:931: td["node"] = tr.target_node_name).
# The old code only checked "target_node_name"/"name", so discovery silently
# returned None and the seated officer was never coupled to the chair.
# ---------------------------------------------------------------------------

class _FakeRendererWithClips(_FakeRenderer):
    """Extends _FakeRenderer with load_animation_clips returning the exact
    shape the native C++ binding emits: tracks keyed "node", not
    "target_node_name"."""
    def __init__(self, seat_rest, seat_animated, clips):
        super().__init__(seat_rest, seat_animated)
        self._clips = clips

    def load_animation_clips(self, path):
        return self._clips


def test_discover_seat_node_reads_native_node_key():
    """_discover_seat_node must find the seat via the "node" key (the native
    binding's actual output).  The camera track ("Camera captain") must be
    skipped; "console seat 01" must be discovered and coupling must register."""
    # Native binding shape: list of clip dicts with "tracks" list; each track
    # has "node" (NOT "target_node_name" or "name").
    native_clips = [
        {
            "tracks": [
                {"node": "Camera captain", "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
                {"node": "console seat 01", "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
            ]
        }
    ]
    seat = _trans(0, 5, 0)
    r = _FakeRendererWithClips(seat_rest=seat, seat_animated=seat, clips=native_clips)
    ctrl = BridgeNodeAnimController(bridge_iid_getter=lambda: 1)
    off = _Officer(42)

    # Deliberately omit "seat_node" to force real _discover_seat_node path.
    ctrl.turn_chair(off, {"clip_nif": "c.nif"}, renderer=r)

    # Officer iid 42 must be in _coupled (discovery succeeded).
    assert 42 in ctrl._coupled, (
        "_discover_seat_node failed to find seat node from native 'node' key; "
        "officer not coupled (regression of old target_node_name-only lookup)"
    )
    assert ctrl._coupled[42]["seat_node"] == "console seat 01"

    # update() must call set_world_transform (seat_rest == seat_anim -> identity).
    ctrl.update(r)
    assert 42 in r.world_sets, "update() did not apply coupling transform"
    for i, v in enumerate(identity4()):
        assert abs(r.world_sets[42][i] - v) < 1e-6
