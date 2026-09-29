"""set_instance_decals through the Python façades (engine.renderer and
engine.host_io), which the Ship Property Viewer calls to preview decal edits
on its ship (spec 2026-09-28-spv-decal-editing-design.md §2.5).

Both forward (iid, decals) unchanged -- a list of load_model-shaped 7-tuples
or None. host_io, like every host_io wrapper, no-ops when headless.
"""
import types


def _recorder():
    calls = []
    return calls, types.SimpleNamespace(
        set_instance_decals=lambda iid, decals: calls.append((iid, decals)))


def test_renderer_forwards_list_and_none(monkeypatch):
    from engine import renderer
    calls, fake = _recorder()
    monkeypatch.setattr(renderer, "_h", fake)
    entry = ("amb saucer:0", (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), 1.0, "m.png")
    renderer.set_instance_decals("iid", [entry])
    renderer.set_instance_decals("iid", None)
    assert calls == [("iid", [entry]), ("iid", None)]


def test_host_io_forwards_list_and_none(monkeypatch):
    from engine import host_io
    calls, fake = _recorder()
    monkeypatch.setattr(host_io, "_h", fake)
    host_io.set_instance_decals(7, [])
    host_io.set_instance_decals(7, None)
    assert calls == [(7, []), (7, None)]


def test_host_io_is_a_no_op_headless(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.set_instance_decals(7, None) is None
