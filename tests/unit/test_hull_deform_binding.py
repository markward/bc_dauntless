"""engine.renderer wrappers for hull deformation must forward to the native
binding when present and no-op / return 0 when it is absent."""
import types

from engine import renderer


class _RecordingHost:
    def __init__(self):
        self.add_calls = []
        self.count_return = 7

    def hull_deform_add(self, iid, world_point, world_normal,
                        world_impact_dir, radius, depth):
        self.add_calls.append(
            (iid, world_point, world_normal, world_impact_dir, radius, depth))

    def hull_deform_crater_count(self, iid):
        return self.count_return


def test_hull_deform_add_forwards_to_binding(monkeypatch):
    host = _RecordingHost()
    monkeypatch.setattr(renderer, "_h", host)
    renderer.hull_deform_add(
        iid="IID", world_point=(1, 2, 3), world_normal=(0, 0, 1),
        world_impact_dir=(0, 0, -1), radius=0.2, depth=0.3)
    assert host.add_calls == [
        ("IID", (1, 2, 3), (0, 0, 1), (0, 0, -1), 0.2, 0.3)]


def test_hull_deform_crater_count_forwards(monkeypatch):
    host = _RecordingHost()
    monkeypatch.setattr(renderer, "_h", host)
    assert renderer.hull_deform_crater_count("IID") == 7


def test_wrappers_noop_when_binding_absent(monkeypatch):
    # A host module without the bindings (e.g. a stale .so) must not raise.
    empty = types.SimpleNamespace()
    monkeypatch.setattr(renderer, "_h", empty)
    renderer.hull_deform_add(
        iid="IID", world_point=(0, 0, 0), world_normal=(0, 0, 1),
        world_impact_dir=(0, 0, -1), radius=0.1, depth=0.1)  # no raise
    assert renderer.hull_deform_crater_count("IID") == 0
