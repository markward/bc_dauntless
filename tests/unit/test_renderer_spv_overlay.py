"""renderer.set_spv_overlay_beams / clear_spv_overlay_beams pass through _h
and no-op when the host binding is absent."""
import engine.renderer as renderer


class _FakeHost:
    def __init__(self):
        self.beams = None
        self.cleared = False
    def set_spv_overlay_beams(self, beams): self.beams = beams
    def clear_spv_overlay_beams(self): self.cleared = True


def test_wrappers_pass_through(monkeypatch):
    fake = _FakeHost()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_spv_overlay_beams([{"x": 1}])
    renderer.clear_spv_overlay_beams()
    assert fake.beams == [{"x": 1}]
    assert fake.cleared is True


def test_wrappers_noop_without_binding(monkeypatch):
    class _Bare: pass
    monkeypatch.setattr(renderer, "_h", _Bare())
    # Must not raise when the host lacks the binding (pre-rebuild / headless).
    renderer.set_spv_overlay_beams([{"x": 1}])
    renderer.clear_spv_overlay_beams()
