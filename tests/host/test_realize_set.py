import engine.host_loop as hl


class _FakeRenderer:
    def __init__(self):
        self.loaded = []
        self.created = []
        self.destroyed = []
        self.transforms = {}
        self._next = 1

    def load_model(self, nif_abs, tex_abs):
        self.loaded.append((nif_abs, tex_abs))
        return 100 + len(self.loaded)

    def create_bridge_instance(self, handle):
        iid = ("bridge", self._next); self._next += 1
        self.created.append(("bridge", handle, iid)); return iid

    def create_comm_instance(self, handle):
        iid = ("comm", self._next); self._next += 1
        self.created.append(("comm", handle, iid)); return iid

    def set_world_transform(self, iid, mat): self.transforms[iid] = mat
    def destroy_instance(self, iid): self.destroyed.append(iid)


def _bridge_set_with_geometry(nif="data/Models/Sets/DBridge/DBridge.nif"):
    from engine.appc.bridge_set import BridgeObjectClass, BridgeSet
    s = BridgeSet(); s.SetName("bridge")
    obj = BridgeObjectClass(nif)
    s.AddObjectToSet(obj, "bridge")
    return s, obj


def test_realize_set_loads_bridge_geometry_and_tags_instance():
    s, obj = _bridge_set_with_geometry()

    class _C:
        bridge_instance = None
        nif_to_handle = {}
        comm_instances_by_set = {}
        officer_instances = []
    c = _C(); r = _FakeRenderer()

    hl.realize_set(c, r, s, is_bridge=True)

    assert len(r.created) == 1
    kind, _handle, iid = r.created[0]
    assert kind == "bridge"
    assert obj.render_instance == iid
    assert c.bridge_instance == iid


def test_realize_set_bridge_geometry_is_idempotent():
    s, obj = _bridge_set_with_geometry()

    class _C:
        bridge_instance = None
        nif_to_handle = {}
        comm_instances_by_set = {}
        officer_instances = []
    c = _C(); r = _FakeRenderer()

    hl.realize_set(c, r, s, is_bridge=True)
    hl.realize_set(c, r, s, is_bridge=True)   # same carrier -> no second instance
    assert len(r.created) == 1


def test_realize_set_realizes_bridge_viewscreen():
    from engine.appc.bridge_set import ViewScreenObject
    s, _obj = _bridge_set_with_geometry()
    vs = ViewScreenObject("data/Models/Sets/DBridge/DBridgeViewscreen.nif")
    s.SetViewScreen(vs)

    class _C:
        bridge_instance = None
        viewscreen_instance = None
        viewscreen_obj = None
        nif_to_handle = {}
        comm_instances_by_set = {}
        officer_instances = []
    c = _C()

    class _R(_FakeRenderer):
        def __init__(s2): super().__init__(); s2.vs_model = None
        def set_viewscreen_model(s2, h): s2.vs_model = h
    r = _R()

    hl.realize_set(c, r, s, is_bridge=True)

    assert vs.render_instance is not None
    assert c.viewscreen_instance == vs.render_instance
    assert c.viewscreen_obj is vs
    assert r.vs_model is not None      # registered for the RTT feed
    assert vs.IsOn()                   # defaults on (SDK doesn't SetIsOn on load)


def test_realize_set_viewscreen_is_idempotent():
    from engine.appc.bridge_set import ViewScreenObject
    s, _obj = _bridge_set_with_geometry()
    vs = ViewScreenObject("data/Models/Sets/DBridge/DBridgeViewscreen.nif")
    s.SetViewScreen(vs)

    class _C:
        bridge_instance = None
        viewscreen_instance = None
        viewscreen_obj = None
        nif_to_handle = {}
        comm_instances_by_set = {}
        officer_instances = []
    c = _C()

    class _R(_FakeRenderer):
        def __init__(s2): super().__init__(); s2.vs_model = None
        def set_viewscreen_model(s2, h): s2.vs_model = h
    r = _R()

    hl.realize_set(c, r, s, is_bridge=True)
    first_instance = vs.render_instance
    bridge_created_count = sum(1 for kind, _, _ in r.created if kind == "bridge")

    hl.realize_set(c, r, s, is_bridge=True)   # same ViewScreenObject -> no second instance

    assert vs.render_instance is first_instance
    assert sum(1 for kind, _, _ in r.created if kind == "bridge") == bridge_created_count


def test_realize_set_places_characters_with_pass_matching_set_kind(monkeypatch):
    # A comm set with one character must place it via create_comm_instance and
    # track it under the set name.
    from engine.appc.sets import SetClass
    from engine.appc.characters import CharacterClass

    s = SetClass(); s.SetName("StarbaseSet")
    s.SetBackgroundModel("data/Models/Sets/StarbaseControl/starbasecontrolRM.nif")
    liu = CharacterClass("body.nif", "head.nif"); liu.SetCharacterName("Liu")
    s.AddObjectToSet(liu, "Liu")

    placed = []
    # Stub the heavy skinned-assembly path: realize_set must call a single
    # helper per character; assert it receives create_comm_instance for comm.
    monkeypatch.setattr(hl, "_place_one_character",
                        lambda c, r, ch, set_name, is_bridge, **kw: placed.append((ch.GetCharacterName(), is_bridge)))

    class _C:
        bridge_instance = None
        viewscreen_instance = None
        viewscreen_obj = None
        nif_to_handle = {}
        comm_instances_by_set = {}
    hl.realize_set(_C(), _FakeRenderer(), s, is_bridge=False)
    assert placed == [("Liu", False)]


