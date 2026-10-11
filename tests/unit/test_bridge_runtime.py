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


def _link(d, block, name, finish):
    """A format-2 material holding `finish`, linked by object <block>:<name>."""
    d["materials"][f"m{block}"] = finish
    ld.object_entry(d, block, name)["material"] = f"m{block}"


def test_attach_pushes_overrides_spots_origin_scales_and_capture(proj):
    d = ld.empty_doc("x")
    _link(d, 3, "floor", {"roughness": 0.25})
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


def test_alert_change_pushes_only_live_values_on_the_next_tick(proj):
    # Spec §11.4: the spot list is static; an alert change only starts the
    # fade, and tick() pushes the live glow + spot colours.
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    io.calls.clear()
    rt.on_alert(2)
    assert names(io) == []
    rt.tick(0.016)
    assert names(io) == ["set_bridge_glow", "set_bridge_spot_colours"]


# ── Obligation (review): neither overrides nor spots are cleared in C++ on a
# Python mission swap -- attach() must push for the NEW bridge even when it
# has nothing, or the previous bridge's state (material overrides, spot
# lights) would keep rendering onto a bridge that declares none of its own. ──

def test_bridge_swap_from_a_bridge_with_data_to_one_without_clears_state(proj):
    d = ld.empty_doc("x")
    _link(d, 3, "floor", {"roughness": 0.25})
    ld.object_entry(d, 5, "bar")["lights"] = [
        {"position": [0, 0, 0], "direction": [0, 0, -1]}]
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
    ld.object_entry(d, 5, "bar")["lights"] = [
        {"position": [0, 0, 0], "direction": [0, 0, -1]}]
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
    _link(d, 5, "bar", {"roughness": 0.1})  # block 5
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
        ld.object_entry(d, i, f"s{i}")["lights"] = [
            {"position": [0, 0, 0], "direction": [0, 0, -1]}]
        matched_meshes.append({"mesh": i, "block": i, "name": f"s{i}", "node_chain": [],
                               "material": 0, "textures": [],
                               "maps": {"roughness": False, "metalness": False, "normal": False}})
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    logged = []
    monkeypatch.setattr(runtime.dev_mode, "log_swallowed",
                        lambda ctx, exc: logged.append((ctx, str(exc))))
    io = FakeIO(info={"source": "/x.nif", "content_hash": HASH, "meshes": matched_meshes})
    runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0).attach("iid")
    too_many = [(ctx, msg) for ctx, msg in logged if ctx == "bridge lighting emitters"]
    assert len(too_many) == 2
    assert all("dropped" in msg for _, msg in too_many)


# ── Review fix round 1, item 4: push() surfaces the renderer's own dropped
# count (non-finite values slipping past schema validation), not just the
# cap-count warnings it already names.

def test_push_reports_a_warning_when_the_renderer_drops_invalid_spots(proj):
    d = ld.empty_doc("x")
    ld.object_entry(d, 5, "bar")["lights"] = [
        {"position": [0, 0, 0], "direction": [0, 0, -1]}]
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
        ld.object_entry(d, i, f"s{i}")["lights"] = [
            {"position": [0, 0, 0], "direction": [0, 0, -1]}]
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
    rt.tick(0.1)
    assert "request_bridge_probe_capture" not in names(io)
    assert "set_bridge_spots" not in names(io)


def test_push_leaves_the_capture_decision_to_the_pass(proj):
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    io.calls.clear()
    d = ld.empty_doc("x")
    _link(d, 3, "floor", {"metalness": 1.0})
    rt.push(d, {"3:floor": 0})
    assert ("set_bridge_material_overrides", "iid", [(0, -1.0, 1.0)]) in io.calls
    assert "request_bridge_probe_capture" not in names(io)


# ── Final-review fix wave, finding 5: attach() clears the previous bridge's
# overrides and spots FIRST, in their own guard, so a failure later in
# attach() (model_identity or the doc load raising) never leaves the old
# bridge's lights live on the new one.

def _attach_a_bridge_with_lights(proj, io):
    d = ld.empty_doc("x")
    ld.object_entry(d, 3, "floor")["lights"] = [
        {"position": [0, 0, 0], "direction": [0, 0, -1]}]
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("A")
    assert any(c[0] == "set_bridge_spots" and c[1] for c in io.calls)   # A has a spot
    io.calls.clear()
    return rt


def test_attach_clears_the_old_bridge_even_when_model_identity_raises(proj):
    class RaisingIdentityIO(FakeIO):
        fail = False

        def model_identity(self, iid):
            if self.fail:
                raise RuntimeError("native boom")
            return self.info

    io = RaisingIdentityIO()
    rt = _attach_a_bridge_with_lights(proj, io)
    io.fail = True
    rt.attach("B")   # must not raise
    assert ("set_bridge_spots", []) in io.calls
    assert ("set_bridge_material_overrides", None, []) in io.calls
    assert io.calls.index(("set_bridge_spots", [])) == 1   # first, before anything else


