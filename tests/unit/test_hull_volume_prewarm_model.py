"""hull_volume.prewarm_for_model: prewarm a hull volume from a MODEL handle,
before any render instance exists (warp-tunnel preload)."""
import pytest

from engine.appc import hull_volume


class FakeShip:
    def __init__(self, resolution):
        self._resolution = resolution

    def GetDamageResolution(self):
        return self._resolution


class Recorder:
    def __init__(self):
        self.calls = []
        self.fill_prefetches = []

    def prefetch_hull_fill(self, handle):
        self.fill_prefetches.append(handle)

    def hull_volume_prewarm_model(self, handle, resolution):
        self.calls.append((handle, resolution))


@pytest.fixture
def recorder(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(hull_volume, "_renderer", r)
    return r


def test_ship_resolution_reaches_the_binding(recorder):
    assert hull_volume.prewarm_for_model(FakeShip(8.0), 5) is True
    assert recorder.calls == [(5, 8.0)]


@pytest.mark.parametrize("res", [0.0, -1.0, None, "abc"])
def test_unset_or_bad_resolution_is_skipped(recorder, res):
    assert hull_volume.prewarm_for_model(FakeShip(res), 5) is False
    assert recorder.calls == []


def test_ship_without_getter_is_skipped(recorder):
    assert hull_volume.prewarm_for_model(object(), 5) is False
    assert recorder.calls == []


def test_binding_error_propagates(recorder, monkeypatch):
    def boom(handle, resolution):
        raise RuntimeError("stale .so")
    monkeypatch.setattr(recorder, "hull_volume_prewarm_model", boom)
    with pytest.raises(RuntimeError):
        hull_volume.prewarm_for_model(FakeShip(8.0), 5)


def test_prewarm_prefetches_the_fill_volume(recorder):
    hull_volume.prewarm_for_model(FakeShip(8.0), 5)
    assert recorder.fill_prefetches == [5]


def test_prefetch_happens_even_without_a_resolution(recorder):
    hull_volume.prewarm_for_model(FakeShip(None), 5)
    assert recorder.fill_prefetches == [5]
