"""Bridge editor picking (spec 2026-10-08-bridge-emitters §4)."""
from engine.bridge_editor import picking

POSE = ((0.0, 0.0, 50.0), (0.0, 1.0, 50.0), (0.0, 0.0, 1.0), 0.785398)

INFO = {
    "source": "/abs/Dbridge.NIF",
    "content_hash": "0123456789abcdef",
    "meshes": [
        {"mesh": 0, "block": 3, "name": "floor", "node_chain": ["Scene Root"],
         "textures": [], "material": 0},
        {"mesh": 1, "block": 7, "name": "redalertpanel",
         "node_chain": ["Scene Root", "Red On GlowAlpha"],
         "textures": ["redalertpanel.tga"], "material": 1},
        # Stock DBridge: every shape is unnamed; the owning node names it.
        {"mesh": 2, "block": 11, "name": "",
         "node_chain": ["", "Gamma", "wall side pnls 11"],
         "textures": ["Map 20.tga"], "material": 2},
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


def test_pick_hit_returns_the_full_trace_result():
    hit = ((0, 10, 50), (0, -1, 0), 10.0, 1, 0)
    assert picking.pick_hit(lambda *a: hit, (400, 300), (800, 600), POSE) == hit


def test_pick_hit_miss_is_none():
    assert picking.pick_hit(lambda *a: None, (1, 1), (800, 600), POSE) is None


def test_pick_hit_with_a_degenerate_viewport_is_none():
    assert picking.pick_hit(lambda *a: 1 / 0, (1, 1), (0, 0), POSE) is None


def test_pick_mesh_derives_from_pick_hit():
    seen = {}

    def trace(origin, direction, max_dist, exclude):
        seen.update(exclude=tuple(exclude))
        return ((0, 10, 50), (0, -1, 0), 10.0, 3, 0)

    assert picking.pick_mesh(trace, (400, 300), (800, 600), POSE, exclude=(9,)) == 3
    assert seen["exclude"] == (9,)


def test_pick_forwards_the_exclusion():
    got = []
    picking.pick_mesh(lambda o, d, m, ex: got.append(tuple(ex)) or None,
                      (1, 1), (800, 600), POSE, exclude=(4, 5))
    assert got == [(4, 5)]


def test_identity_for_resolves_block_name_chain_textures_and_hash():
    ident = picking.identity_for(INFO, 1)
    assert ident.key == "7:redalertpanel"
    assert ident.node_chain == ("Scene Root", "Red On GlowAlpha")
    assert ident.textures == ("redalertpanel.tga",)
    assert ident.content_hash == "0123456789abcdef"
    assert ident.display_name == "redalertpanel"


def test_identity_for_an_unnamed_shape_keys_on_the_empty_name_and_displays_its_node():
    ident = picking.identity_for(INFO, 2)
    assert ident.name == ""
    assert ident.key == "11:"
    assert ident.textures == ("Map 20.tga",)
    assert ident.display_name == "(node) wall side pnls 11"


def test_display_name_skips_unnamed_nodes_and_never_comes_back_empty():
    ident = picking.ShapeIdentity(mesh=0, block=1, name="", node_chain=("", ""),
                                  textures=(), content_hash="")
    assert ident.display_name == "(unnamed)"


def test_identity_for_unknown_mesh_or_block_is_none():
    assert picking.identity_for(INFO, 9) is None
    info = {"source": "", "content_hash": "", "meshes": [
        {"mesh": 0, "block": -1, "name": "x", "node_chain": [], "textures": [],
         "material": 0}]}
    assert picking.identity_for(info, 0) is None


def _layered(layers):
    """A pick function over meshes stacked front-to-back along the ray."""
    calls = []

    def pick(exclude):
        calls.append(tuple(exclude))
        return next((m for m in layers if m not in exclude), None)
    return pick, calls


def test_alt_pick_at_a_fresh_spot_returns_the_surface_behind_the_cursor():
    # The current selection (mesh 1) is unrelated to what is under the
    # cursor: the first Alt+click must still step past the FRONT surface.
    cyc = picking.PickCycle()
    pick, calls = _layered([2, 0])
    assert cyc.alt_pick(pick, (100, 100)) == 0
    assert calls == [(), (2,)]


def test_alt_pick_repeated_at_the_same_spot_steps_deeper():
    cyc = picking.PickCycle()
    pick, _ = _layered([2, 0, 5])
    assert cyc.alt_pick(pick, (100, 100)) == 0
    assert cyc.alt_pick(pick, (102, 99)) == 5          # within slop: deeper
    assert cyc.alt_pick(pick, (101, 100)) is None      # nothing further behind


def test_alt_pick_somewhere_else_starts_again_from_the_front():
    cyc = picking.PickCycle()
    pick, _ = _layered([2, 0, 5])
    cyc.alt_pick(pick, (100, 100))
    cyc.alt_pick(pick, (100, 100))
    assert cyc.alt_pick(pick, (300, 100)) == 0
    cyc.reset()
    assert cyc.alt_pick(pick, (300, 100)) == 0


def test_alt_pick_with_nothing_under_the_cursor_is_none():
    cyc = picking.PickCycle()
    pick, calls = _layered([])
    assert cyc.alt_pick(pick, (5, 5)) is None
    assert calls == [()]
