"""Runtime re-station: a bridge officer whose SDK location changes must be
re-posed at the new station.

The motivating case is E1M1's "press s to skip introduction". BC's skip path
does NOT walk anyone back to their chair -- E1M1.PutEveryoneInSeats (E1M1.py:
2582/2584) hard-teleports them with bare SetLocation calls:

    g_pSaffi.SetLocation("DBCommander")
    g_pPicard.SetLocation("DBGuest")

CharacterClass.SetLocation is a pure data write, and station placement is
otherwise applied to the renderer exactly once per bridge load
(_realize_character_instance, guarded by _render_instance). The only other
runtime re-pose is the AT_MOVE walk controller. So without this sync the two
officers keep whatever standing pose they were in when the player pressed s.

Verified headlessly 2026-08-21: PutEveryoneInSeats itself runs clean and the
locations DO change (DBL1M -> DBCommander / DBGuest); nothing turned that into
a pose.
"""
import engine.host_loop as HL


class _FakeR:
    def __init__(self):
        self._next = 100
        self.loaded = {}        # (iid, path) -> clip_index
        self.rest_poses = []    # (iid, clip_index, at_start)
        self.idled = []         # (iid, clip_index)

    def load_instance_clip(self, iid, path):
        key = (iid, path)
        if key not in self.loaded:
            self._next += 1
            self.loaded[key] = self._next
        return self.loaded[key]

    def set_instance_rest_pose(self, iid, clip_index, at_start):
        self.rest_poses.append((iid, clip_index, at_start))

    def play_instance_idle(self, iid, clip_index):
        self.idled.append((iid, clip_index))


class _Char:
    def __init__(self, iid, location, placed_location):
        self._render_instance = iid
        self._location = location
        self._placed_location = placed_location

    def GetLocation(self):
        return self._location

    def SetLocation(self, loc):
        self._location = loc

    def GetCharacterName(self):
        return "Test"


_PLACEMENTS = {
    "DBGuest": {"clip_nif": "data/animations/Seated_P.nif",
                "hidden": False, "sample_at_start": True},
    "DBCommander": {"clip_nif": "data/animations/db_stand_c_m.nif",
                    "hidden": False, "sample_at_start": True},
}


def _patch(monkeypatch, chars, *, placements=None, breathing=None):
    monkeypatch.setattr(HL, "_bridge_characters_for_sync",
                        lambda controller: chars)
    import engine.appc.bridge_placement as BP
    monkeypatch.setattr(
        BP, "capture_placement",
        lambda c: (placements if placements is not None
                   else _PLACEMENTS).get(c.GetLocation()))
    monkeypatch.setattr(
        BP, "capture_breathing",
        breathing if breathing is not None
        else (lambda c: {"clip_nif": f"{c.GetLocation()}Breathe.nif"}))
    monkeypatch.setattr(HL, "PROJECT_ROOT", HL.PROJECT_ROOT)


def test_location_change_reposes_at_the_new_station(monkeypatch):
    """The E1M1 skip case: Picard is standing at the guest-1 mark, the skip
    hard-teleports him to the seated guest chair."""
    picard = _Char(11, "DBGuest", placed_location="DBGuest1")
    _patch(monkeypatch, [picard])
    r = _FakeR()

    HL._sync_bridge_character_station(object(), r)

    seat = r.loaded[(11, str(HL.PROJECT_ROOT / "game"
                             / "data/animations/Seated_P.nif"))]
    # Frame 0 of the placement clip is the at-station pose (sample_at_start).
    assert r.rest_poses == [(11, seat, True)]
    # Breathing re-established at the DESTINATION so the seated officer gets the
    # seated idle, not the standing one.
    assert r.idled == [(11, r.loaded[(11, str(HL.PROJECT_ROOT / "game"
                                              / "DBGuestBreathe.nif"))])]
    assert picard._placed_location == "DBGuest"


def test_unchanged_location_touches_the_renderer_not_at_all(monkeypatch):
    """Runs every frame -- a settled officer must cost nothing."""
    saffi = _Char(12, "DBCommander", placed_location="DBCommander")
    _patch(monkeypatch, [saffi])
    r = _FakeR()

    HL._sync_bridge_character_station(object(), r)

    assert r.rest_poses == []
    assert r.idled == []


def test_unrealized_character_is_skipped(monkeypatch):
    """A character with no instance (E1M1 Picard still in the turbolift) has
    nothing to re-pose; the walk controller realizes and places him."""
    waiting = _Char(None, "DBGuest", placed_location="DBL1M")
    _patch(monkeypatch, [waiting])
    r = _FakeR()

    HL._sync_bridge_character_station(object(), r)

    assert r.rest_poses == []
    # The tag must NOT advance -- realizing later must still place him.
    assert waiting._placed_location == "DBL1M"


def test_unplaceable_location_is_not_retried_every_frame(monkeypatch):
    """An unknown location has no SetPosition branch. Accept the change once so
    the SDK's SetPosition is not re-run on every frame forever."""
    stray = _Char(13, "SomewhereElse", placed_location="DBGuest")
    _patch(monkeypatch, [stray])
    r = _FakeR()

    HL._sync_bridge_character_station(object(), r)

    assert r.rest_poses == []
    assert stray._placed_location == "SomewhereElse"


def test_a_raising_character_does_not_stop_the_others(monkeypatch):
    class _Boom(_Char):
        def GetLocation(self):
            raise RuntimeError("boom")

    boom = _Boom(14, "DBGuest", placed_location="DBGuest1")
    picard = _Char(11, "DBGuest", placed_location="DBGuest1")
    _patch(monkeypatch, [boom, picard])
    r = _FakeR()

    HL._sync_bridge_character_station(object(), r)   # must not raise

    assert picard._placed_location == "DBGuest"
