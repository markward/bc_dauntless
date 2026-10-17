import pytest

from engine import bridge_lighting
from engine.bridge_editor import behaviour, lighting_doc as ld, lighting_writer as lw, runtime
from engine.bridge_editor import probe_layers

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
    # Spec §11.4: the spot/area lists are static; an alert change only starts
    # the fade, and tick() pushes the live glow + spot + area colours.
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    io.calls.clear()
    rt.on_alert(2)
    assert names(io) == []
    rt.tick(0.016)
    assert names(io) == ["bridge_quality", "set_bridge_glow", "set_bridge_spot_colours",
                         "set_bridge_area_colours", "set_bridge_layer_values"]


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

        def set_bridge_layer_values(self, *a):
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
    assert ("set_bridge_probe_scales", bridge_lighting.probe_scales()) in io.calls
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
    # SAME population. They are not -- lights.build() already caps the rows
    # at 32 before they ever reach native, so whatever native reports
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

    cap_warnings = [w for w in warnings if "dropped (needs" in w]
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
    d["materials"]["p"] = {"emission": 0, "emission_source": "flat", "modifiers": [
        {"type": "state", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
        {"type": "state", "scope": ["red"], "tint": [1, 0, 0], "level": 0.5},
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2.0, "min": 0.0},
        {"type": "transition", "scope": list(ld.STATES), "seconds": 1.0}]}
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
    assert len(spot) == 10


def test_on_alert_fades_over_its_transition_and_tick_advances_the_clock(proj):
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


def test_a_light_on_a_mapped_mesh_gets_the_map_default(proj):
    """The runtime tells the lights which meshes have an `_emissive` map, so
    an unset emission lights like the map as painted (1), not dark."""
    info = {"source": "/x.nif", "content_hash": HASH, "meshes": [
        {"mesh": 0, "block": 3, "name": "floor", "node_chain": [], "material": 0,
         "textures": ["Map 13.tga"], "maps": {"emissive": True}}]}
    d = ld.empty_doc("x")
    d["materials"]["Map 13"] = {"texture": "map 13.tga", "modifiers": [
        {"type": "state", "scope": ["red"], "tint": [1, 0, 0], "level": 1}]}
    d["textures"] = {"map 13.tga": "Map 13"}
    ld.object_entry(d, 3, "floor")["lights"] = [
        {"position": [0, 0, 0], "direction": [0, 0, -1], "intensity": 10}]
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    io = FakeIO(info=info)
    runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0).attach("iid")
    colours = [c for c in io.calls if c[0] == "set_bridge_spot_colours"]
    assert colours[-1][1] == [(10.0, 10.0, 10.0)]


# ── room light (Mark 2026-10-12) ────────────────────────────────────────────

def _lit_doc():
    d = ld.empty_doc("x")
    ld.object_entry(d, 3, "floor")["lights"] = [
        {"position": [0, 0, 9], "direction": [0, 0, -1], "intensity": 10}]
    return d


def test_a_bridge_with_lights_has_no_room_light_and_its_reflections_follow(proj):
    lw.save(_lit_doc(), proj / "bridge_lighting" / f"{HASH}.json")
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    assert rt.ambient_scale(0) == 0.0 and rt.ambient_scale(2) == 0.0
    assert last(io, "set_bridge_probe_scales") == ("set_bridge_probe_scales", (0.0,) * 5)
    assert names(io)[-1] == "request_bridge_probe_capture"


def test_a_bridge_without_lights_keeps_the_default(proj):
    lw.save(ld.empty_doc("x"), proj / "bridge_lighting" / f"{HASH}.json")
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    assert rt.ambient_scale(0) is None
    assert last(io, "set_bridge_probe_scales") == ("set_bridge_probe_scales",
                                                   bridge_lighting.probe_scales())


def test_an_edited_room_light_recaptures_once(proj):
    lw.save(_lit_doc(), proj / "bridge_lighting" / f"{HASH}.json")
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    d = _lit_doc()
    d["room_light"] = {"green": 0.2, "yellow": 0.1}
    n = names(io).count("request_bridge_probe_capture")
    rt.push(d, {"3:floor": 0})
    assert rt.ambient_scale(0) == 0.2
    assert last(io, "set_bridge_probe_scales") == (
        "set_bridge_probe_scales", (0.2, 0.1, 0.0, 0.0, 0.0))   # a lit bridge: unset levels are 0
    assert names(io).count("request_bridge_probe_capture") == n + 1
    rt.push(d, {"3:floor": 0})                          # unchanged: no recapture
    assert names(io).count("request_bridge_probe_capture") == n + 1


