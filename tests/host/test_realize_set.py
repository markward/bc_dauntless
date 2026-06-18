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
