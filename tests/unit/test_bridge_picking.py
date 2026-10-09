"""Bridge editor picking (spec 2026-10-08-bridge-emitters §4)."""
from engine.bridge_editor import picking

POSE = ((0.0, 0.0, 50.0), (0.0, 1.0, 50.0), (0.0, 0.0, 1.0), 0.785398)

INFO = {
    "source": "/abs/Dbridge.NIF",
    "content_hash": "0123456789abcdef",
    "meshes": [
        {"mesh": 0, "block": 3, "name": "floor", "node_chain": ["Scene Root"], "material": 0},
        {"mesh": 1, "block": 7, "name": "redalertpanel",
         "node_chain": ["Scene Root", "Red On GlowAlpha"], "material": 1},
    ],
}


def test_pick_traces_the_ray_through_the_cursor():
    seen = {}

    def trace(origin, direction, max_dist, exclude):
        seen.update(origin=origin, direction=direction, max_dist=max_dist,
                    exclude=tuple(exclude))
        return ((0, 10, 50), (0, -1, 0), 10.0, 1, 0)

    assert picking.pick_mesh(trace, (400, 300), (800, 600), POSE) == 1
    assert seen["origin"] == (0.0, 0.0, 50.0)
    dx, dy, dz = seen["direction"]
    assert abs(dx) < 1e-6 and dy > 0.999 and abs(dz) < 1e-6   # screen centre = forward
    assert seen["max_dist"] == picking.MAX_PICK_DIST
    assert seen["exclude"] == ()


def test_pick_miss_is_none():
    assert picking.pick_mesh(lambda *a: None, (1, 1), (800, 600), POSE) is None


def test_pick_with_a_degenerate_viewport_is_none():
    assert picking.pick_mesh(lambda *a: 1 / 0, (1, 1), (0, 0), POSE) is None


def test_pick_forwards_the_exclusion():
    got = []
    picking.pick_mesh(lambda o, d, m, ex: got.append(tuple(ex)) or None,
                      (1, 1), (800, 600), POSE, exclude=(4, 5))
    assert got == [(4, 5)]


def test_identity_for_resolves_block_name_chain_textures_and_hash():
    ident = picking.identity_for(INFO, 1, {7: ["redalertpanel.tga"]})
    assert ident.key == "7:redalertpanel"
    assert ident.node_chain == ("Scene Root", "Red On GlowAlpha")
    assert ident.textures == ("redalertpanel.tga",)
    assert ident.content_hash == "0123456789abcdef"


def test_identity_for_unknown_mesh_or_block_is_none():
    assert picking.identity_for(INFO, 9, {}) is None
    info = {"source": "", "content_hash": "", "meshes": [
        {"mesh": 0, "block": -1, "name": "x", "node_chain": [], "material": 0}]}
    assert picking.identity_for(info, 0, {}) is None


def test_pick_cycle_excludes_previous_picks_at_the_same_spot():
    cyc = picking.PickCycle()
    assert cyc.next_exclusion((100, 100), current_mesh=1) == (1,)
    assert cyc.next_exclusion((101, 100), current_mesh=0) == (1, 0)
    assert cyc.next_exclusion((300, 100), current_mesh=2) == (2,)   # moved: restart
    cyc.reset()
    assert cyc.next_exclusion((300, 100), current_mesh=2) == (2,)


def test_pick_cycle_without_a_current_selection_excludes_nothing():
    assert picking.PickCycle().next_exclusion((5, 5), current_mesh=-1) == ()
