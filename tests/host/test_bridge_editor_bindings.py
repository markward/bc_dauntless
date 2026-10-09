"""Bridge editor bindings (spec 2026-10-08-bridge-emitters §4): they exist,
and their host_io wrappers degrade to None/{} instead of raising when the
host is absent or the id is stale."""
import os

import pytest

from engine import host_io
from tests.helpers import bc_assets


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
    host_io.set_bridge_highlight(None, -1, -1)   # no raise


def test_host_io_decodes_non_utf8_names_instead_of_raising(monkeypatch):
    """The binding hands names over as BYTES (a NIF name is whatever bytes
    the exporter wrote); host_io decodes them with errors="replace", so a
    non-UTF-8 shape/node/texture name can never raise into the host loop."""

    class FakeHost:
        @staticmethod
        def model_identity(iid):
            return {"source": "/x.nif", "content_hash": "ab",
                    "meshes": [{"mesh": 0, "block": 3, "name": b"caf\xe9",
                                "node_chain": [b"Scene Root", b"\xff\xfe"],
                                "textures": [b"Map\xa03.tga"], "material": 0}]}

    monkeypatch.setattr(host_io, "_h", FakeHost)
    m = host_io.model_identity(0)["meshes"][0]
    assert m["name"] == "caf\ufffd"
    assert m["node_chain"] == ["Scene Root", "\ufffd\ufffd"]
    assert m["textures"] == ["Map\ufffd3.tga"]


DBRIDGE_NIF = bc_assets.GAME_ROOT / "data" / "Models" / "Sets" / "DBridge" / "Dbridge.NIF"
DBRIDGE_TEX = bc_assets.GAME_ROOT / "data" / "Models" / "Sets" / "DBridge" / "High"


@pytest.fixture
def dbridge():
    """Headless host with stock DBridge loaded as an interior; yields
    (module, InstanceId)."""
    if not DBRIDGE_NIF.is_file() or not DBRIDGE_TEX.is_dir():
        pytest.skip("BC DBridge asset not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(256, 256, "bridge-editor-binding-tests")
    except RuntimeError as e:
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)
        pytest.skip(f"no GL context: {e}")
    try:
        handle = _dauntless_host.load_model(str(DBRIDGE_NIF), [str(DBRIDGE_TEX)],
                                            interior=True)
        yield _dauntless_host, _dauntless_host.create_bridge_instance(handle)
    finally:
        _dauntless_host.shutdown()
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)


def test_model_identity_on_dbridge_has_str_names_and_built_textures(dbridge, monkeypatch):
    h, iid = dbridge
    monkeypatch.setattr(host_io, "_h", h)
    info = host_io.model_identity(iid)
    assert len(info["content_hash"]) == 16
    meshes = info["meshes"]
    assert meshes
    for m in meshes:
        assert isinstance(m["name"], str)
        assert all(isinstance(n, str) for n in m["node_chain"])
        assert isinstance(m["textures"], list) and len(m["textures"]) <= 1
        assert all(isinstance(t, str) and t for t in m["textures"])
    # Stock DBridge shapes are unnamed and inherit their textures from parent
    # nodes -- the measured blank-readout bug: nif_shapes reported 0 names.
    assert sum(1 for m in meshes if m["textures"]) > len(meshes) // 2


# The enabled path (developer gate on: set, None/stale clear) is tested in C++
# (native/tests/host/bridge_highlight_test.cc): the gate must never have a
# Python-reachable setter, or any script could enable C++ dev paths.

def test_set_bridge_highlight_is_a_noop_without_developer_mode(dbridge):
    h, iid = dbridge
    assert h.developer_mode is False
    assert h.bridge_highlight() == (False, -1, -1)
    h.set_bridge_highlight(iid, 3, 4)
    assert h.bridge_highlight() == (False, -1, -1)


def test_set_bridge_highlight_none_and_stale_never_raise(dbridge):
    h, _iid = dbridge
    h.set_bridge_highlight(None, -1, -1)
    h.set_bridge_highlight(h.InstanceId(), 0, 0)


def test_set_bridge_highlight_none_and_stale_never_raise_headless(host_module):
    # Before init(): no bridge pass exists at all.
    host_module.set_bridge_highlight(None, -1, -1)
    host_module.set_bridge_highlight(host_module.InstanceId(), 0, 0)


def test_no_python_setter_for_the_developer_gate(host_module):
    assert not any("set_developer_mode" in n for n in dir(host_module))


def test_model_identity_meshes_report_maps(monkeypatch):
    from engine import host_io

    class FakeHost:
        @staticmethod
        def instance_translation(iid):
            return None

        @staticmethod
        def model_identity(iid):
            return {"source": b"/x.nif", "content_hash": "ab", "meshes": [
                {"mesh": 0, "block": 3, "name": b"floor", "node_chain": [],
                 "material": 0, "textures": [b"floor.tga"],
                 "maps": {"roughness": True, "metalness": False, "normal": False}}]}

    monkeypatch.setattr(host_io, "_h", FakeHost)
    mesh = host_io.model_identity(0)["meshes"][0]
    assert mesh["maps"] == {"roughness": True, "metalness": False, "normal": False}


# Bridge PBR (plan 2026-10-09-bridge-pbr Task 4): per-shape material
# overrides are production data (NOT developer-gated); the A/B switch is.

@pytest.mark.parametrize("name", ["set_bridge_material_overrides", "set_bridge_pbr_enabled"])
def test_pbr_binding_exists(host_module, name):
    assert hasattr(host_module, name)


def test_material_overrides_with_a_stale_id_never_raise(host_module):
    host_module.set_bridge_material_overrides(host_module.InstanceId(), [(0, 0.5, -1.0)])
    host_module.set_bridge_material_overrides(None, [])


def test_material_overrides_on_a_live_bridge_never_raise(dbridge):
    h, iid = dbridge
    h.set_bridge_material_overrides(iid, [(0, 0.5, -1.0), (3, -1.0, 1.0)])
    h.set_bridge_material_overrides(iid, [])
    h.set_bridge_material_overrides(None, [])
    h.set_bridge_pbr_enabled(False)   # no-op without --developer; never raises


def test_host_io_pbr_wrappers_degrade_headless(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "_h", None)
    host_io.set_bridge_material_overrides(0, [(0, 0.5, -1.0)])
    host_io.set_bridge_pbr_enabled(False)
