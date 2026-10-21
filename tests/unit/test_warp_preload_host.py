"""host_loop's side of the warp-tunnel preload: the hooks it hands warp.py,
the Preload deps it builds (each the SAME call realization makes, so the
arrival hits what the tunnel loaded), and the guarded per-frame step."""
import ast
import inspect
from types import SimpleNamespace

import pytest

import App
from engine import dev_mode, host_loop, warp_preload
from engine import dev_nebula_dials as D
from engine.appc.sets import SetClass_Create


class _R:
    def __init__(self, far=True, volumetric=True):
        self._far = far
        self._volumetric = volumetric
        self.profiles = []

    def far_enabled(self):
        return self._far

    def volumetric_nebulae_enabled(self):
        return self._volumetric

    def set_system_nebula_profile(self, d):
        self.profiles.append(d)

    def set_system_nebula_star(self, pos):
        pass


def _controller(instances=None):
    return SimpleNamespace(
        session=SimpleNamespace(ship_instances=dict(instances or {})),
        nif_to_handle={}, nif_to_extent={}, nif_to_sphere_radius={})


@pytest.fixture(autouse=True)
def _no_active_preload(monkeypatch):
    monkeypatch.setattr(warp_preload, "_active", None)
    yield
    App.g_kSetManager._sets.clear()


# -- hooks -----------------------------------------------------------------

def test_ready_is_true_with_no_active_preload():
    assert host_loop._warp_preload_ready() is True


def test_ready_reads_the_active_preload(monkeypatch):
    monkeypatch.setattr(warp_preload, "_active",
                        SimpleNamespace(ready=lambda: False))
    assert host_loop._warp_preload_ready() is False


def test_hooks_begin_end_pending_replan(monkeypatch):
    hooks = host_loop._warp_preload_hooks(_controller(), _R(far=False))
    assert set(hooks) == {"preload_begin", "preload_ready", "preload_replan",
                          "preload_end", "preload_pending"}
    assert hooks["preload_pending"]() == []
    hooks["preload_replan"]()                # no preload: a no-op
    hooks["preload_begin"]("Vesuvi4")
    p = warp_preload.active()
    assert isinstance(p, warp_preload.Preload) and p._dest == "Vesuvi4"
    assert p._atlases is False               # far_enabled read at begin
    hooks["preload_end"]()
    assert warp_preload.active() is None


def test_step_guards_none():
    host_loop._step_warp_preload()           # no preload: nothing raises


def test_step_swallows_a_preload_exception(monkeypatch):
    def _boom():
        raise RuntimeError("boom")
    monkeypatch.setattr(warp_preload, "_active", SimpleNamespace(step=_boom))
    seen = []
    monkeypatch.setattr(dev_mode, "log_swallowed",
                        lambda what, e: seen.append((what, str(e))))
    host_loop._step_warp_preload()
    assert seen == [("warp preload step", "boom")]


# -- deps ------------------------------------------------------------------

def test_deps_atlases_and_haze_gate(monkeypatch):
    r = _R(far=True, volumetric=True)
    deps = host_loop._warp_preload_deps(_controller(), r)
    assert deps["renderer"] is r
    assert deps["atlases"] is True
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    assert deps["haze_enabled"]() is True
    r._volumetric = False                    # read live, like the arrival
    assert deps["haze_enabled"]() is False


def test_deps_ships_excludes_realized_and_missing_set():
    s = SetClass_Create(); App.g_kSetManager.AddSet(s, "PHostDest")
    a = App.ShipClass_Create(); a.SetName("A"); s.AddObjectToSet(a, "A")
    b = App.ShipClass_Create(); b.SetName("B"); s.AddObjectToSet(b, "B")
    deps = host_loop._warp_preload_deps(_controller({a: 7}), _R())
    assert deps["ships"]("PHostDest") == [b]
    assert deps["ships"]("NoSuchSet") == []


def test_deps_load_ship_prewarms_the_loaded_handle(monkeypatch):
    from engine.appc import hull_volume
    r = _R()
    loads, prewarms = [], []
    monkeypatch.setattr(host_loop, "_load_runtime_ship_model",
                        lambda ship, r_: (loads.append((ship, r_))
                                          or ("H", "m.nif", "m.nif", 1.0)))
    monkeypatch.setattr(hull_volume, "prewarm_for_model",
                        lambda handle: prewarms.append(handle))
    ship = object()
    host_loop._warp_preload_deps(_controller(), r)["load_ship"](ship)
    assert loads == [(ship, r)]
    assert prewarms == ["H"]


