"""Bridge editor bindings (spec 2026-10-08-bridge-emitters §4): they exist,
and their host_io wrappers degrade to None/{} instead of raising when the
host is absent or the id is stale."""
import contextlib
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


# Bridge reflection probes (plan 2026-10-09-bridge-pbr Task 6): production,
# NOT developer-gated; no-ops before init (the values are stashed and applied
# when the pass is created).

# The set_bridge_probe_* stash is a C++ static that survives shutdown()/init()
# BY DESIGN, and tests/conftest.py's autouse reset never touches C++ statics.
# Every test that calls a real probe binding therefore restores it.
_PROBE_STASH_DEFAULTS = {"origin": (0.0, 0.0, 0.0), "scales": (1.0,) * 5,
                         "mix": 0.0, "capture_pending": False}


@contextlib.contextmanager
def restored_probe_stash(h):
    """Snapshot the probe stash, run the body, restore it exactly. There is no
    setter that clears a pending request (deliberately: no production clear);
    init() hands a pending request to the new pass and clears it, so an
    init/shutdown cycle on a headless host drains it."""
    before = h.bridge_probe_stash()
    try:
        yield
    finally:
        h.set_bridge_probe_origin(before["origin"])
        h.set_bridge_probe_scales(before["scales"])
        h.set_bridge_probe_mix(before["mix"])
        if h.bridge_probe_stash()["capture_pending"] and not before["capture_pending"]:
            os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
            try:
                h.init(16, 16, "probe-stash-drain")
            except RuntimeError:
                pass   # no GL: nothing renders, the flag cannot matter
            else:
                h.shutdown()
            finally:
                os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)


@pytest.fixture
def probe_stash_guard(host_module):
    """Request this BEFORE `dbridge` in a test's arguments, so it tears down
    after dbridge's shutdown() and restores the stash with no pass alive."""
    with restored_probe_stash(host_module):
        yield


@pytest.mark.parametrize("name", ["set_bridge_probe_origin", "set_bridge_probe_scales",
                                  "set_bridge_probe_mix", "request_bridge_probe_capture"])
def test_probe_binding_exists(host_module, name):
    assert hasattr(host_module, name)


def test_probe_bindings_are_safe_before_init(probe_stash_guard, host_module):
    host_module.set_bridge_probe_origin((0.0, 87.0, 50.0))
    host_module.set_bridge_probe_scales((1.5, 1.0, 1.0, 0.4, 1.0))
    host_module.set_bridge_probe_mix(0.25)
    host_module.request_bridge_probe_capture()


def test_probe_bindings_on_a_live_bridge_never_raise(probe_stash_guard, dbridge):
    h, _iid = dbridge
    h.set_bridge_probe_origin((0.0, 87.0, 50.0))
    h.set_bridge_probe_scales((1.5, 1.0, 1.0, 0.4, 1.0))
    h.set_bridge_probe_mix(1.0)
    h.request_bridge_probe_capture()


def test_host_io_probe_wrappers_degrade_headless(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "_h", None)
    host_io.set_bridge_probe_origin((0.0, 87.0, 50.0))
    host_io.set_bridge_probe_scales((1.5, 1.0, 1.0, 0.4, 1.0))
    host_io.set_bridge_probe_mix(0.25)
    host_io.request_bridge_probe_capture()


def test_host_io_probe_wrappers_forward(monkeypatch):
    from engine import host_io
    calls = []

    class FakeHost:
        @staticmethod
        def set_bridge_probe_origin(p): calls.append(("origin", p))
        @staticmethod
        def set_bridge_probe_scales(sc): calls.append(("scales", sc))
        @staticmethod
        def set_bridge_probe_mix(t): calls.append(("mix", t))
        @staticmethod
        def request_bridge_probe_capture(): calls.append(("capture",))

    monkeypatch.setattr(host_io, "_h", FakeHost)
    host_io.set_bridge_probe_origin((1, 2, 3))
    host_io.set_bridge_probe_scales((1.5, 1, 1, 1, 1))
    host_io.set_bridge_probe_mix(1)
    host_io.request_bridge_probe_capture()
    assert calls == [("origin", (1.0, 2.0, 3.0)), ("scales", [1.5, 1.0, 1.0, 1.0, 1.0]),
                     ("mix", 1.0), ("capture",)]


