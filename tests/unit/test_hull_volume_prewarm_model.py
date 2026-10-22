"""hull_volume.prewarm_for_model: warm a hull from a MODEL handle, before any
render instance exists (warp-tunnel preload).

Since the carve's per-instance field pipeline was removed, what is warmed is
the hull's fill volume (the interior's left-the-ship test), which does not
depend on BC's authored damage resolution, the hull's ray-trace BVH, and (phase
4 §2.2) the hull's structure-part detection, severance's regions."""
import pytest

from engine.appc import hull_volume


class Recorder:
    def __init__(self):
        self.fill_prefetches = []
        self.trace_prewarms = []
        self.structure_prefetches = []

    def prefetch_hull_fill(self, handle):
        self.fill_prefetches.append(handle)

    def prewarm_trace_accel(self, handle):
        self.trace_prewarms.append(handle)

    def prefetch_structure_parts(self, handle):
        self.structure_prefetches.append(handle)


@pytest.fixture
def recorder(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(hull_volume, "_renderer", r)
    return r


def test_prewarm_prefetches_the_fill_volume_and_builds_the_bvh(recorder):
    hull_volume.prewarm_for_model(5)
    assert recorder.fill_prefetches == [5]
    assert recorder.trace_prewarms == [5]


def test_prewarm_starts_structure_part_detection(recorder):
    """Phase 4 §2.2: the warp-tunnel preload starts detection, so a ship
    arriving through it can sever on its first hit."""
    hull_volume.prewarm_for_model(5)
    assert recorder.structure_prefetches == [5]


def test_a_binding_error_propagates(recorder, monkeypatch):
    """The caller (host_loop's warp preload) logs it; swallowing it here
    would hide a stale .so."""
    def boom(handle):
        raise RuntimeError("stale .so")
    monkeypatch.setattr(recorder, "prefetch_hull_fill", boom)
    with pytest.raises(RuntimeError):
        hull_volume.prewarm_for_model(5)