def test_attach_clears_the_old_bridge_even_when_the_doc_load_raises(proj, monkeypatch):
    io = FakeIO()
    rt = _attach_a_bridge_with_lights(proj, io)

    def boom(*a, **k):
        raise RuntimeError("load boom")

    monkeypatch.setattr(runtime.ld, "load", boom)
    rt.attach("B")   # must not raise
    assert ("set_bridge_spots", []) in io.calls
    assert ("set_bridge_material_overrides", None, []) in io.calls


def test_attach_clear_failing_does_not_stop_the_load(proj):
    class ClearRaisesIO(FakeIO):
        def set_bridge_spots(self, spots):
            if not spots:
                raise RuntimeError("clear boom")
            self.calls.append(("set_bridge_spots", spots))
            return 0

    io = ClearRaisesIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (1.0, 2.0, 3.0), alert=lambda: 0)
    rt.attach("iid")
    assert ("set_bridge_probe_origin", (1.0, 2.0, 3.0)) in io.calls
    assert names(io)[-1] == "request_bridge_probe_capture"


def _glow_doc(proj):
    d = ld.empty_doc("x")
    d["materials"]["p"] = {"fade_s": 1.0, "emission": {"without_map": "flat"}, "modifiers": [
        {"type": "emitter", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
        {"type": "emitter", "scope": ["red"], "tint": [1, 0, 0], "level": 0.5},
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2.0, "min": 0.0}]}
    e = ld.object_entry(d, 3, "floor")
    e["material"] = "p"
    e["lights"] = [{"position": [0, 0, 9], "direction": [0, 0, -1], "intensity": 10}]
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")


def last(io, name):
    return [c for c in io.calls if c[0] == name][-1]


def test_attach_pushes_glow_and_live_spot_colours(proj):
    _glow_doc(proj)
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    assert last(io, "set_bridge_glow") == ("set_bridge_glow", "iid", [(0, 2, (1.0, 1.0, 1.0), 1.0)])
    assert last(io, "set_bridge_spot_colours") == ("set_bridge_spot_colours", [(10.0, 10.0, 10.0)])
    (spot,) = last(io, "set_bridge_spots")[1]
    assert len(spot) == 9


def test_on_alert_fades_over_fade_s_and_tick_advances_the_clock(proj):
    _glow_doc(proj)
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    n_spots = len([c for c in io.calls if c[0] == "set_bridge_spots"])
    rt.on_alert(2)
    assert len([c for c in io.calls if c[0] == "set_bridge_spots"]) == n_spots   # no re-push
    rt.tick(0.5)                               # half way: mix(white 1, red peak... at t=0.5)
    (_, _, rgb, level), = last(io, "set_bridge_glow")[2]
    assert 0.0 < level < 1.0
    rt.tick(10.0)
    (_, _, rgb, level), = last(io, "set_bridge_glow")[2]
    assert rgb[1] == pytest.approx(0.0) and rgb[2] == pytest.approx(0.0)   # settled red


def test_tick_with_zero_dt_keeps_the_same_output(proj):
    _glow_doc(proj)
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 2)
    rt.attach("iid")
    rt.tick(0.3)
    a = last(io, "set_bridge_glow")
    rt.tick(0.0)
    assert last(io, "set_bridge_glow") == a


def test_detach_clears_the_glow_and_tick_after_detach_is_a_no_op(proj):
    _glow_doc(proj)
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    rt.detach()
    assert ("set_bridge_glow", None, []) in io.calls
    n = len(io.calls)
    rt.tick(1.0)
    assert len(io.calls) == n


def test_offline_state_turns_an_unscoped_material_off(proj):
    _glow_doc(proj)
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 3)
    rt.attach("iid")
    (_, _, rgb, level), = last(io, "set_bridge_glow")[2]
    assert level == 0.0 and rgb == (0.0, 0.0, 0.0)


def test_attach_applies_a_texture_material_to_a_mesh_with_no_object(proj):
    """Each TGA is a material (Mark 2026-10-11): production applies the
    texture's material to every unlinked mesh using that texture."""
    info = {"source": "/x.nif", "content_hash": HASH, "meshes": [
        {"mesh": 0, "block": 3, "name": "floor", "node_chain": [], "material": 0,
         "textures": ["Map 13.tga"], "maps": {}}]}
    d = ld.empty_doc("x")
    d["materials"]["Map 13"] = {"metalness": 1}
    d["textures"] = {"map 13.tga": "Map 13"}
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    io = FakeIO(info=info)
    runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0).attach("iid")
    assert ("set_bridge_material_overrides", "iid", [(0, -1.0, 1.0)]) in io.calls


def test_push_reports_a_link_to_another_textures_material(proj):
    info = {"source": "/x.nif", "content_hash": HASH, "meshes": [
        {"mesh": 0, "block": 3, "name": "floor", "node_chain": [], "material": 0,
         "textures": ["Map 13.tga"], "maps": {}}]}
    rt = runtime.BridgeRuntime(io=FakeIO(info=info), eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    d = ld.empty_doc("x")
    d["materials"]["Map 19 2"] = {"texture": "map 19.tga", "roughness": 0}
    ld.object_entry(d, 3, "floor")["material"] = "Map 19 2"
    warnings = rt.push(d, {"3:floor": 0})
    assert any("Map 19 2" in w and "ignored" in w for w in warnings)