def test_a_push_without_attach_and_no_lights_requests_no_capture():
    """Gate catch (host test): the runtime starts from the default probe
    scales, so a bridge with no lights never asks for a recapture."""
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt._iid = "iid"
    rt.push(ld.empty_doc("x"), {})
    assert "request_bridge_probe_capture" not in names(io)


# ── strips and panels (spec §16.3) ──────────────────────────────────────────

WALL_GEOM = ([(0.0, 50.0, 10.0), (0.0, 50.0, 30.0), (40.0, 50.0, 30.0),
              (0.0, 50.0, 10.0), (40.0, 50.0, 30.0), (40.0, 50.0, 10.0)],
             (0.0, -800.0, 0.0), 800.0)


class GeomIO(FakeIO):
    def __init__(self, geom=WALL_GEOM, **kw):
        super().__init__(**kw)
        self.geom = geom
        self.geom_calls = 0

    def bridge_mesh_geometry(self, iid, mesh):
        self.geom_calls += 1
        return self.geom


def _strip_doc(proj):
    d = ld.empty_doc("x")
    ld.object_entry(d, 3, "floor")["lights"] = [
        {"shape": "strip", "edge": "top", "intensity": 40, "range": 150}]
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    return d


def _last(io, name):
    return [c for c in io.calls if c[0] == name][-1]


def test_attach_clears_then_pushes_the_strip_on_its_top_edge(proj):
    _strip_doc(proj)
    io = GeomIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (20.0, 0.0, 20.0), alert=lambda: 0)
    rt.attach("iid")
    pushes = [c for c in io.calls if c[0] == "set_bridge_area_lights"]
    assert pushes[0] == ("set_bridge_area_lights", [])          # the previous bridge's cleared
    [row] = pushes[-1][1]
    assert row[0] == (20.0, 50.0, 30.0) and row[3] == 150 and row[5] == 40


def test_tick_pushes_live_area_colours(proj):
    _strip_doc(proj)
    io = GeomIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (20.0, 0.0, 20.0), alert=lambda: 0)
    rt.attach("iid")
    rt.tick(0.016)
    assert len(_last(io, "set_bridge_area_colours")[1]) == 1


def test_geometry_is_fetched_once_per_mesh_per_attach(proj):
    _strip_doc(proj)
    io = GeomIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (20.0, 0.0, 20.0), alert=lambda: 0)
    rt.attach("iid")
    for _ in range(5):
        rt.tick(0.016)
    rt.push(rt._doc)
    assert io.geom_calls == 1
    rt.attach("iid")
    assert io.geom_calls == 2


def test_a_strip_with_no_geometry_is_warned_and_not_pushed(proj):
    _strip_doc(proj)
    io = GeomIO(geom=None)
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (20.0, 0.0, 20.0), alert=lambda: 0)
    rt.attach("iid")
    assert _last(io, "set_bridge_area_lights")[1] == []
    warnings = rt.push(rt._doc)
    assert any("no geometry" in w for w in warnings)


def test_frame_for_uses_the_oriented_vertex_sum_not_the_raw_binding_sum(proj):
    # Review ruling item 2: DBridge's winding is mixed, so _frame_for must
    # derive facing from light_shapes.oriented_normal_sum(verts, eye), never
    # from the binding's raw normal_sum. A deliberately WRONG raw sum
    # (pointing +Y) paired with the correct vertices must still produce the
    # same top-edge strip as WALL_GEOM's own (correct) raw sum.
    _strip_doc(proj)
    verts, _wrong_raw_sum, area = WALL_GEOM
    io = GeomIO(geom=(verts, (0.0, 800.0, 0.0), area))
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (20.0, 0.0, 20.0), alert=lambda: 0)
    rt.attach("iid")
    [row] = _last(io, "set_bridge_area_lights")[1]
    assert row[0] == (20.0, 50.0, 30.0) and row[3] == 150 and row[5] == 40
    assert row[1] == (20.0, 0.0, 0.0)          # half_u sign: right-handed, unflipped by the bogus sum


def test_detach_clears_the_area_lights(proj):
    _strip_doc(proj)
    io = GeomIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (20.0, 0.0, 20.0), alert=lambda: 0)
    rt.attach("iid")
    rt.detach()
    assert _last(io, "set_bridge_area_lights") == ("set_bridge_area_lights", [])


# ── per-state probes (spec 2026-10-17 §4.4) ─────────────────────────────────