def test_probe_stash_set_before_init_survives_into_the_pass(probe_stash_guard, host_module):
    """Values set before init() (no pass yet) are applied to the pass init()
    builds -- including a pending capture request and the alert scale."""
    h = host_module
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    h.set_bridge_probe_origin((1.0, 87.0, 50.0))
    h.set_bridge_probe_scales((1.5, 0.75, 0.75, 0.4, 1.0))
    h.set_bridge_probe_mix(0.25)
    h.request_bridge_probe_capture()
    try:
        try:
            h.init(64, 64, "bridge-probe-stash-test")
        except RuntimeError as e:
            pytest.skip(f"no GL context: {e}")
        st = h.bridge_probe_state()
        assert st["origin"] == pytest.approx((1.0, 87.0, 50.0))
        assert st["scales"] == pytest.approx((1.5, 0.75, 0.75, 0.4, 1.0))
        assert "mix" not in st   # the cross-fade runs in the renderer now
        assert st["capture_pending"] is True
    finally:
        h.shutdown()
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)


def test_bridge_probe_state_is_none_before_init(host_module):
    assert host_module.bridge_probe_state() is None


def test_alert_ambient_scale_reaches_the_pass(probe_stash_guard, dbridge):
    h, _iid = dbridge
    h.set_bridge_ambient_scale(1.5)
    assert h.bridge_probe_state()["alert_ambient_scale"] == pytest.approx(1.5)
    h.set_bridge_ambient_scale(1.0)
    assert h.bridge_probe_state()["alert_ambient_scale"] == pytest.approx(1.0)


def test_restored_probe_stash_undoes_every_probe_binding(host_module):
    """The guard itself: whatever a probe test sets -- including a pending
    request made with no pass -- is back as it was afterwards."""
    h = host_module
    before = h.bridge_probe_stash()
    with restored_probe_stash(h):
        h.set_bridge_probe_origin((3.0, 87.0, 50.0))
        h.set_bridge_probe_scales((2.0, 0.5, 0.5, 0.5, 0.5))
        h.set_bridge_probe_mix(0.75)
        h.request_bridge_probe_capture()
        assert h.bridge_probe_stash()["capture_pending"] is True
    after = h.bridge_probe_stash()
    assert after["origin"] == pytest.approx(before["origin"])
    assert after["scales"] == pytest.approx(before["scales"])
    assert after["mix"] == pytest.approx(before["mix"])
    assert after["capture_pending"] == before["capture_pending"]


def test_probe_stash_is_at_defaults(host_module):
    """Order-independent tripwire: every probe test in the process restores
    the stash, so whenever this runs it reads the defaults. A future probe
    test that forgets probe_stash_guard leaves it dirty and fails this."""
    st = host_module.bridge_probe_stash()
    assert st["origin"] == pytest.approx(_PROBE_STASH_DEFAULTS["origin"])
    assert st["scales"] == pytest.approx(_PROBE_STASH_DEFAULTS["scales"])
    assert st["mix"] == pytest.approx(_PROBE_STASH_DEFAULTS["mix"])
    assert st["capture_pending"] is False


# Bridge static spot lights (plan 2026-10-09-bridge-pbr Task 7): production,
# NOT developer-gated; returns the dropped count, never raises. Setting spots
# moves the probe signatures the capture queue compares against (spec
# 2026-10-17 §4.7), so the binding needs no separate request (and touches no
# probe stash). Nothing is queued before the first capture request.

_SPOT = ((0.0, 0.0, 50.0), (0.0, 0.0, -1.0), 30.0, 60.0, 120.0, (1.0, 1.0, 1.0), 2000.0)


def test_set_bridge_spots_returns_dropped_count(host_module):
    spot = ((0.0, 0.0, 50.0), (0.0, 0.0, -1.0), 30.0, 60.0, 120.0, (1.0, 1.0, 1.0), 2000.0)
    assert host_module.set_bridge_spots([spot]) == 0


def test_set_bridge_spots_counts_drops_and_takes_empty_before_init(host_module):
    assert host_module.set_bridge_spots([_SPOT] * 35) == 3
    assert host_module.set_bridge_spots([]) == 0


def test_set_bridge_spots_degenerate_values_never_raise(host_module):
    zero_dir = ((0.0, 0.0, 50.0), (0.0, 0.0, 0.0), 60.0, 30.0, 0.0, (1.0, 1.0, 1.0), 0.0)
    assert host_module.set_bridge_spots([zero_dir]) == 0


