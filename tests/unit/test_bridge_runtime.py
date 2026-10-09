import pytest

from engine import bridge_lighting
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
    # Every method BridgeRuntime can call, all raising: attach() must reach
    # push()'s own guard (not just survive on attach()'s outer try/except),
    # so every native call push() makes is represented here.
    class HostileIO:
        def model_identity(self, iid):
            return INFO

        def set_bridge_probe_origin(self, *a):
            raise RuntimeError("native boom")

        def set_bridge_probe_scales(self, *a):
            raise RuntimeError("native boom")

        def set_bridge_probe_mix(self, *a):
            raise RuntimeError("native boom")

        def set_bridge_material_overrides(self, *a):
            raise RuntimeError("native boom")

        def set_bridge_spots(self, *a):
            raise RuntimeError("native boom")

        def request_bridge_probe_capture(self):
            raise RuntimeError("native boom")

    rt = runtime.BridgeRuntime(io=HostileIO(), eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")   # must not raise
    d = ld.empty_doc("x")
    rt.push(d, {})      # must not raise
    rt.on_alert(1)       # must not raise
    rt.detach()          # must not raise


# ── Review fix round 1, item 2: the no-hash attach path must still push a
# FRESH probe origin/scales and request a capture -- a bridge with no
# content hash must not keep reflecting from whatever bridge attached last.

def test_attach_without_a_hash_still_pushes_fresh_probe_state(proj):
    io = FakeIO(info={"source": "", "content_hash": "", "meshes": []})
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (3.0, 4.0, 5.0), alert=lambda: 0)
    rt.attach("iid")
    assert ("set_bridge_probe_origin", (3.0, 4.0, 5.0)) in io.calls
    green, yellow_red = bridge_lighting.probe_scales()
    assert ("set_bridge_probe_scales", green, yellow_red) in io.calls
    assert names(io)[-1] == "request_bridge_probe_capture"


def test_attach_without_a_hash_does_not_keep_the_previous_bridges_eye(proj):
    d = ld.empty_doc("x")
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    io = FakeIO()
    eyes = [(0.0, 87.0, 50.0)]
    rt = runtime.BridgeRuntime(io=io, eye=lambda: eyes[-1], alert=lambda: 0)
    rt.attach("A")   # has a hash -> pushes eye (0, 87, 50)

    io.info = {"source": "", "content_hash": "", "meshes": []}  # bridge B: no hash
    eyes.append((9.0, 9.0, 9.0))
    io.calls.clear()
    rt.attach("B")

    assert ("set_bridge_probe_origin", (9.0, 9.0, 9.0)) in io.calls
    assert names(io)[-1] == "request_bridge_probe_capture"


# ── Review fix round 1, item 3: bad bridge data is logged to the dev log
# (never raised, never silent under --developer).

def test_broken_file_error_is_logged(proj, monkeypatch):
    (proj / "bridge_lighting").mkdir()
    (proj / "bridge_lighting" / f"{HASH}.json").write_text("{broken")
    logged = []
    monkeypatch.setattr(runtime.dev_mode, "log_swallowed",
                        lambda ctx, exc: logged.append((ctx, str(exc))))
    io = FakeIO()
    runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0).attach("iid")
    assert any(ctx == "bridge lighting doc load" for ctx, _ in logged)


def test_match_shapes_mismatch_warnings_are_logged(proj, monkeypatch):
    d = ld.empty_doc("x")
    ld.shape_entry(d, 5, "bar")["material"] = {"roughness": 0.1}  # block 5
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    logged = []
    monkeypatch.setattr(runtime.dev_mode, "log_swallowed",
                        lambda ctx, exc: logged.append((ctx, str(exc))))
    io = FakeIO()  # INFO's only mesh is block 3 "floor" -- "5:bar" never matches
    runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0).attach("iid")
    matches = [(ctx, msg) for ctx, msg in logged if ctx == "bridge lighting doc match_shapes"]
    assert len(matches) == 1 and "5:bar" in matches[0][1]


