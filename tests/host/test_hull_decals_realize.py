"""End-to-end at the real `host_loop._ship_decals` call site.

`test_hull_decals_e2e.py` drives `hull_decals.decals_for` directly with a
literal folder, which never exercises `_ship_decals`' own
`Path(nif_path).parent.relative_to(game_root())` computation or either of
its two `realize_set_objects` / `_reconcile_runtime_instances` call sites
(Controller Ruling G item 2). This test drives the real
`realize_set_objects` path -- the simpler of the two -- with a capturing
fake renderer, mirroring the `_CaptureRenderer` pattern in
`tests/unit/test_ship_texture_share_path.py`.
"""
import App
from engine.appc import hull_decals, registry_texture
from engine.appc.sets import SetClass_Create
from tests.helpers.bc_assets import require_game_dir


class _CaptureRenderer:
    """Fake renderer that records the `decals` argument per load_model call."""

    def __init__(self):
        self._next = 1
        self.calls = []

    def load_model(self, path, search, texture_replacements=None, decals=None):
        self.calls.append({"path": path, "decals": decals})
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    def create_instance(self, h):
        iid = self._next
        self._next += 1
        return iid

    def set_world_transform(self, iid, m):
        pass

    def set_rim_eligible(self, iid, b):
        pass

    def set_rim_strength(self, iid, s):
        pass


def test_realize_set_objects_feeds_decals_to_load_model():
    require_game_dir("data/Models/Ships/Ambassador")
    from engine import host_loop as hl

    registry_texture.reset()
    hull_decals.reset()
    App.g_kLODModelManager.Purge()

    sess = hl.MissionSession(mission_name="t")
    r = _CaptureRenderer()
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    ship = App.ShipClass_Create()
    ship.SetName("Ambassador-1")
    ship.SetScript("ships.Ambassador")
    s.AddObjectToSet(ship, "Ambassador-1")

    assert registry_texture.apply_class_default(ship) is True

    try:
        hl.realize_set_objects(sess, s, r)

        assert r.calls, "the Ambassador was never handed to load_model"
        decals = r.calls[0]["decals"]
        assert decals, (
            "expected the Ambassador's default (Zhukov) registry to resolve "
            "at least one decal through the real _ship_decals call site")
        shape, origin, u_axis, v_axis, normal, depth, mask_path = decals[0]
        assert shape == "amb saucer:0"
        assert mask_path.replace("\\", "/").endswith("Masks/Zhukov/top.png")
    finally:
        registry_texture.reset()
        hull_decals.reset()