def test_set_bridge_spots_on_a_live_bridge_dirties_the_probes(probe_stash_guard, dbridge):
    h, _iid = dbridge
    before = h.bridge_probe_signatures()
    assert h.set_bridge_spots([_SPOT] * 33) == 1
    after = h.bridge_probe_signatures()
    assert len(after) == len(before) >= 5
    assert all(a != b for a, b in zip(after, before))   # every base reads the spots
    # No request yet: nothing is queued, so nothing is pending.
    assert h.bridge_probe_state()["capture_pending"] is False
    h.request_bridge_probe_capture()
    assert h.bridge_probe_state()["capture_pending"] is True


def test_host_io_set_bridge_spots_is_zero_headless(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.set_bridge_spots([_SPOT]) == 0


def test_host_io_set_bridge_spots_forwards(monkeypatch):
    from engine import host_io
    calls = []

    class FakeHost:
        @staticmethod
        def set_bridge_spots(spots):
            calls.append(spots)
            return 7

    monkeypatch.setattr(host_io, "_h", FakeHost)
    assert host_io.set_bridge_spots([((1, 2, 3), (0, 0, -1), 20, 30, 100, (1, 0.5, 0), 2000)]) == 7
    assert calls == [[((1.0, 2.0, 3.0), (0.0, 0.0, -1.0), 20.0, 30.0, 100.0,
                       (1.0, 0.5, 0.0), 2000.0)]]


def test_set_bridge_spots_drops_and_counts_non_finite_lights(host_module):
    nan, inf = float("nan"), float("inf")
    bad_pos = ((nan, 0.0, 50.0), (0.0, 0.0, -1.0), 30.0, 60.0, 120.0, (1.0, 1.0, 1.0), 2000.0)
    bad_k = ((0.0, 0.0, 50.0), (0.0, 0.0, -1.0), 30.0, 60.0, 120.0, (1.0, 1.0, 1.0), inf)
    assert host_module.set_bridge_spots([bad_pos, _SPOT, bad_k]) == 2
    # Invalid lights count before the cap: 32 good + 1 bad drops only the bad one.
    assert host_module.set_bridge_spots([_SPOT] * 32 + [bad_pos]) == 1


def test_set_bridge_spots_drops_non_finite_on_a_live_bridge(probe_stash_guard, dbridge):
    h, _iid = dbridge
    nan = float("nan")
    bad_range = ((0.0, 0.0, 50.0), (0.0, 0.0, -1.0), 30.0, 60.0, nan, (1.0, 1.0, 1.0), 2000.0)
    bad_dir = ((0.0, 0.0, 50.0), (nan, 0.0, -1.0), 30.0, 60.0, 120.0, (1.0, 1.0, 1.0), 2000.0)
    bad_angle = ((0.0, 0.0, 50.0), (0.0, 0.0, -1.0), nan, 60.0, 120.0, (1.0, 1.0, 1.0), 2000.0)
    bad_rgb = ((0.0, 0.0, 50.0), (0.0, 0.0, -1.0), 30.0, 60.0, 120.0, (1.0, nan, 1.0), 2000.0)
    assert h.set_bridge_spots([bad_range, bad_dir, bad_angle, bad_rgb, _SPOT]) == 4


# Final-review fix wave, finding 1: an alert change re-pushes the spots on
# every level change -- with no lighting file, an EMPTY list over an empty
# one. That must not recapture the probes (~14 ms for no visible change).
# BridgePass dirties only when the sanitised list (or override set) differs.

def test_identical_spot_and_override_pushes_do_not_dirty_the_probes(probe_stash_guard, dbridge):
    h, iid = dbridge
    before = h.bridge_probe_signatures()
    assert h.bridge_probe_state()["capture_pending"] is False
    assert h.set_bridge_spots([]) == 0
    h.set_bridge_material_overrides(iid, [])
    assert h.bridge_probe_signatures() == before
    assert h.bridge_probe_state()["capture_pending"] is False


def test_runtime_alert_changes_with_no_file_never_request_a_capture(
        probe_stash_guard, dbridge, monkeypatch):
    from engine.bridge_editor import lighting_doc as ld, runtime
    h, iid = dbridge
    monkeypatch.setattr(host_io, "_h", h)
    rt = runtime.BridgeRuntime(io=host_io, eye=lambda: (0.0, 0.0, 0.0), alert=lambda: 0)
    # The state attach() leaves behind for a bridge with no file, minus the
    # load-time capture request attach() makes on purpose.
    rt._iid = iid
    rt.push(ld.empty_doc("x"), {})
    assert h.bridge_probe_state()["capture_pending"] is False
    rt.on_alert(1)
    rt.on_alert(2)
    rt.on_alert(0)
    assert h.bridge_probe_state()["capture_pending"] is False


# Task 17: emissive sibling maps pick their variant by the player's alert
# level, pushed every frame (host_loop) through set_bridge_alert_level. Like
# the ambient scale it is per-frame state that init()/shutdown() reset.

def test_alert_level_binding_exists(host_module):
    assert hasattr(host_module, "set_bridge_alert_level")


def test_alert_level_reaches_the_pass(dbridge):
    h, _iid = dbridge
    assert h.bridge_probe_state()["alert_level"] == 0
    h.set_bridge_alert_level(2)
    assert h.bridge_probe_state()["alert_level"] == 2
    h.set_bridge_alert_level(1)
    assert h.bridge_probe_state()["alert_level"] == 1
    h.set_bridge_alert_level(0)


def test_alert_level_is_per_frame_state_reset_by_init(host_module):
    """Like the ambient scale, the level is per-frame state: init() (and
    shutdown()) reset it to green via reset_frame_state(); host_loop re-pushes
    it on the first frame."""
    h = host_module
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    h.set_bridge_alert_level(2)
    try:
        try:
            h.init(64, 64, "bridge-alert-level-test")
        except RuntimeError as e:
            pytest.skip(f"no GL context: {e}")
        assert h.bridge_probe_state()["alert_level"] == 0
        h.set_bridge_alert_level(2)
        assert h.bridge_probe_state()["alert_level"] == 2
    finally:
        h.shutdown()
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)


