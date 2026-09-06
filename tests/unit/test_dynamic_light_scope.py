"""Which dynamic lights reach which render, and that they reach it at all.

Both halves guard a seam where a feature dies SILENTLY with every other test
still green:

* `explosion_lights` can be perfect and, if `host_loop` never concatenates its
  builder into the `set_dynamic_lights` call, no fireball ever casts.
* `render_space_geometry` can take a `dyn_lights` parameter and, if a
  viewscreen call site passes the full list anyway, the suppression silently
  does nothing.

Neither is reachable from a headless unit test — the first needs a live frame,
the second a GL context and a bridge — so these assert on the source.
"""
import ast
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HOST_LOOP = _ROOT / "engine" / "host_loop.py"
_HOST_BINDINGS = _ROOT / "native" / "src" / "host" / "host_bindings.cc"


# ── explosion lights reach the frame ─────────────────────────────────────

def _calls_named(tree, name):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == name:
                out.append(node)
            elif isinstance(fn, ast.Attribute) and fn.attr == name:
                out.append(node)
    return out


def test_host_loop_builds_explosion_lights():
    tree = ast.parse(_HOST_LOOP.read_text())
    assert _calls_named(tree, "_build_explosion_light_render_data"), (
        "host_loop never calls _build_explosion_light_render_data -- death "
        "fireballs would cast no light"
    )


def test_explosion_lights_are_concatenated_into_set_dynamic_lights():
    """The builder existing is not enough; its result must reach the binding."""
    tree = ast.parse(_HOST_LOOP.read_text())
    calls = _calls_named(tree, "set_dynamic_lights")
    assert calls, "host_loop never calls set_dynamic_lights"

    reached = False
    for call in calls:
        for arg in call.args:
            names = {n.func.id for n in ast.walk(arg)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            if "_build_explosion_light_render_data" in names:
                reached = True
    assert reached, (
        "_build_explosion_light_render_data's result is never passed to "
        "set_dynamic_lights"
    )


def test_explosion_lights_are_advanced_and_reset():
    """Without the advance no blast is ever borne; without the reset a ship
    that died in the previous mission keeps lighting the next one."""
    src = _HOST_LOOP.read_text()
    assert "_explosion_lights.advance(" in src, "registry is never ticked"
    assert "_explosion_lights.reset()" in src, "registry survives a mission swap"


# ── the viewscreen suppresses every dynamic light ────────────────────────

def _render_space_geometry_calls(src):
    """Each call's full argument text, brace-matched across line breaks."""
    out = []
    for m in re.finditer(r"render_space_geometry\(", src):
        i = m.end()
        depth = 1
        while depth:
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
            i += 1
        out.append(src[m.end():i - 1])
    return out


def test_every_geometry_call_states_its_light_list():
    """`dyn_lights` is a required parameter precisely so no call site can
    inherit the global by accident."""
    calls = _render_space_geometry_calls(_HOST_BINDINGS.read_text())
    # The lambda's own definition reads `auto render_space_geometry = [&](`,
    # which this pattern deliberately does not match -- so these are the call
    # sites only.
    assert len(calls) == 4, f"expected 4 call sites, got {len(calls)}"
    for args in calls:
        assert "dyn_lights" in args or "g_dynamic_lights" in args, (
            f"a render_space_geometry call names no light list: {args!r}"
        )


def test_viewscreen_renders_pass_no_dynamic_lights():
    """Emitter, torpedo and explosion lights are all suppressed on the
    viewscreen feed; only the sun remains (a separate pass plus the
    directionals, neither of which is a dynamic light)."""
    calls = _render_space_geometry_calls(_HOST_BINDINGS.read_text())
    viewscreen = [a for a in calls if "g_viewscreen_hdr" in a]
    assert len(viewscreen) == 2, (
        f"expected 2 viewscreen render calls, found {len(viewscreen)}"
    )
    for args in viewscreen:
        assert "nullptr" in args.split(",")[-1], (
            f"a viewscreen render passes a light list: {args!r}"
        )
        assert "g_dynamic_lights" not in args, (
            f"a viewscreen render passes the global light list: {args!r}"
        )


def test_main_view_renders_keep_their_dynamic_lights():
    """The suppression must be scoped to the viewscreen — the exterior view
    still gets every emitter."""
    calls = _render_space_geometry_calls(_HOST_BINDINGS.read_text())
    main = [a for a in calls if "g_viewscreen_hdr" not in a]
    assert len(main) == 2, f"expected 2 main-view render calls, found {len(main)}"
    for args in main:
        assert "&g_dynamic_lights" in args, (
            f"a main-view render lost its dynamic lights: {args!r}"
        )