def test_realize_set_tears_down_prior_officers_on_bridge_re_realize():
    # Mission swap re-realizes the bridge set. The prior load's officer render
    # instances must be destroyed and officer_instances reset before re-placing,
    # otherwise they leak in the renderer and the list grows unbounded.
    s, _obj = _bridge_set_with_geometry()

    class _C:
        bridge_instance = None
        nif_to_handle = {}
        comm_instances_by_set = {}
        officer_instances = None
    c = _C(); r = _FakeRenderer()

    # Simulate a prior load having placed two officers.
    c.officer_instances = [("officer", 1), ("officer", 2)]

    hl.realize_set(c, r, s, is_bridge=True)

    # Both prior officer instances were torn down...
    assert ("officer", 1) in r.destroyed
    assert ("officer", 2) in r.destroyed
    # ...and the tracking list was reset (not the stale, growing list).
    assert ("officer", 1) not in c.officer_instances
    assert ("officer", 2) not in c.officer_instances


def test_realize_all_sets_realizes_bridge_and_comm_sets(monkeypatch):
    import App as _App
    from engine.appc.sets import SetClass
    from engine.appc.bridge_set import BridgeObjectClass

    # Reset + register a bridge set and a comm set in the SetManager.
    _App.g_kSetManager._sets.clear()
    seen = []
    monkeypatch.setattr(hl, "realize_set",
                        lambda c, r, s, *, is_bridge, comm_set_id=None: seen.append((s.GetName(), is_bridge)))
    bridge = SetClass(); bridge.SetName("bridge")
    bridge.AddObjectToSet(BridgeObjectClass("b.nif"), "bridge")
    comm = SetClass(); comm.SetName("StarbaseSet"); comm.SetBackgroundModel("c.nif")
    _App.g_kSetManager.AddSet(bridge, "bridge")
    _App.g_kSetManager.AddSet(comm, "StarbaseSet")

    class _C:
        comm_set_ids = {}
    # Use a renderer that HAS create_comm_instance so the comm set is realized.
    hl.realize_all_sets(_C(), _FakeRenderer())
    assert ("bridge", True) in seen
    assert ("StarbaseSet", False) in seen


def test_realize_all_sets_assigns_stable_comm_set_ids_and_tags_instances(monkeypatch):
    """Each comm set gets a small positive id (sequential from 1), stored in
    controller.comm_set_ids[set_name], and every comm instance for that set is
    tagged via r.set_comm_set_id(iid, set_id). The bridge set gets no id."""
    import App as _App
    from engine.appc.sets import SetClass
    from engine.appc.bridge_set import BridgeObjectClass

    _App.g_kSetManager._sets.clear()
    bridge = SetClass(); bridge.SetName("bridge")
    bridge.AddObjectToSet(BridgeObjectClass("b.nif"), "bridge")
    a = SetClass(); a.SetName("AlphaSet"); a.SetBackgroundModel("a.nif")
    b = SetClass(); b.SetName("BetaSet"); b.SetBackgroundModel("b2.nif")
    _App.g_kSetManager.AddSet(bridge, "bridge")
    _App.g_kSetManager.AddSet(a, "AlphaSet")
    _App.g_kSetManager.AddSet(b, "BetaSet")

    class _R(_FakeRenderer):
        def __init__(s2): super().__init__(); s2.tagged = []
        def set_comm_set_id(s2, iid, set_id): s2.tagged.append((iid, set_id))

    class _C:
        bridge_instance = None
        viewscreen_instance = None
        viewscreen_obj = None
        nif_to_handle = {}
        comm_instances_by_set = {}
        officer_instances = []
        comm_set_ids = {}
    c = _C(); r = _R()

    hl.realize_all_sets(c, r)

    # Comm sets got sequential positive ids; bridge got none.
    assert "bridge" not in c.comm_set_ids
    assert set(c.comm_set_ids.keys()) == {"AlphaSet", "BetaSet"}
    ids = sorted(c.comm_set_ids.values())
    assert ids == [1, 2]
    # Every comm instance is tagged with its set's id.
    for set_name, iids in c.comm_instances_by_set.items():
        sid = c.comm_set_ids[set_name]
        for iid in iids:
            assert (iid, sid) in r.tagged


def test_realize_all_sets_skips_comm_set_when_renderer_lacks_create_comm_instance(monkeypatch):
    """Renderer without create_comm_instance must not reach realize_set for comm
    sets — it would crash with AttributeError (the guard introduced to fix the
    feat/comm-set-viewscreen crash during live E1M1 load).  The bridge set
    is unaffected."""
    import App as _App
    from engine.appc.sets import SetClass
    from engine.appc.bridge_set import BridgeObjectClass

    _App.g_kSetManager._sets.clear()
    seen = []
    monkeypatch.setattr(hl, "realize_set",
                        lambda c, r, s, *, is_bridge: seen.append((s.GetName(), is_bridge)))

    bridge = SetClass(); bridge.SetName("bridge")
    bridge.AddObjectToSet(BridgeObjectClass("b.nif"), "bridge")
    comm = SetClass(); comm.SetName("StarbaseSet"); comm.SetBackgroundModel("c.nif")
    _App.g_kSetManager.AddSet(bridge, "bridge")
    _App.g_kSetManager.AddSet(comm, "StarbaseSet")

    # Renderer WITHOUT create_comm_instance (simulates a build without comm support).
    class _RendererNoComm:
        pass

    hl.realize_all_sets(object(), _RendererNoComm())

    # Bridge realized; comm set skipped — no AttributeError.
    assert ("bridge", True) in seen
    assert ("StarbaseSet", False) not in seen
