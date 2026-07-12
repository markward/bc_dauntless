from engine.bridge_character_walk import BridgeCharacterWalkController


class _FakeRenderer:
    def __init__(self):
        self._next = 100
        self.loaded = {}          # (iid, path) -> clip_index
        self.walked = []          # (iid, clip_index)
        self.rest_poses = []      # (iid, clip_index, at_start)
        self.idled = []           # (iid, clip_index)
    def load_instance_clip(self, iid, path):
        key = (iid, path)
        if key not in self.loaded:
            self._next += 1
            self.loaded[key] = self._next
        return self.loaded[key]
    def play_instance_walk(self, iid, clip_index):
        self.walked.append((iid, clip_index))
    def set_instance_rest_pose(self, iid, clip_index, at_start):
        self.rest_poses.append((iid, clip_index, at_start))
    def play_instance_idle(self, iid, clip_index):
        self.idled.append((iid, clip_index))
    def load_animation_clips(self, path):
        return [{"duration": 2.0}]     # every walk clip is 2s in tests


class _Char:
    def __init__(self, name="Picard"):
        self._character_name = name
        self._render_instance = None
        self._location = "DBL1M"
        self._hidden = 1
    def GetCharacterName(self):
        return self._character_name
    def SetHidden(self, h):
        self._hidden = 1 if h else 0
    def IsHidden(self):
        return self._hidden
    def SetLocation(self, loc):
        self._location = loc
    def GetLocation(self):
        return self._location


def _controller_with_realize():
    realized = {"next": 500}
    def realize_fn(character):
        realized["next"] += 1
        character._render_instance = realized["next"]
        return character._render_instance
    return BridgeCharacterWalkController(realize_fn=realize_fn), realize_fn


def test_move_realizes_reveals_and_walks(monkeypatch):
    import engine.bridge_character_walk as bcw
    monkeypatch.setattr(bcw, "capture_breathing", lambda ch: None)
    ctrl, _ = _controller_with_realize()
    r = _FakeRenderer()
    ch = _Char()
    done = []
    ctrl.request_move(ch, "db_L1toP_P.nif", "DBGuest1",
                      on_complete=lambda: done.append(True))

    ctrl.update(0.0, renderer=r)                 # drain: realize + reveal + walk
    assert ch._render_instance is not None
    assert ch.IsHidden() == 0                    # revealed
    iid = ch._render_instance
    assert r.walked == [(iid, r.loaded[(iid, "db_L1toP_P.nif")])]
    assert ctrl.is_moving(ch) is True
    assert done == []                            # not complete until settle


def test_move_settles_restations_and_completes(monkeypatch):
    """The controller does NOT set the end location itself -- the SDK builder's own
    trailing AT_SET_LOCATION_NAME does, synchronously, inside the completion callback
    (that is why _settle fires completion BEFORE resolving the idle). Model that
    contract: on_complete re-stations the officer, and capture_breathing resolves
    against whatever GetLocation() says AT THAT MOMENT."""
    import engine.bridge_character_walk as bcw
    ctrl, _ = _controller_with_realize()
    r = _FakeRenderer()
    ch = _Char()                                 # origin: DBL1M (the turbolift)
    done = []

    def on_complete():                           # == the builder's AT_SET_LOCATION_NAME
        ch.SetLocation("DBGuest1")
        done.append(True)

    # The turbolift origin has no breathe clip; the guest-1 destination does. Resolving
    # the idle against a stale origin would therefore yield NO idle at all.
    monkeypatch.setattr(bcw, "capture_breathing",
                        lambda c: {"clip_nif": "DBGuest1Breathe.nif"}
                        if c.GetLocation() == "DBGuest1" else None)

    ctrl.request_move(ch, "db_L1toP_P.nif", None, on_complete=on_complete)
    ctrl.update(0.0, renderer=r)                 # start (duration 2.0)
    iid = ch._render_instance
    walk_clip = r.loaded[(iid, "db_L1toP_P.nif")]

    ctrl.update(1.0, renderer=r)                 # mid-walk: still moving
    assert ctrl.is_moving(ch) is True
    assert done == []
    assert ch.GetLocation() == "DBL1M"           # not re-stationed until completion

    ctrl.update(1.5, renderer=r)                 # elapsed 2.5 >= 2.0: settle
    assert ch.GetLocation() == "DBGuest1"        # re-stationed, via completion
    # rest pose frozen at the walk clip's LAST frame (at_start=False)
    assert (iid, walk_clip, False) in r.rest_poses
    # the idle was resolved AFTER the re-station, so it is the DESTINATION's clip
    assert r.idled == [(iid, r.loaded[(iid, "DBGuest1Breathe.nif")])]
    assert done == [True]                        # completion fired exactly once
    assert ctrl.is_moving(ch) is False


def test_move_completes_inline_when_realize_fails():
    ctrl = BridgeCharacterWalkController(realize_fn=lambda ch: None)  # realize fails
    r = _FakeRenderer()
    ch = _Char()
    done = []
    ctrl.request_move(ch, "db_L1toP_P.nif", "DBGuest1",
                      on_complete=lambda: done.append(True))
    ctrl.update(0.0, renderer=r)
    assert done == [True]                        # never stalls the sequence
    assert r.walked == []


class _FakeRendererClipLoadFails(_FakeRenderer):
    def load_instance_clip(self, iid, path):
        return -1


def test_move_completes_inline_when_clip_load_fails():
    ctrl, _ = _controller_with_realize()          # realize succeeds
    r = _FakeRendererClipLoadFails()               # but clip load fails
    ch = _Char()
    done = []
    ctrl.request_move(ch, "db_L1toP_P.nif", "DBGuest1",
                      on_complete=lambda: done.append(True))
    ctrl.update(0.0, renderer=r)
    assert done == [True]                          # never stalls the sequence
    assert r.walked == []
    assert ctrl.is_moving(ch) is False


def test_update_never_raises_when_realize_raises():
    def realize_fn(character):
        raise RuntimeError("boom")
    ctrl = BridgeCharacterWalkController(realize_fn=realize_fn)
    r = _FakeRenderer()
    ch = _Char()
    done = []
    ctrl.request_move(ch, "db_L1toP_P.nif", "DBGuest1",
                      on_complete=lambda: done.append(True))
    ctrl.update(0.0, renderer=r)                   # must not raise
    assert done == [True]
    assert r.walked == []


def test_reset_clears_active(monkeypatch):
    import engine.bridge_character_walk as bcw
    monkeypatch.setattr(bcw, "capture_breathing", lambda ch: None)
    ctrl, _ = _controller_with_realize()
    r = _FakeRenderer()
    ch = _Char()
    ctrl.request_move(ch, "w.nif", "DBGuest1", on_complete=lambda: None)
    ctrl.update(0.0, renderer=r)
    ctrl.reset()
    assert ctrl.is_moving(ch) is False
