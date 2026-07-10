import engine.renderer as renderer


class _FakeHost:
    def __init__(self):
        self.calls = []

    def set_viewscreen_scene_source(self, eye, target, up, fov_y_rad, near, far):
        self.calls.append(("set", eye, target, up, fov_y_rad, near, far))

    def clear_viewscreen_scene_source(self):
        self.calls.append(("clear",))


def test_scene_source_passthrough(monkeypatch):
    fake = _FakeHost()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_viewscreen_scene_source(
        (1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (0.0, 0.0, 1.0), 0.5, 1.0, 5000.0)
    renderer.clear_viewscreen_scene_source()
    assert fake.calls == [
        ("set", (1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (0.0, 0.0, 1.0), 0.5, 1.0, 5000.0),
        ("clear",),
    ]


def test_scene_source_in_required_bindings():
    assert "set_viewscreen_scene_source" in renderer._REQUIRED_BINDINGS
    assert "clear_viewscreen_scene_source" in renderer._REQUIRED_BINDINGS