def test_push_sends_layers_and_glow_captures(proj):
    _glow_doc(proj)    # a red sine on the lit and glowing material
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    (_, states, ids) = last(io, "set_bridge_probe_layers")
    assert states == [2]
    # Each layer's identity (spec §4.4) rides beside its state.
    assert ids == [probe_layers.layer_identity(rt._plan.layers[0])]
    assert last(io, "set_bridge_probe_scales")[1] == (0.0,) * 5     # a lit bridge: no room light
    (iid, rows) = last(io, "set_bridge_glow_captures")[1:]
    assert iid == "iid" and len(rows) == 1
    (mesh, src, caps, layers, rgbs) = rows[0]
    assert layers[2] == 0 and caps[2] == (0.0, 0.0, 0.0)


def test_bridge_without_doc_plans_no_layers_and_five_scales(proj):
    io = FakeIO(info={"source": "", "content_hash": "", "meshes": []})
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    sent = [c for c in io.calls if c[0] == "set_bridge_probe_layers" and c[1]]
    assert sent == []
    assert len(last(io, "set_bridge_probe_scales")[1]) == 5


def test_attach_clears_glow_captures_and_layers(proj):
    io = FakeIO(info={"source": "", "content_hash": "", "meshes": []})
    runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0).attach("iid")
    assert ("set_bridge_glow_captures", None, []) in io.calls
    assert ("set_bridge_probe_layers", [], []) in io.calls


def test_plan_warnings_reach_the_status_line(proj):
    d = ld.empty_doc("x")
    d["materials"]["p"] = {"emission": 1, "modifiers": [
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": p}
        for p in (1.0,)]}
    d["materials"]["q"] = {"emission": 1, "modifiers": [
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 3.0}]}
    d["materials"]["r"] = {"emission": 1, "modifiers": [
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 5.0}]}
    for i, m in enumerate("pqr"):
        ld.object_entry(d, 10 + i, f"o{i}")["material"] = m
    meshes = [{"mesh": i, "block": 10 + i, "name": f"o{i}", "node_chain": [], "material": 0,
               "textures": [], "maps": {"roughness": False, "metalness": False, "normal": False}}
              for i in range(3)]
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    io = FakeIO(info={"source": "/x.nif", "content_hash": HASH, "meshes": meshes})
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")      # FakeIO quality 0 -> cap 2: one wave is dropped
    warnings = rt.push(d, {f"{10 + i}:o{i}": i for i in range(3)})
    assert any("layer cap" in w for w in warnings)


# ── per-frame layer values and quality re-plans (spec 2026-10-17 §4.2, §4.4) ──

class QualityIO(FakeIO):
    def __init__(self, quality, info=INFO):
        super().__init__(info)
        self.quality = quality

    def bridge_quality(self):
        return self.quality


def test_tick_pushes_layer_values(proj):
    _glow_doc(proj)    # one red sine, period 2 s, min 0
    io = QualityIO(1)
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    io.calls.clear()
    rt.tick(0.75)
    expected = behaviour.wave_factor(
        {"shape": "sine", "period_s": 2.0, "phase": 0.0, "min": 0.0}, 0.75) ** 2.2
    (_, vals) = last(io, "set_bridge_layer_values")
    assert len(vals) == 1 and vals[0] == pytest.approx(expected)


def test_layer_values_freeze_under_pause(proj):
    _glow_doc(proj)
    io = QualityIO(1)
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    rt.tick(0.3)
    rt.tick(0.0)
    a = last(io, "set_bridge_layer_values")
    rt.tick(0.0)
    assert last(io, "set_bridge_layer_values") == a


def test_quality_change_replans_layers(proj, monkeypatch):
    d = ld.empty_doc("x")
    for i, p in enumerate((1.0, 3.0, 5.0)):
        d["materials"]["m%d" % i] = {"emission": 1, "modifiers": [
            {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": p}]}
        ld.object_entry(d, 10 + i, "o%d" % i)["material"] = "m%d" % i
    meshes = [{"mesh": i, "block": 10 + i, "name": "o%d" % i, "node_chain": [],
               "material": 0, "textures": [],
               "maps": {"roughness": False, "metalness": False, "normal": False}}
              for i in range(3)]
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    io = QualityIO(1, info={"source": "/x.nif", "content_hash": HASH, "meshes": meshes})
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 0)
    rt.attach("iid")
    rt.tick(0.1)
    assert len(last(io, "set_bridge_layer_values")[1]) == 3
    logged = []
    monkeypatch.setattr(runtime.dev_mode, "log_swallowed",
                        lambda where, e: logged.append(str(e)))
    io.quality = 0
    io.calls.clear()
    rt.tick(0.1)
    assert any("m2" in w and "layer cap" in w for w in logged)
    assert len(last(io, "set_bridge_layer_values")[1]) == 2
    (_, states, ids) = last(io, "set_bridge_probe_layers")
    assert len(states) == 2 and ids == [probe_layers.layer_identity(l)
                                        for l in rt._plan.layers]
