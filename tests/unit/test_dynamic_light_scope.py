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


# ── the two bugs that made the fireball lights invisible in-game ─────────

def test_the_light_list_goes_through_the_category_budget():
    """Plain concatenation starves whichever category is last, and the native
    cap truncates rather than prioritising. The budget helper is what stops a
    busy scene dropping every explosion light, so the binding must be fed from
    it and not from a raw `a + b + c`."""
    tree = ast.parse(_HOST_LOOP.read_text())
    calls = _calls_named(tree, "set_dynamic_lights")
    assert calls, "host_loop never calls set_dynamic_lights"

    for call in calls:
        src = ast.unparse(call)
        if "_build_explosion_light_render_data" not in src:
            continue
        assert "_budgeted_dynamic_lights" in src, (
            "the light list is built by raw concatenation, so the native "
            "truncation decides what survives:\n  " + src
        )
        return
    raise AssertionError("no set_dynamic_lights call builds explosion lights")


def test_explosion_light_radius_clears_the_ship_scale_ceiling():
    """Below renderer's kDynLightShipCeilingGU (40 GU) the attenuation
    reference is 1 and the light falls off as 1/(d^2+1) in GAME UNITS -- a
    curve for lights sitting ON a hull. A fireball light under that ceiling
    delivers ~0.01 to a neighbour 20 GU away, i.e. nothing. This shipped at a
    33 GU radius and was invisible even with 50 ships packed together."""
    from engine.appc import explosion_lights as el

    CEILING_GU = 40.0   # renderer::kDynLightShipCeilingGU
    # A small craft is the worst case: the smallest fireball, hence the
    # smallest radius this factor can produce.
    smallest_fireball_gu = 2.0          # ship_death.MIN_EXPLOSION_SIZE
    radius = max(smallest_fireball_gu * el.RADIUS_FACTOR,
                 el.MIN_LIGHT_RADIUS_GU)
    assert radius > CEILING_GU, (
        f"the smallest fireball's light radius is {radius:g} GU, at or under "
        f"the {CEILING_GU:g} GU ship-scale ceiling -- it will not carry to a "
        "neighbouring hull"
    )


def test_explosion_lights_survive_a_camera_far_beyond_the_dyn_light_cull():
    """THE bug that made the feature invisible in game.

    `_camera_distance_fade` returns None -- meaning "do not build this light at
    all" -- past DYN_LIGHT_CULL_GU (~86 GU, 15 km). That is correct for
    hull-local lights like torpedo glows and subsystem emitters. An explosion
    light has a 110+ GU radius and exists to light the ships AROUND it, so the
    camera's distance from it is the wrong question: combat routinely happens
    past 15 km, and every fireball light was discarded before it was built.
    Intensity, radius and list truncation were all irrelevant while this held.
    """
    import engine.host_loop as host_loop
    from engine.appc import explosion_lights

    class _P:
        def __init__(self, x):
            self.x, self.y, self.z = x, 0.0, 0.0

    class _Ship:
        def __init__(self, x):
            self._p = _P(x)

        def GetWorldLocation(self):
            return self._p

    explosion_lights.reset()
    try:
        # A ship dying 4000 GU away -- far outside the cull, ordinary for combat.
        far_gu = host_loop.DYN_LIGHT_CULL_GU * 45.0
        explosion_lights.register(_Ship(far_gu), size_gu=11.0, count=1,
                                  spacing_s=1.0, life_s=3.0)
        explosion_lights.advance(0.4)
        host_loop._note_camera_eye((0.0, 0.0, 0.0))

        built = host_loop._build_explosion_light_render_data()
        assert built, (
            f"an explosion {far_gu:.0f} GU from the camera produced no light; "
            "the camera-distance cull is being applied to a light whose reach "
            "has nothing to do with camera distance"
        )
        assert built[0]["intensity"] > 0.0
    finally:
        explosion_lights.reset()
        host_loop._note_camera_eye(None)
