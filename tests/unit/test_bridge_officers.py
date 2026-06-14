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
        self.assembled = []          # (body_nif, head_nif, body_tex, head_tex)
        self.created = []            # model handles
        self.poses_sampled = []      # (model, nif_abs)
        self.palettes_set = []       # (iid, palette)
        self.transforms_set = []     # (iid, mat4)
        self.destroyed = []          # iid
        self._next_model = 100
        self._next_iid = 1

    def resolve_placement(self, location):
        return self._placements.get(location)

    def assemble_officer(self, body_nif, head_nif, body_tex, head_tex):
        self.assembled.append((body_nif, head_nif, body_tex, head_tex))
        h = self._next_model
        self._next_model += 1
        return h

    def create_bridge_instance(self, model):
        self.created.append(model)
        iid = self._next_iid
        self._next_iid += 1
        return iid

    def sample_placement_pose(self, model, nif_abs):
        self.poses_sampled.append((model, nif_abs))
        # Return a non-empty single-bone palette (column-major identity).
        return [[1.0, 0.0, 0.0, 0.0,
                 0.0, 1.0, 0.0, 0.0,
                 0.0, 0.0, 1.0, 0.0,
                 0.0, 0.0, 0.0, 1.0]]

    def set_instance_bone_palette(self, iid, palette):
        self.palettes_set.append((iid, palette))

    def set_world_transform(self, iid, mat4):
        self.transforms_set.append((iid, mat4))

    def destroy_instance(self, iid):
        self.destroyed.append(iid)


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


def test_visible_officer_assembles_poses_and_places():
    host = FakeHost(_PLACEMENTS)
    officer = FakeOfficer("Felix", "DBTactical", _FULL_APPEARANCE)

    placed = place_officers([officer], host, data_root="/game")

    # One instance placed.
    assert placed == [1]
    # assemble_officer got the four appearance paths.
    assert host.assembled == [(
        "Bodies/BodyMaleL/BodyMaleL.nif",
        "Heads/HeadFelix/felix_head.nif",
        "Bodies/BodyMaleM/FedGold_body.tga",
        "Heads/HeadFelix/felix_head.tga",
    )]
    # A bridge instance was created from the assembled model handle.
    assert host.created == [100]
    # Pose sampled with the resolved NIF joined to the data root.
    assert host.poses_sampled == [(100, "/game/data/animations/db_stand_t_l.nif")]
    # Palette set on the created instance.
    assert len(host.palettes_set) == 1
    assert host.palettes_set[0][0] == 1
    # World transform applied.
    assert len(host.transforms_set) == 1
    assert host.transforms_set[0][0] == 1


def test_hidden_location_is_skipped():
    host = FakeHost(_PLACEMENTS)
    officer = FakeOfficer("Staging", "DBL1S", _FULL_APPEARANCE)

    placed = place_officers([officer], host, data_root="/game")

    assert placed == []
    assert host.assembled == []
    assert host.created == []
    assert host.poses_sampled == []


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
