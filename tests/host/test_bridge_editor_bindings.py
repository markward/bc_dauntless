"""Bridge editor bindings (spec 2026-10-08-bridge-emitters §4): they exist,
and their host_io wrappers degrade to None/{} instead of raising when the
host is absent or the id is stale."""
import pytest


@pytest.fixture
def host_module():
    pytest.importorskip("_dauntless_host")
    import _dauntless_host as h
    return h


@pytest.mark.parametrize("name", [
    "ray_trace_mesh_pick", "model_identity", "set_bridge_highlight",
])
def test_binding_exists(host_module, name):
    assert hasattr(host_module, name)


def test_model_identity_of_a_stale_id_is_none(host_module):
    stale = host_module.InstanceId()
    assert host_module.model_identity(stale) is None


def test_host_io_wrappers_degrade_headless(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.ray_trace_mesh_pick(0, (0, 0, 0), (0, 0, 1), 10.0) is None
    assert host_io.model_identity(0) is None
    assert host_io.nif_shape_textures("/nope.nif") == {}
    host_io.set_bridge_highlight(None, -1, -1)   # no raise


def test_nif_shape_textures_maps_block_to_textures(monkeypatch):
    from engine import host_io

    class FakeHost:
        @staticmethod
        def nif_shapes(abs_path):
            return [{"block": 4, "name": "wall", "textures": ["Map 3.tga"]},
                    {"block": 9, "name": "floor", "textures": []}]

    monkeypatch.setattr(host_io, "_h", FakeHost)
    assert host_io.nif_shape_textures("/x.nif") == {4: ["Map 3.tga"], 9: []}


def test_nif_shape_textures_handles_a_failed_parse(monkeypatch):
    from engine import host_io

    class FakeHost:
        @staticmethod
        def nif_shapes(abs_path):
            return None

    monkeypatch.setattr(host_io, "_h", FakeHost)
    assert host_io.nif_shape_textures("/x.nif") == {}
