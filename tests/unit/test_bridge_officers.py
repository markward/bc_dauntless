"""Logic-level test for SP3 bridge-officer placement.

Drives engine.bridge_officers.place_officers with a fake host (recording every
call) and fake officers, asserting the skip rules and the visible-officer call
sequence. No GL, no real assets.
"""
from engine.bridge_officers import place_officers


class FakeHost:
    """Records calls; emulates the native binding contract."""

    def __init__(self, placements):
        # placements: location-str -> {"nif": rel, "hidden": bool} or None
        self._placements = placements
        # (body_nif, head_nif, body_tex, head_tex, placement_nif)
        self.assembled = []
        self.created = []            # model handles
        self.transforms_set = []     # (iid, mat4)
        self.animations_set = []     # (iid, clip_index, loop, sample_at_start)
        self.destroyed = []          # iid
        self._next_model = 100
        self._next_iid = 1

    def resolve_placement(self, location):
        return self._placements.get(location)

    def assemble_officer(self, body_nif, head_nif, body_tex, head_tex,
                         placement_nif, sample_at_start=False):
        # SP2: assemble_officer keeps the skeleton and loads the placement clip
        # into model.animations[0]; the per-instance clip selection now happens
        # via set_instance_animation. sample_at_start is forwarded there.
        self.assembled.append(
            (body_nif, head_nif, body_tex, head_tex, placement_nif,
             sample_at_start))
        h = self._next_model
        self._next_model += 1
        return h

    def create_bridge_instance(self, model):
        self.created.append(model)
        iid = self._next_iid
        self._next_iid += 1
        return iid

    def set_world_transform(self, iid, mat4):
        self.transforms_set.append((iid, mat4))

    def set_instance_animation(self, iid, clip_index, loop, sample_at_start):
        # SP2: the renderer plays model.animations[clip_index] on this instance
        # (play-once-and-hold when loop is False) and rebuilds the bone palette
        # each frame until it settles.
        self.animations_set.append((iid, clip_index, loop, sample_at_start))

    def destroy_instance(self, iid):
        self.destroyed.append(iid)

    # The dead SP3 node-walk posing path is gone. If place_officers ever calls
    # these, it's a regression back to that path — fail loudly.
    def sample_placement_pose(self, *a, **k):  # pragma: no cover
        raise AssertionError(
            "sample_placement_pose must not be called (removed in SP2)")


class FakeOfficer:
    def __init__(self, name, location, appearance):
        self._name = name
        self._location = location
        self._appearance = appearance

    def GetCharacterName(self):
        return self._name

    def GetLocation(self):
        return self._location

    def appearance(self):
        return self._appearance


_FULL_APPEARANCE = {
    "body_nif": "Bodies/BodyMaleL/BodyMaleL.nif",
    "head_nif": "Heads/HeadFelix/felix_head.nif",
    "body_tex": "Bodies/BodyMaleM/FedGold_body.tga",
    "head_tex": "Heads/HeadFelix/felix_head.tga",
}

_PLACEMENTS = {
    "DBTactical": {"nif": "data/animations/db_stand_t_l.nif", "hidden": False},
    "DBL1S": {"nif": "data/animations/DB_L1toE_S.nif", "hidden": True},
}


def test_visible_officer_assembles_posed_and_places():
    host = FakeHost(_PLACEMENTS)
    officer = FakeOfficer("Felix", "DBTactical", _FULL_APPEARANCE)

    placed = place_officers([officer], host, data_root="/game")

    # One instance placed.
    assert placed == [1]
    # SP3: assemble_officer got the four appearance paths AND the placement NIF,
    # all joined to the data root (the SDK gives data-root-relative paths; the
    # host opens files relative to CWD, so they must be absolutised). The
    # placement NIF (5th arg) drives the node-pose bake inside assemble_officer.
    assert host.assembled == [(
        "/game/Bodies/BodyMaleL/BodyMaleL.nif",
        "/game/Heads/HeadFelix/felix_head.nif",
        "/game/Bodies/BodyMaleM/FedGold_body.tga",
        "/game/Heads/HeadFelix/felix_head.tga",
        "/game/data/animations/db_stand_t_l.nif",
        False,  # DBTactical is a stand clip -> sample t=end, not start
    )]
    # A bridge instance was created from the assembled model handle.
    assert host.created == [100]
    # World transform applied to the created instance (bridge-identity space).
    assert len(host.transforms_set) == 1
    assert host.transforms_set[0][0] == 1
    # SP2: the officer plays its placement clip (animations[0]) once and holds.
    assert host.animations_set == [(1, 0, False, False)]