def test_host_io_alert_level_degrades_headless_and_forwards(monkeypatch):
    calls = []
    monkeypatch.setattr(host_io, "_h", None)
    host_io.set_bridge_alert_level(2)          # no raise

    class FakeHost:
        @staticmethod
        def set_bridge_alert_level(level): calls.append(level)

    monkeypatch.setattr(host_io, "_h", FakeHost)
    host_io.set_bridge_alert_level(2.0)
    host_io.set_bridge_alert_level(None)       # unknown -> green
    assert calls == [2, 0]


_Z = (0.0, 0.0, 0.0)
_CAP = ([(1.0, 1.0, 1.0)] + [_Z] * 4, [-1, -1, 0, -1, -1], [_Z, _Z, (0.5, 0.0, 0.0), _Z, _Z])


def _nan_cap():
    return ([(float("nan"), 0.0, 0.0)] + [_Z] * 4, [-1] * 5, [_Z] * 5)


def test_set_bridge_spots_takes_capture_colours(host_module):
    spot = ((0.0, 0.0, 50.0), (0.0, 0.0, -1.0), 30.0, 60.0, 100.0, (1.0, 1.0, 1.0), 10.0)
    assert host_module.set_bridge_spots([spot], [_CAP]) == 0
    assert host_module.set_bridge_spots([spot], [_nan_cap()]) == 1
    assert host_module.set_bridge_spots([spot], []) == 0          # mismatch: ignored
    assert host_module.set_bridge_spots([]) == 0


def test_set_bridge_spot_colours_and_glow_never_raise(host_module):
    host_module.set_bridge_spot_colours([(1.0, 2.0, 3.0), (float("inf"), 0.0, 0.0)])
    host_module.set_bridge_spot_colours([])
    host_module.set_bridge_glow(None, [])
    host_module.set_bridge_glow(0xFFFFFFFF, [(0, 2, (1.0, 1.0, 1.0), 1.0)])   # stale id