def test_deps_load_ship_without_a_model_skips_prewarm(monkeypatch):
    from engine.appc import hull_volume
    prewarms = []
    monkeypatch.setattr(host_loop, "_load_runtime_ship_model",
                        lambda ship, r_: None)
    monkeypatch.setattr(hull_volume, "prewarm_for_model",
                        lambda handle: prewarms.append(handle))
    host_loop._warp_preload_deps(_controller(), _R())["load_ship"](object())
    assert prewarms == []


def test_deps_planet_models_are_the_orbiting_bodies():
    from engine.systems import resolve
    m = resolve.for_set("Vesuvi4")[0]
    want = [b.appearance.model for b in m.bodies if b.orbits is not None]
    assert want                              # Vesuvi has planets
    got = host_loop._warp_preload_deps(_controller(), _R())["planet_models"](
        "Vesuvi4")
    assert list(got) == want
    assert list(host_loop._warp_preload_deps(_controller(), _R())
                ["planet_models"]("NoSuchSet")) == []


def test_deps_load_planet_uses_the_controller_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(host_loop, "_planet_model_path",
                        lambda rel: None if rel == "missing" else "/abs/" + rel)
    monkeypatch.setattr(host_loop, "_load_planet_model",
                        lambda r_, path, *, cache=None:
                        calls.append((r_, path, cache)))
    r, c = _R(), _controller()
    load = host_loop._warp_preload_deps(c, r)["load_planet"]
    load("p.nif")
    load("missing")
    assert calls == [(r, "/abs/p.nif", c)]


# -- the haze dict the tunnel prebuilds IS the one the arrival pushes ---------

def test_preload_haze_dict_equals_the_arrival_push(monkeypatch):
    """The native far-field table cache is keyed on the dict's contents: the
    preload's profile_dict_for_set(set) must equal what _push_system_nebula
    pushes once the player is in that set, or the arrival rebuilds."""
    from engine import system_haze
    from engine.systems import frames, resolve
    monkeypatch.setattr(D, "_dials", dict(D.DEFAULTS))
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", None)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_veil",
                        host_loop._system_nebula_pushed_veil)
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    system = resolve.system_of("Vesuvi4")
    monkeypatch.setattr(frames, "system_position",
                        lambda obj: (("system", system), 1.0, 2.0, 3.0))
    preloaded = system_haze.profile_dict_for_set("Vesuvi4")
    assert preloaded is not None
    r = _R()
    host_loop._push_system_nebula(r, object(), [{"position": (0, 0, 0)}],
                                  False)
    assert r.profiles == [preloaded]


# -- run() wiring ------------------------------------------------------------

def _run_tree():
    return ast.parse(inspect.getsource(host_loop.run))


def _call_name(node):
    f = node.func
    return f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)


def test_run_configures_the_preload_hooks():
    found = False
    for node in ast.walk(_run_tree()):
        if (isinstance(node, ast.Call)
                and _call_name(node) == "configure_warp_hooks"):
            for kw in node.keywords:
                if (kw.arg is None and isinstance(kw.value, ast.Call)
                        and _call_name(kw.value) == "_warp_preload_hooks"):
                    found = True
    assert found


def test_run_steps_the_preload_once_per_frame_after_the_ticks():
    """Inside frame_profiler.scope("warp.preload"), after loop.tick(), and
    not inside the per-tick loop."""
    tree = _run_tree()
    tick_line = next(n.lineno for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and _call_name(n) == "tick"
                     and isinstance(n.func, ast.Attribute)
                     and isinstance(n.func.value, ast.Name)
                     and n.func.value.id == "loop")
    steps = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        ctx = node.items[0].context_expr
        if not (isinstance(ctx, ast.Call) and _call_name(ctx) == "scope"
                and ctx.args and isinstance(ctx.args[0], ast.Constant)
                and ctx.args[0].value == "warp.preload"):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and _call_name(sub) == "_step_warp_preload":
                steps.append(sub.lineno)
    assert len(steps) == 1 and steps[0] > tick_line
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            inner = {n.lineno for n in ast.walk(node)
                     if isinstance(n, ast.Call)}
            if tick_line in inner:
                assert steps[0] not in inner    # not once per sim tick


# -- F1: a mission swap drops the running preload -----------------------------

def test_mission_swap_reset_drops_the_preload_and_its_owner(monkeypatch):
    from engine.appc import warp
    monkeypatch.setattr(warp_preload, "_active", object())
    monkeypatch.setattr(warp, "_preload_owner", object())
    host_loop.reset_sdk_globals()
    assert warp_preload.active() is None
    assert warp._preload_owner is None
