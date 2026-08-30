import engine.renderer as renderer


def test_viewscreen_wrappers_passthrough(monkeypatch):
    calls = {}

    class FakeH:
        def set_viewscreen_static_source(self, paths):
            calls["source"] = paths
        def set_viewscreen_static(self, on, intensity):
            calls["static"] = (on, intensity)
        def set_viewscreen_brightness(self, b):
            calls["brightness"] = b
        def set_viewscreen_off_texture(self, path):
            calls["off_texture"] = path

    monkeypatch.setattr(renderer, "_h", FakeH())
    renderer.set_viewscreen_static_source(["a.tga", "b.tga"])
    renderer.set_viewscreen_static(True, 0.7)
    renderer.set_viewscreen_brightness(0.5)
    renderer.set_viewscreen_off_texture("/game/data/Icons/ViewscreenLoading.tga")
    assert calls["source"] == ["a.tga", "b.tga"]
    assert calls["static"] == (True, 0.7)
    assert calls["brightness"] == 0.5
    assert calls["off_texture"] == "/game/data/Icons/ViewscreenLoading.tga"