def test_place_one_sets_animation():
    """Each placed officer is wired to play its placement clip (clip_index 0,
    play-once-and-hold) with the placement's sample_at_start flag forwarded."""
    host = FakeHost(_PLACEMENTS)
    officer = FakeOfficer("Felix", "DBTactical", _FULL_APPEARANCE)

    place_officers([officer], host, data_root="/game")

    anim = host.animations_set
    assert len(anim) == 1
    iid, clip_index, loop, sample_at_start = anim[0]
    assert iid == 1
    assert clip_index == 0
    assert loop is False
    # DBTactical is a stand clip -> no sample_at_start flag -> False.
    assert sample_at_start is False


def test_place_one_forwards_sample_at_start():
    """A movement-station placement (sample_at_start True) forwards the flag to
    set_instance_animation."""
    placements = {
        "DBL1S": {"nif": "data/animations/DB_L1toE_S.nif", "hidden": False,
                  "sample_at_start": True},
    }
    host = FakeHost(placements)
    officer = FakeOfficer("Mover", "DBL1S", _FULL_APPEARANCE)

    place_officers([officer], host, data_root="/game")

    assert host.animations_set == [(1, 0, False, True)]


def test_hidden_location_is_skipped():
    host = FakeHost(_PLACEMENTS)
    officer = FakeOfficer("Staging", "DBL1S", _FULL_APPEARANCE)

    placed = place_officers([officer], host, data_root="/game")

    assert placed == []
    assert host.assembled == []
    assert host.created == []


def test_unknown_location_is_skipped():
    host = FakeHost(_PLACEMENTS)
    officer = FakeOfficer("Nobody", "Nowhere", _FULL_APPEARANCE)

    placed = place_officers([officer], host, data_root="/game")

    assert placed == []
    assert host.assembled == []


def test_empty_location_is_skipped():
    host = FakeHost(_PLACEMENTS)
    officer = FakeOfficer("Unconfigured", "", _FULL_APPEARANCE)

    placed = place_officers([officer], host, data_root="/game")

    assert placed == []
    assert host.assembled == []


def test_officer_without_body_nif_is_skipped():
    host = FakeHost(_PLACEMENTS)
    ap = dict(_FULL_APPEARANCE)
    ap["body_nif"] = ""
    officer = FakeOfficer("Bodiless", "DBTactical", ap)

    placed = place_officers([officer], host, data_root="/game")

    assert placed == []
    # resolve_placement ran, but assembly did not.
    assert host.assembled == []


def test_one_bad_officer_does_not_abort_the_rest():
    class Exploding(FakeOfficer):
        def appearance(self):
            raise RuntimeError("boom")

    host = FakeHost(_PLACEMENTS)
    bad = Exploding("Bad", "DBTactical", _FULL_APPEARANCE)
    good = FakeOfficer("Good", "DBTactical", _FULL_APPEARANCE)

    placed = place_officers([bad, good], host, data_root="/game")

    # The good officer is still placed despite the bad one raising.
    assert len(placed) == 1
    assert len(host.assembled) == 1


def test_failure_after_create_destroys_the_orphan_instance():
    """If a post-create step raises, the just-created instance must be
    destroyed (no orphaned render instance) and other officers still place."""

    class ExplodingHost(FakeHost):
        def __init__(self, placements, explode_for_model):
            FakeHost.__init__(self, placements)
            self._explode_for_model = explode_for_model

        def set_world_transform(self, iid, mat4):
            # Raise AFTER create_bridge_instance for the targeted officer's
            # model handle, simulating a mid-placement failure.
            if self._created_for_model == self._explode_for_model:
                raise RuntimeError("transform boom")
            FakeHost.set_world_transform(self, iid, mat4)

        def create_bridge_instance(self, model):
            self._created_for_model = model
            return FakeHost.create_bridge_instance(self, model)

    # First officer assembles model 100 -> explode on its transform.
    host = ExplodingHost(_PLACEMENTS, explode_for_model=100)
    bad = FakeOfficer("Bad", "DBTactical", _FULL_APPEARANCE)
    good = FakeOfficer("Good", "DBTactical", _FULL_APPEARANCE)

    placed = place_officers([bad, good], host, data_root="/game")

    # Bad officer's instance (iid 1) was created then destroyed; not tracked.
    assert host.destroyed == [1]
    assert placed == [2]
    # The good officer still placed and was NOT destroyed (only iid 2 got a
    # successful world transform).
    assert len(host.transforms_set) == 1
    assert host.transforms_set[0][0] == 2
