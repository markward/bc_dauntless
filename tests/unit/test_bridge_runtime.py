import pytest

from engine.bridge_editor import lighting_doc as ld, lighting_writer as lw, runtime

HASH = "0123456789abcdef"
HASH_B = "fedcba9876543210"
INFO = {"source": "/x.nif", "content_hash": HASH, "meshes": [
    {"mesh": 0, "block": 3, "name": "floor", "node_chain": [], "material": 0,
     "textures": [], "maps": {"roughness": False, "metalness": False, "normal": False}}]}


class FakeIO:
    def __init__(self, info=INFO):
        self.info = info
        self.calls = []

    def model_identity(self, iid):
        return self.info

    def __getattr__(self, name):
        def rec(*a):
            self.calls.append((name,) + a)
            return 0
        return rec


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    return tmp_path


def names(io):
    return [c[0] for c in io.calls]


def test_attach_pushes_overrides_spots_origin_scales_and_capture(proj):
    d = ld.empty_doc("x")
    ld.shape_entry(d, 3, "floor")["material"] = {"roughness": 0.25}
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0.0, 87.0, 50.0), alert=lambda: 0)
    rt.attach("iid")
    assert ("set_bridge_material_overrides", "iid", [(0, 0.25, -1.0)]) in io.calls
    assert ("set_bridge_spots", []) in io.calls
    assert ("set_bridge_probe_origin", (0.0, 87.0, 50.0)) in io.calls
    assert names(io)[-1] == "request_bridge_probe_capture"


def test_attach_without_a_hash_clears_and_does_not_raise(proj):
    io = FakeIO(info={"source": "", "content_hash": "", "meshes": []})
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    assert ("set_bridge_material_overrides", None, []) in io.calls


def test_a_broken_file_is_ignored_not_raised(proj):
    (proj / "bridge_lighting").mkdir()
    (proj / "bridge_lighting" / f"{HASH}.json").write_text("{broken")
    io = FakeIO()
    runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0).attach("iid")
    assert ("set_bridge_material_overrides", "iid", []) in io.calls


def test_alert_change_repushes_spots_only(proj):
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    io.calls.clear()
    rt.on_alert(2)
    assert names(io) == ["set_bridge_spots"]


# ── Obligation (review): neither overrides nor spots are cleared in C++ on a
# Python mission swap -- attach() must push for the NEW bridge even when it
# has nothing, or the previous bridge's state (material overrides, spot
# lights) would keep rendering onto a bridge that declares none of its own. ──

def test_bridge_swap_from_a_bridge_with_data_to_one_without_clears_state(proj):
    d = ld.empty_doc("x")
    ld.shape_entry(d, 3, "floor")["material"] = {"roughness": 0.25}
    ld.shape_entry(d, 5, "bar")["emitter"] = {
        "light": {"position": [0, 0, 0], "direction": [0, 0, -1]}}
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")

    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("A")
    # Sanity: bridge A really did push non-empty state.
    assert ("set_bridge_material_overrides", "A", [(0, 0.25, -1.0)]) in io.calls

    io.info = {"source": "/y.nif", "content_hash": HASH_B, "meshes": []}
    io.calls.clear()
    rt.attach("B")

    assert ("set_bridge_material_overrides", "B", []) in io.calls
    assert ("set_bridge_spots", []) in io.calls
    assert names(io)[-1] == "request_bridge_probe_capture"


def test_detach_clears_and_resets_so_a_later_push_is_inert(proj):
    d = ld.empty_doc("x")
    ld.shape_entry(d, 5, "bar")["emitter"] = {
        "light": {"position": [0, 0, 0], "direction": [0, 0, -1]}}
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")

    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    io.calls.clear()

    rt.detach()
    assert ("set_bridge_material_overrides", None, []) in io.calls
    assert ("set_bridge_spots", []) in io.calls

    io.calls.clear()
    rt.on_alert(2)
    assert io.calls == []


def test_push_never_raises_even_with_a_hostile_io():
    class HostileIO:
        def set_bridge_material_overrides(self, *a):
            raise RuntimeError("native boom")

        def set_bridge_spots(self, *a):
            raise RuntimeError("native boom")

        def request_bridge_probe_capture(self):
            raise RuntimeError("native boom")

        def model_identity(self, iid):
            return INFO

    rt = runtime.BridgeRuntime(io=HostileIO(), eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")   # must not raise
    d = ld.empty_doc("x")
    rt.push(d, {})      # must not raise
    rt.on_alert(1)       # must not raise
    rt.detach()          # must not raise