def test_more_than_32_spots_warning_is_logged(proj, monkeypatch):
    d = ld.empty_doc("x")
    matched_meshes = []
    for i in range(34):
        ld.shape_entry(d, i, f"s{i}")["emitter"] = {
            "light": {"position": [0, 0, 0], "direction": [0, 0, -1]}}
        matched_meshes.append({"mesh": i, "block": i, "name": f"s{i}", "node_chain": [],
                               "material": 0, "textures": [],
                               "maps": {"roughness": False, "metalness": False, "normal": False}})
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    logged = []
    monkeypatch.setattr(runtime.dev_mode, "log_swallowed",
                        lambda ctx, exc: logged.append((ctx, str(exc))))
    io = FakeIO(info={"source": "/x.nif", "content_hash": HASH, "meshes": matched_meshes})
    runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0).attach("iid")
    too_many = [(ctx, msg) for ctx, msg in logged if ctx == "bridge lighting too many spots"]
    assert len(too_many) == 2
    assert all("dropped" in msg for _, msg in too_many)


# ── Review fix round 1, item 4: push() surfaces the renderer's own dropped
# count (non-finite values slipping past schema validation), not just the
# cap-count warnings it already names.

def test_push_reports_a_warning_when_the_renderer_drops_invalid_spots(proj):
    d = ld.empty_doc("x")
    ld.shape_entry(d, 5, "bar")["emitter"] = {
        "light": {"position": [0, 0, 0], "direction": [0, 0, -1]}}
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")

    class DroppingIO(FakeIO):
        def set_bridge_spots(self, spots):
            self.calls.append(("set_bridge_spots", spots))
            return 3   # native reports 3 of the sent spots as non-finite

    io = DroppingIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    matched = {"5:bar": 0}
    warnings = rt.push(d, matched)
    assert warnings == ["3 bridge light(s) dropped as invalid (non-finite values)"]


def test_push_reports_cap_and_invalid_drops_together_not_subtracted(proj):
    # Round-2 fix: push() previously did `if dropped > len(cap_warnings)`,
    # treating the native dropped-count and the cap-warning count as the
    # SAME population. They are not -- lights.spots() already truncates the
    # list to 32 before it ever reaches native, so whatever native reports
    # dropped can only be non-finite values among the <=32 it was SENT, and
    # must always be reported in addition to the cap warnings, never only
    # when it exceeds them. 34 matched lights -> 2 cap warnings; 1 of the 32
    # SENT spots reported non-finite -> 1 > 2 is False under the old logic,
    # silently losing the real drop.
    d = ld.empty_doc("x")
    matched = {}
    for i in range(34):
        ld.shape_entry(d, i, f"s{i}")["emitter"] = {
            "light": {"position": [0, 0, 0], "direction": [0, 0, -1]}}
        matched[f"{i}:s{i}"] = i

    class DroppingIO(FakeIO):
        def set_bridge_spots(self, spots):
            self.calls.append(("set_bridge_spots", spots))
            return 1   # 1 of the 32 SENT spots was non-finite

    io = DroppingIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")

    warnings = rt.push(d, matched)

    cap_warnings = [w for w in warnings if "more than 32" in w]
    invalid_warnings = [w for w in warnings if "dropped as invalid" in w]
    assert len(cap_warnings) == 2
    assert invalid_warnings == ["1 bridge light(s) dropped as invalid (non-finite values)"]
    assert len(warnings) == 3


# ── Final-review fix wave, finding 1: an alert change (and an identical
# editor re-push) must not recapture the probes. BridgePass dirties them
# itself only when the spots / overrides really change (C++:
# BridgePbrFrame.SettingTheSameSpotsAgainDoesNotDirtyTheProbes,
# ...MaterialOverridesDirtyTheProbesOnlyWhenTheyChange), so neither
# on_alert() nor push() asks for a capture on its own. Only attach() -- a
# bridge load, a new eye -- requests one unconditionally.

def test_alert_changes_with_an_empty_doc_never_request_a_capture(proj):
    io = FakeIO()          # a hashed bridge with NO lighting file: empty doc
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    io.calls.clear()
    rt.on_alert(1)
    rt.on_alert(2)
    assert "request_bridge_probe_capture" not in names(io)
    assert io.calls == [("set_bridge_spots", []), ("set_bridge_spots", [])]


def test_push_leaves_the_capture_decision_to_the_pass(proj):
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    io.calls.clear()
    d = ld.empty_doc("x")
    ld.shape_entry(d, 3, "floor")["material"] = {"metalness": 1.0}
    rt.push(d, {"3:floor": 0})
    assert ("set_bridge_material_overrides", "iid", [(0, -1.0, 1.0)]) in io.calls
    assert "request_bridge_probe_capture" not in names(io)
