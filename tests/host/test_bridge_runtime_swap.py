"""A runtime LoadBridge.Load(<other config>) must be re-realised by the host.

Until the ship->bridge matrix, g_sBridgeType was always "GalaxyBridge", so
LoadBridge.Load's "set exists, different config" branch never ran under our
engine. These tests drive that branch's OUTPUT (a fresh BridgeObjectClass
carrier + fresh ViewScreenObject under a new config name) and assert the
per-tick reconcile re-realises exactly once and only on a config change.
"""
import engine.host_loop as hl


class _FakeRenderer:
    def __init__(self):
        self.created = []
        self.destroyed = []
        self._next = 1
        self.vs_model = None

    def load_model(self, nif_abs, tex_abs):
        return 100 + self._next

    def create_bridge_instance(self, handle):
        iid = ("bridge", self._next); self._next += 1
        self.created.append(iid); return iid

    def create_comm_instance(self, handle):
        iid = ("comm", self._next); self._next += 1
        self.created.append(iid); return iid

    def set_world_transform(self, iid, mat): pass
    def destroy_instance(self, iid): self.destroyed.append(iid)
    def set_viewscreen_model(self, h): self.vs_model = h


def _controller():
    c = hl.HostController()
    return c


def _install_bridge(config, nif, vs_nif):
    """Build (or rebuild, like LoadBridge.Load does) the 'bridge' set."""
    import App
    from engine.appc.bridge_set import (BridgeObjectClass, BridgeSet,
                                        ViewScreenObject)
    s = App.BridgeSet_Cast(App.g_kSetManager.GetSet("bridge"))
    if s is None:
        s = BridgeSet()
        App.g_kSetManager.AddSet(s, "bridge")
    s.DeleteObjectFromSet("bridge")
    s.DeleteObjectFromSet("viewscreen")
    s.AddObjectToSet(BridgeObjectClass(nif), "bridge")
    s.SetViewScreen(ViewScreenObject(vs_nif))
    s.SetConfig(config)
    return s


def _fresh_sdk():
    from tools import mission_harness
    mission_harness.setup_sdk()
    hl.reset_sdk_globals()


def test_reconcile_is_a_noop_when_config_unchanged(monkeypatch):
    _fresh_sdk()
    c, r = _controller(), _FakeRenderer()
    _install_bridge("GalaxyBridge", "data/Models/Sets/DBridge/DBridge.nif",
                    "data/Models/Sets/DBridge/DBridgeViewScreen.nif")
    hl._realize_bridge(c, r)
    n_created = len(r.created)

    assert hl._reconcile_bridge_config(c, r) is False
    assert len(r.created) == n_created
    assert c.realized_bridge_config == "GalaxyBridge"


def test_reconcile_rerealises_on_config_change(monkeypatch):
    _fresh_sdk()
    c, r = _controller(), _FakeRenderer()
    _install_bridge("GalaxyBridge", "data/Models/Sets/DBridge/DBridge.nif",
                    "data/Models/Sets/DBridge/DBridgeViewScreen.nif")
    hl._realize_bridge(c, r)
    old_bridge = c.bridge_instance
    old_vs = c.viewscreen_instance

    # What LoadBridge.Load("SovereignBridge") leaves behind: same set, new
    # carrier + viewscreen objects, new config name.
    _install_bridge("SovereignBridge", "data/Models/Sets/EBridge/EBridge.nif",
                    "data/Models/Sets/EBridge/EBridgeViewScreen.nif")

    assert hl._reconcile_bridge_config(c, r) is True
    assert c.realized_bridge_config == "SovereignBridge"
    assert old_bridge in r.destroyed
    assert old_vs in r.destroyed
    assert c.bridge_instance is not None and c.bridge_instance != old_bridge
    assert c.viewscreen_instance is not None and c.viewscreen_instance != old_vs
    # Second tick: nothing more to do.
    assert hl._reconcile_bridge_config(c, r) is False


def test_reconcile_without_a_bridge_set_is_a_noop():
    _fresh_sdk()
    c, r = _controller(), _FakeRenderer()
    assert hl._reconcile_bridge_config(c, r) is False
    assert r.created == []


def test_bridge_set_delete_viewscreen_clears_the_slot():
    """LoadBridge.Load deletes 'viewscreen' by name before the new config's
    CreateBridgeModel installs a new one; the BridgeSet slot must not keep
    handing out the deleted object in between."""
    from engine.appc.bridge_set import BridgeSet, ViewScreenObject
    s = BridgeSet(); s.SetName("bridge")
    vs = ViewScreenObject("x.nif")
    s.SetViewScreen(vs)
    s.DeleteObjectFromSet("viewscreen")
    assert s.GetViewScreen() is None


# ── Officer re-placement across a runtime swap (Finding 1) ──────────────────
# LoadBridge.Load's "set exists, different config" branch keeps the SAME
# CharacterClass objects in the set and only re-ConfigureCharacters them (spec
# §2). realize_set's officer teardown destroys the old render instances but,
# without this fix, never clears the characters' _render_instance tag, so
# _place_one_character's idempotency guard (~:6400) skips every one of them
# forever -- an empty bridge after the first runtime swap.

class _OfficerRenderer(_FakeRenderer):
    """_FakeRenderer plus the skinned-officer assembly surface."""
    def __init__(self):
        super().__init__()
        self.visible = {}

    def assemble_officer(self, *a, **k):
        iid = ("model", self._next); self._next += 1; return iid

    def set_instance_rest_pose(self, iid, idx, at_start): pass
    def set_visible(self, iid, vis): self.visible[iid] = vis
    def load_instance_clip(self, iid, nif): return -1
    def play_instance_idle(self, iid, idx): pass


def _stub_placement(monkeypatch):
    import engine.appc.bridge_placement as bp
    monkeypatch.setattr(
        bp, "capture_placement",
        lambda ch: {"clip_nif": "data/animations/MiscEng02.NIF",
                    "hidden": False, "sample_at_start": True})
    monkeypatch.setattr(bp, "capture_breathing", lambda ch: None)


def test_runtime_bridge_swap_re_places_the_officer(monkeypatch):
    _fresh_sdk()
    _stub_placement(monkeypatch)
    from engine.appc.characters import CharacterClass

    c, r = _controller(), _OfficerRenderer()
    s = _install_bridge("GalaxyBridge", "data/Models/Sets/DBridge/DBridge.nif",
                        "data/Models/Sets/DBridge/DBridgeViewScreen.nif")
    officer = CharacterClass("body.nif", "head.nif")
    officer.SetCharacterName("Riker")
    s.AddObjectToSet(officer, "Riker")

    hl._realize_bridge(c, r)
    old_iid = officer._render_instance
    assert old_iid is not None
    assert c.officer_instances == [old_iid]

    # Same set, SAME character object, different config -- exactly what
    # LoadBridge.Load's "set exists, different config" branch leaves behind.
    _install_bridge("SovereignBridge", "data/Models/Sets/EBridge/EBridge.nif",
                    "data/Models/Sets/EBridge/EBridgeViewScreen.nif")

    hl._realize_bridge(c, r)

    assert old_iid in r.destroyed
    new_iid = officer._render_instance
    assert new_iid is not None
    assert new_iid != old_iid
    assert c.officer_instances == [new_iid]