def test_host_io_bridge_glow_wrappers_are_headless_safe(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.set_bridge_spots([((0, 0, 0), (0, 0, -1), 30, 60, 100, (1, 1, 1), 1,
                                      [(1, 1, 1)] * 5, [-1] * 5, [(0, 0, 0)] * 5)]) == 0
    host_io.set_bridge_spot_colours([(1, 1, 1)])
    host_io.set_bridge_glow(None, [(0, 2, (1, 1, 1), 1)])


def test_host_io_set_bridge_area_lights_passes_joins_only_when_any_are_set(monkeypatch):
    """Review item 3 (Important): host_io.set_bridge_area_lights splits the
    9th element (join bits, spec §16.8) off the row tuple into a `joins=`
    kwarg aligned with the rows -- but only when at least one row carries a
    nonzero bit; an all-zero strip (or a plain spot-free call) must pass no
    `joins` kwarg at all, matching the C++ default."""
    from engine import host_io
    calls = []

    class H:
        @staticmethod
        def set_bridge_area_lights(rows, captures=None, joins=None):
            calls.append((rows, captures, joins))
            return 0

    monkeypatch.setattr(host_io, "_h", H)

    def area(joins):
        return ((0.0, 0.0, 50.0), (5.0, 0.0, 0.0), (0.0, -5.0, 0.0), 120.0,
                (1.0, 1.0, 1.0), 4.0, [(1.0, 1.0, 1.0)] * 5, [-1] * 5, [(0.0, 0.0, 0.0)] * 5,
                joins)

    host_io.set_bridge_area_lights([area(2), area(1)])
    rows, caps, joins = calls[-1]
    assert joins == [2, 1]
    assert len(rows[0]) == 6                          # joins split off, not left in the row
    assert caps == [([(1.0, 1.0, 1.0)] * 5, [-1] * 5, [(0.0, 0.0, 0.0)] * 5)] * 2

    host_io.set_bridge_area_lights([area(0), area(0)])
    _rows, _caps, joins = calls[-1]
    assert joins is None


def test_host_io_set_bridge_spots_splits_captures(monkeypatch):
    from engine import host_io
    calls = []

    class H:
        @staticmethod
        def set_bridge_spots(rows, captures=None):
            calls.append((rows, captures))
            return 0

    monkeypatch.setattr(host_io, "_h", H)
    host_io.set_bridge_spots([((0, 0, 0), (0, 0, -1), 30, 60, 100, (1, 1, 1), 5,
                               [(1, 1, 1)] + [(0, 0, 0)] * 4, [-1, -1, 0, -1, -1],
                               [(0, 0, 0)] * 2 + [(0.5, 0, 0)] + [(0, 0, 0)] * 2)])
    rows, caps = calls[-1]
    assert rows == [((0.0, 0.0, 0.0), (0.0, 0.0, -1.0), 30.0, 60.0, 100.0, (1.0, 1.0, 1.0), 5.0)]
    assert caps == [([(1.0, 1.0, 1.0)] + [(0.0, 0.0, 0.0)] * 4, [-1, -1, 0, -1, -1],
                     [(0.0, 0.0, 0.0)] * 2 + [(0.5, 0.0, 0.0)] + [(0.0, 0.0, 0.0)] * 2)]
    host_io.set_bridge_spots([((0, 0, 0), (0, 0, -1), 30, 60, 100, (1, 1, 1), 5)])
    assert calls[-1][1] is None


# Area lights + mesh geometry (spec 2026-10-12-bridge-area-lights §16.3).

_AREA = ((0.0, 0.0, 50.0), (5.0, 0.0, 0.0), (0.0, -5.0, 0.0), 120.0, (1.0, 1.0, 1.0), 4.0)


@pytest.mark.parametrize("name", [
    "set_bridge_area_lights", "set_bridge_area_colours", "bridge_mesh_geometry"])
def test_area_binding_exists(host_module, name):
    assert hasattr(host_module, name)


def test_set_bridge_area_lights_counts_drops_and_takes_empty_before_init(host_module):
    assert host_module.set_bridge_area_lights([_AREA]) == 0
    assert host_module.set_bridge_area_lights([_AREA] * 35) == 3
    assert host_module.set_bridge_area_lights([]) == 0


def test_set_bridge_area_lights_accepts_joins_aligned_with_rows(host_module):
    """Review item 3 (Important): the `joins` kwarg (spec §16.8) was wired
    into the binding but never exercised by a test. A wrong length or a
    non-int entry must be ignored (no joins applied) without raising --
    same dropped count as not passing it at all."""
    base = host_module.set_bridge_area_lights([_AREA, _AREA])
    assert host_module.set_bridge_area_lights([_AREA, _AREA], joins=[2, 1]) == base
    assert host_module.set_bridge_area_lights([_AREA, _AREA], joins=[2]) == base       # wrong length
    assert host_module.set_bridge_area_lights([_AREA, _AREA], joins=["x", "y"]) == base  # non-int


def test_a_zero_size_or_non_finite_area_light_is_dropped(host_module):
    flat = ((0.0, 0.0, 50.0), (5.0, 0.0, 0.0), (0.0, 0.0, 0.0), 120.0, (1.0, 1.0, 1.0), 4.0)
    nan = ((0.0, 0.0, float("nan")), (5.0, 0.0, 0.0), (0.0, -5.0, 0.0), 120.0,
           (1.0, 1.0, 1.0), 4.0)
    no_range = ((0.0, 0.0, 50.0), (5.0, 0.0, 0.0), (0.0, -5.0, 0.0), 0.0, (1.0, 1.0, 1.0), 4.0)
    assert host_module.set_bridge_area_lights([flat, nan, no_range, _AREA]) == 3


def test_set_bridge_area_lights_on_a_live_bridge_dirties_the_probes(probe_stash_guard, dbridge):
    h, _iid = dbridge
    before = h.bridge_probe_signatures()
    assert h.set_bridge_area_lights([_AREA]) == 0
    lit = h.bridge_probe_signatures()
    assert all(a != b for a, b in zip(lit, before))
    h.set_bridge_area_colours([(2.0, 2.0, 2.0)])          # never raises...
    assert h.bridge_probe_signatures() == lit             # ...nor moves a signature
    assert h.bridge_probe_state()["capture_pending"] is False   # no request yet


def test_mesh_geometry_on_dbridge(dbridge, monkeypatch):
    h, iid = dbridge
    monkeypatch.setattr(host_io, "_h", h)
    verts, normal_sum, area = host_io.bridge_mesh_geometry(iid, 0)
    assert len(verts) >= 3 and len(verts) % 3 == 0 and area > 0
    assert len(normal_sum) == 3
    assert host_io.bridge_mesh_geometry(iid, 10 ** 6) is None


def test_mesh_geometry_of_a_stale_id_is_none(host_module, monkeypatch):
    monkeypatch.setattr(host_io, "_h", host_module)
    assert host_io.bridge_mesh_geometry(host_module.InstanceId(), 0) is None


def test_area_wrappers_degrade_headless(monkeypatch):
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.set_bridge_area_lights([_AREA]) == 0
    assert host_io.set_bridge_area_colours([(1.0, 1.0, 1.0)]) is None
    assert host_io.bridge_mesh_geometry(object(), 0) is None


def test_a_click_under_a_map_3_alcove_lip_snaps_to_the_curved_lip(dbridge, monkeypatch):
    """Spec §16.8: DBridge's Map 3 left wall (block 652) holds three alcoves
    in one mesh. A click under an alcove's top lip snaps to the curved lip
    run (measured 2026-10-12: 116 units, y -37..79, z 88.7..89.6; after the
    round-8 rebuild of block 652, mirrored from 663, measured 2026-10-17:
    87.8 units in 3 segments, y -36..52, z 89.05..89.56)."""
    from engine.bridge_editor import edge_snap, light_shapes as ls
    h, iid = dbridge
    monkeypatch.setattr(host_io, "_h", h)
    info = host_io.model_identity(iid)
    [mesh] = [m["mesh"] for m in info["meshes"] if m["block"] == 652]
    verts, _n, area = host_io.bridge_mesh_geometry(iid, mesh)
    eye = (0.0, 0.0, 50.0)
    fr = ls.frame(verts, ls.oriented_normal_sum(verts, eye), area, eye)
    pts, tris, normals = edge_snap._welded(fr.vertices, eye)
    target = (-170.5, 28.9, 88.6)              # just under the lip, on the wall
    centroids = [tuple(sum(pts[i][k] for i in t) / 3.0 for k in range(3)) for t in tris]
    anchor_index = min(range(len(centroids)),
                       key=lambda i: sum((centroids[i][k] - target[k]) ** 2 for k in range(3)))
    anchor = centroids[anchor_index]
    s = edge_snap.snap(fr, anchor)
    assert s is not None
    length = sum(ls._len(ls._sub(b, a)) for a, b in zip(s.polyline, s.polyline[1:]))
    assert length > 80 and 2 <= len(s.polyline) - 1 <= edge_snap.MAX_SEGMENTS
    assert all(88.0 < p[2] < 90.5 for p in s.polyline)
    # Review item 1 (Critical): the clicked triangle's own (eye-oriented)
    # normal must be the one the snap reports -- the bug this regresses let
    # a winding-flipped neighbour win instead.
    assert ls._dot(s.surface_normal, normals[anchor_index]) > 0.99

    # And every welded triangle in the lip region (block 652 keeps 79 of 281
    # triangles with reversed winding there) must agree with its own click,
    # not a neighbour's -- this loop is what would have caught the bug.
    # A sliver too thin to click is skipped: round 8's block 652 has one
    # (0.03 units wide) whose centroid lies exactly on its neighbour's edge
    # and plane, so the click is on both surfaces and either answer is right.
    def width(t):
        a, b, c = (pts[k] for k in t)
        area2 = ls._len(ls._cross(ls._sub(b, a), ls._sub(c, a)))
        return area2 / max(ls._len(ls._sub(b, a)), ls._len(ls._sub(c, b)), ls._len(ls._sub(a, c)))
    lip = [i for i, c in enumerate(centroids) if c[2] > 80 and width(tris[i]) > 0.1]
    assert len(lip) > 100
    for i in lip:
        sn = edge_snap.snap(fr, centroids[i])
        assert sn is not None, centroids[i]
        assert ls._dot(sn.surface_normal, normals[i]) > 0.99, centroids[i]


# ── per-state probes (spec 2026-10-17 §4.1, §4.4) ───────────────────────────

def test_new_probe_bindings_exist(host_module):
    for name in ("set_bridge_probe_layers", "set_bridge_glow_captures",
                 "bridge_probe_signatures"):
        assert hasattr(host_module, name)


def test_probe_layers_set_probe_count_and_drop_bad_states(probe_stash_guard, dbridge):
    h, _iid = dbridge
    assert h.bridge_probe_state()["probe_count"] == 5
    assert h.set_bridge_probe_layers([2, 0, 9]) == 1
    assert h.bridge_probe_state()["probe_count"] == 7
    assert len(h.bridge_probe_signatures()) == 7
    h.set_bridge_probe_layers([])


def test_probe_signatures_move_with_red_captures(probe_stash_guard, dbridge):
    h, _iid = dbridge
    spot = ((0.0, 0.0, 50.0), (0.0, 0.0, -1.0), 30.0, 60.0, 100.0, (1.0, 1.0, 1.0), 10.0)

    def cap(red):
        return ([(1.0, 1.0, 1.0), _Z, (red, 0.0, 0.0), _Z, _Z], [-1] * 5, [_Z] * 5)

    assert h.set_bridge_spots([spot], [cap(0.25)]) == 0
    before = h.bridge_probe_signatures()
    assert h.set_bridge_spots([spot], [cap(0.75)]) == 0
    after = h.bridge_probe_signatures()
    assert [i for i, (a, b) in enumerate(zip(before, after)) if a != b] == [2]


def test_probe_scales_must_be_five_values(host_module):
    with pytest.raises(ValueError):
        host_module.set_bridge_probe_scales([1.0, 1.0])


def test_glow_captures_never_raise(host_module):
    host_module.set_bridge_glow_captures(None, [])
    host_module.set_bridge_glow_captures(host_module.InstanceId(), [(0, 0, [], [], [])])


def test_host_io_new_wrappers_degrade_headless_and_forward(monkeypatch):
    monkeypatch.setattr(host_io, "_h", None)
    host_io.set_bridge_probe_layers([2])
    host_io.set_bridge_glow_captures(None, [])
    assert host_io.bridge_probe_signatures() is None
    assert host_io.bridge_quality() == 1
    calls = []

    class H:
        @staticmethod
        def set_bridge_probe_layers(s): calls.append(("layers", s))
        @staticmethod
        def set_bridge_glow_captures(i, r): calls.append(("glow", i, r))
        @staticmethod
        def bridge_quality(): return 2

    monkeypatch.setattr(host_io, "_h", H)
    host_io.set_bridge_probe_layers([2.0])
    z = [(0, 0, 0)] * 5
    host_io.set_bridge_glow_captures("i", [(3, 0, z, [-1] * 5, z)])
    assert host_io.bridge_quality() == 2
    assert calls == [("layers", [2]),
                     ("glow", "i", [(3, 0, [(0.0, 0.0, 0.0)] * 5, [-1] * 5, [(0.0, 0.0, 0.0)] * 5)])]
