import App
from engine.host_loop import _place_bridge_officers, OFFICER_TRANSFORM


class FakeRenderer:
    def __init__(self):
        self.calls = []          # ordered (op, args) log
        self._next_iid = 100
        self.destroyed = []

    def assemble_officer(self, body, head, body_tex, head_tex, placement, sample):
        self.calls.append(("assemble", body, head, body_tex, head_tex, placement, sample))
        return ("model", body)

    def create_bridge_instance(self, model):
        self.calls.append(("create", model))
        iid = self._next_iid
        self._next_iid += 1
        return iid

    def set_world_transform(self, iid, mat4):
        self.calls.append(("xform", iid, tuple(mat4)))

    def set_instance_animation(self, iid, clip_index, loop, sample_at_start):
        self.calls.append(("anim", iid, clip_index, loop, sample_at_start))

    def destroy_instance(self, iid):
        self.destroyed.append(iid)


class FakeController:
    def __init__(self):
        self.officer_instances = []


def _bridge_with(*characters):
    """Build a fresh 'bridge' set holding the given configured characters."""
    App.g_kSetManager._sets.pop("bridge", None)
    s = App.BridgeSet_Create()                  # registers loud-stub BridgeSet_Create
    App.g_kSetManager.AddSet(s, "bridge")
    for name, loc in characters:
        c = App.CharacterClass_Create(
            "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
            "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
        )
        c.ReplaceBodyAndHead(
            "data/Models/Characters/Bodies/Low/BodyMaleM/FedGold_body.tga",
            "data/Models/Characters/Heads/Low/HeadFelix/felix_head.tga",
        )
        c.SetCharacterName(name)
        c.SetLocation(loc)
        s.AddObjectToSet(c, name)
    return s


def test_places_each_officer_in_order():
    _bridge_with(("Tactical", "DBTactical"))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)

    ops = [c[0] for c in r.calls]
    assert ops == ["assemble", "create", "xform", "anim"]
    assemble = r.calls[0]
    assert assemble[1].endswith("BodyMaleL/BodyMaleL.nif")
    assert assemble[5].endswith("db_stand_t_l.nif")        # placement clip
    assert assemble[6] is False                            # sample_at_start
    assert r.calls[2][2] == tuple(OFFICER_TRANSFORM)       # xform matrix
    assert r.calls[3] == ("anim", 100, 0, False, False)    # iid, clip0, no loop
    assert ctrl.officer_instances == [100]


def test_movement_officer_samples_at_start():
    _bridge_with(("Science", "DBScience"))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    assert r.calls[0][6] is True                           # assemble sample_at_start
    assert r.calls[3][4] is True                           # anim sample_at_start


def test_hidden_officer_skipped():
    _bridge_with(("Mover", "DBL1M"))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    assert r.calls == []
    assert ctrl.officer_instances == []


def test_no_location_skipped():
    _bridge_with(("Idle", ""))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    assert r.calls == []


def test_enumerates_all_including_guest():
    _bridge_with(("Tactical", "DBTactical"),
                 ("Helm", "DBHelm"),
                 ("Guest", "DBCommander"))   # a non-standard slot name
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    assert len(ctrl.officer_instances) == 3


def test_swap_destroys_prior_then_replaces():
    # Load 1: place an officer.
    _bridge_with(("Tactical", "DBTactical"))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    first = list(ctrl.officer_instances)
    assert first == [100]

    # Mission swap: production reset_sdk_globals clears g_kSetManager._sets, so
    # the next load enumerates a FRESH (untagged) character in a new set.
    _bridge_with(("Tactical", "DBTactical"))
    r2 = FakeRenderer()
    _place_bridge_officers(ctrl, r2)
    assert r2.destroyed == first                 # prior instance torn down
    assert [c[0] for c in r2.calls] == ["assemble", "create", "xform", "anim"]
    assert ctrl.officer_instances == [100]       # fresh placement on r2


def test_double_call_same_load_does_not_replace():
    # Within ONE load (no set rebuild), the per-character _render_instance tag
    # prevents double-placement if _place_bridge_officers is called twice.
    _bridge_with(("Tactical", "DBTactical"))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    r2 = FakeRenderer()
    _place_bridge_officers(ctrl, r2)
    assert r2.destroyed == [100]                 # prior torn down
    assert r2.calls == []                        # tagged char not re-placed
    assert ctrl.officer_instances == []
