from engine import host_loop


class _Recorder:
    def __init__(self):
        self.calls = []

    def set_viewscreen_comm_source(self, *a):
        self.calls.append(("comm", a))

    def clear_viewscreen_comm_source(self):
        self.calls.append(("clear_comm",))

    def set_viewscreen_scene_source(self, *a):
        self.calls.append(("scene", a))

    def clear_viewscreen_scene_source(self):
        self.calls.append(("clear_scene",))


def _names(rec):
    return [c[0] for c in rec.calls]


def test_comm_wins_and_clears_scene():
    rec = _Recorder()
    comm = (7, (0, 0, 0), (0, 1, 0), (0, 0, 1), 0.5, 1.0, 5000.0)
    # The helper does NOT render comm itself (the loop does, with set bounds); it
    # returns "comm" and guarantees the scene source is cleared.
    result = host_loop._select_viewscreen_source(
        rec, comm_feed=comm, scene_feed=(1, 2, 3, 4, 5, 6))
    assert result == "comm"
    assert "clear_scene" in _names(rec)
    assert "clear_comm" not in _names(rec)
    assert "scene" not in _names(rec)


def test_scene_when_no_comm():
    rec = _Recorder()
    result = host_loop._select_viewscreen_source(
        rec, comm_feed=None,
        scene_feed=((0, 0, 0), (0, 1, 0), (0, 0, 1), 0.4, 1.0, 5000.0))
    assert result == "scene"
    assert "clear_comm" in _names(rec)
    assert "scene" in _names(rec)
    assert "clear_scene" not in _names(rec)


def test_forward_when_neither():
    rec = _Recorder()
    result = host_loop._select_viewscreen_source(rec, comm_feed=None, scene_feed=None)
    assert result == "forward"
    assert "clear_comm" in _names(rec)
    assert "clear_scene" in _names(rec)
    assert "comm" not in _names(rec) and "scene" not in _names(rec)
