"""Tests for host-loop lighting wiring (Phase-1 lights → renderer)."""
import os

import pytest


def test_set_lighting_binding_smoke():
    """Calling set_lighting on the bindings module does not raise."""
    import _open_stbc_host
    _open_stbc_host.set_lighting(
        (0.2, 0.3, 0.4),
        [
            ((0.0, -1.0, 0.0), (1.0, 0.9, 0.8)),
            ((1.0, 0.0, 0.0), (0.5, 0.5, 0.5)),
        ],
    )


def test_set_lighting_accepts_empty_directionals():
    import _open_stbc_host
    _open_stbc_host.set_lighting((0.5, 0.5, 0.5), [])


def test_set_lighting_clamps_to_max_directionals():
    """Passing more than 4 directionals must not raise (truncation in C++)."""
    import _open_stbc_host
    _open_stbc_host.set_lighting(
        (0.1, 0.1, 0.1),
        [((0.0, 1.0, 0.0), (1.0, 1.0, 1.0))] * 8,
    )


def test_renderer_module_set_lighting_wrapper():
    """The Python wrapper round-trips arguments to the bindings."""
    from engine import renderer
    renderer.set_lighting(
        (0.1, 0.2, 0.3),
        [((0.0, 1.0, 0.0), (1.0, 1.0, 1.0))],
    )


def test_default_lighting_constants_present():
    from engine import host_loop
    assert isinstance(host_loop.DEFAULT_AMBIENT, tuple)
    assert len(host_loop.DEFAULT_AMBIENT) == 3
    assert isinstance(host_loop.DEFAULT_DIRECTIONALS, list)
    assert len(host_loop.DEFAULT_DIRECTIONALS) >= 1
    direction, color = host_loop.DEFAULT_DIRECTIONALS[0]
    assert len(direction) == 3 and len(color) == 3


def test_aggregate_lights_none_returns_defaults():
    from engine import host_loop
    ambient, directionals = host_loop._aggregate_lights(None)
    assert ambient == host_loop.DEFAULT_AMBIENT
    assert directionals == host_loop.DEFAULT_DIRECTIONALS


def test_aggregate_lights_ambient_last_wins():
    import App
    from engine import host_loop
    pSet = App.SetClass_Create()
    pSet.CreateAmbientLight(0.1, 0.1, 0.1, 1.0, "a1")
    pSet.CreateAmbientLight(0.4, 0.5, 0.6, 0.5, "a2")  # last
    ambient, directionals = host_loop._aggregate_lights(pSet)
    # 0.4 * 0.5 = 0.2 etc.
    assert ambient[0] == pytest.approx(0.2)
    assert ambient[1] == pytest.approx(0.25)
    assert ambient[2] == pytest.approx(0.3)
    assert directionals == []


def test_aggregate_lights_directional_negates_forward():
    """BC's directional forward is 'where the light shines'; renderer
    wants 'direction toward the light'. host_loop must negate every
    component. Uses a non-axis forward so each axis exercises the sign
    flip individually — an axis-aligned input would mask a partial
    negation that left positive zeros in place."""
    import App
    from engine import host_loop
    pSet = App.SetClass_Create()
    # Forward = (0.5, 0.5, -0.5): non-zero on every axis; the negation
    # must produce (-0.5, -0.5, 0.5) — sign-flip on x, y AND z.
    pSet.CreateDirectionalLight(1.0, 1.0, 1.0, 1.0, 0.5, 0.5, -0.5, "d1")
    _, directionals = host_loop._aggregate_lights(pSet)
    assert len(directionals) == 1
    direction, color = directionals[0]
    dx, dy, dz = direction
    assert dx == pytest.approx(-0.5)
    assert dy == pytest.approx(-0.5)
    assert dz == pytest.approx(0.5)
    assert color == (1.0, 1.0, 1.0)


def test_aggregate_lights_truncates_to_four():
    import App
    from engine import host_loop
    pSet = App.SetClass_Create()
    for i in range(6):
        pSet.CreateDirectionalLight(
            1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 0.0, f"d{i}")
    _, directionals = host_loop._aggregate_lights(pSet)
    assert len(directionals) == 4


def test_aggregate_lights_overflow_warning_fires_once_per_set(capsys):
    """The >MAX_DIRECTIONALS warning prints once per SetClass — second
    aggregation pass on the same set must be silent (no per-tick spam)."""
    import App
    from engine import host_loop
    pSet = App.SetClass_Create()
    pSet.SetName("OverflowSet")
    for i in range(6):
        pSet.CreateDirectionalLight(
            1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 0.0, f"d{i}")

    host_loop._aggregate_lights(pSet)
    first = capsys.readouterr().out
    assert "OverflowSet" in first
    assert "dropped extra directional lights" in first

    host_loop._aggregate_lights(pSet)
    second = capsys.readouterr().out
    assert second == ""


def test_aggregate_lights_filters_zero_vector_directions():
    import App
    from engine import host_loop
    pSet = App.SetClass_Create()
    pSet.CreateDirectionalLight(1, 1, 1, 1, 0, 1, 0, "good")
    pSet.CreateDirectionalLight(1, 1, 1, 1, 0, 0, 0, "zero")
    _, directionals = host_loop._aggregate_lights(pSet)
    assert len(directionals) == 1


def test_resolve_active_lighting_set_prefers_rendered():
    import App
    from engine import host_loop
    pRendered = App.SetClass_Create()
    pRendered.CreateAmbientLight(1, 1, 1, 1, "a")
    App.g_kSetManager.AddSet(pRendered, "RenderedSet")
    App.g_kSetManager.MakeRenderedSet("RenderedSet")
    try:
        active = host_loop._resolve_active_lighting_set(player=None)
        assert active is pRendered
    finally:
        App.g_kSetManager.DeleteSet("RenderedSet")
        App.g_kSetManager._rendered_set_name = None


def test_resolve_active_lighting_set_falls_back_to_player_set():
    import App
    from engine import host_loop
    App.g_kSetManager._rendered_set_name = None  # explicitly unset
    pPlayer = App.SetClass_Create()
    pPlayer.CreateAmbientLight(1, 1, 1, 1, "a")
    App.g_kSetManager.AddSet(pPlayer, "PlayerSet")

    class _FakePlayer: pass
    fp = _FakePlayer()
    pPlayer.AddObjectToSet(fp, "player")
    try:
        active = host_loop._resolve_active_lighting_set(player=fp)
        assert active is pPlayer
    finally:
        App.g_kSetManager.DeleteSet("PlayerSet")


def test_resolve_active_lighting_set_returns_none_for_no_lights():
    import App
    from engine import host_loop
    App.g_kSetManager._rendered_set_name = None
    pEmpty = App.SetClass_Create()  # no lights
    App.g_kSetManager.AddSet(pEmpty, "Empty")
    try:
        active = host_loop._resolve_active_lighting_set(player=None)
        assert active is None
    finally:
        App.g_kSetManager.DeleteSet("Empty")


def test_g_lighting_persists_across_frames():
    """A second frame() without a new set_lighting must use the lighting
    from the first set_lighting call. Isolates the C++-side persistence
    of g_lighting from the rendered-pixel test that re-sets it each frame."""
    from pathlib import Path

    PROJECT_ROOT = Path(__file__).parent.parent.parent
    GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")

    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host

    _open_stbc_host.init(640, 360, "test_lighting_persistence")
    try:
        tex_search = str(PROJECT_ROOT / "game" / "data" / "Models" /
                         "SharedTextures" / "FedShips" / "High")
        h = _open_stbc_host.load_model(str(GALAXY_NIF), tex_search)
        iid = _open_stbc_host.create_instance(h)
        _open_stbc_host.set_world_transform(iid, [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ])
        _open_stbc_host.set_camera(
            eye=(0.0, 0.0, 1500.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472, near=1.0, far=100000.0,
        )

        fw, fh = _open_stbc_host.framebuffer_size()
        cx, cy = fw // 2, fh // 2

        _open_stbc_host.set_lighting((1.0, 0.0, 0.0), [])
        _open_stbc_host.frame()
        r1 = _open_stbc_host.read_pixel(cx, cy)[0]

        # Deliberately no second set_lighting — second frame should
        # use the same g_lighting state.
        _open_stbc_host.frame()
        r2 = _open_stbc_host.read_pixel(cx, cy)[0]

        assert r1 == r2, f"lighting did not persist: r1={r1}, r2={r2}"
        assert r1 > 100, f"first frame should have been brightly red-lit, got r={r1}"
    finally:
        _open_stbc_host.destroy_instance(iid)
        _open_stbc_host.shutdown()


def test_g_lighting_resets_on_shutdown():
    """After shutdown(), the next init() starts with the default Lighting
    (not whatever was set in the previous session). Verified by setting
    bright-red ambient in session A, then in session B not calling
    set_lighting and checking the rendered pixel is *not* red."""
    from pathlib import Path

    PROJECT_ROOT = Path(__file__).parent.parent.parent
    GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"

    import _open_stbc_host

    def _render_one_frame(set_lighting_call):
        _open_stbc_host.init(640, 360, "test_lighting_reset")
        try:
            tex_search = str(PROJECT_ROOT / "game" / "data" / "Models" /
                             "SharedTextures" / "FedShips" / "High")
            h = _open_stbc_host.load_model(str(GALAXY_NIF), tex_search)
            iid = _open_stbc_host.create_instance(h)
            _open_stbc_host.set_world_transform(iid, [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0,
            ])
            _open_stbc_host.set_camera(
                eye=(0.0, 0.0, 1500.0),
                target=(0.0, 0.0, 0.0),
                up=(0.0, 1.0, 0.0),
                fov_y_rad=1.0472, near=1.0, far=100000.0,
            )
            fw, fh = _open_stbc_host.framebuffer_size()
            cx, cy = fw // 2, fh // 2

            if set_lighting_call is not None:
                set_lighting_call()
            _open_stbc_host.frame()
            return _open_stbc_host.read_pixel(cx, cy)
        finally:
            _open_stbc_host.destroy_instance(iid)
            _open_stbc_host.shutdown()

    # Session A: bright red ambient.
    rA, gA, bA, _ = _render_one_frame(
        lambda: _open_stbc_host.set_lighting((1.0, 0.0, 0.0), [])
    )
    assert rA > 100, "session A should have been red-lit"
    assert rA > gA + 50, "session A red should dominate green"

    # Session B: no set_lighting — must NOT reuse session A's red ambient.
    rB, gB, bB, _ = _render_one_frame(set_lighting_call=None)
    # Default lighting has equal r/g/b channels (white directional + grey
    # ambient), so we don't expect red dominance.
    assert abs(int(rB) - int(gB)) < 30, (
        f"session B should use neutral defaults, got "
        f"r={rB} g={gB} b={bB} — looks like stale session-A red leaked")


def test_set_lighting_changes_rendered_pixel():
    """End-to-end: set_lighting with bright red ambient changes the
    on-screen pixel sampled at the centre of the frame, vs. set_lighting
    with black ambient + no directionals."""
    from pathlib import Path

    PROJECT_ROOT = Path(__file__).parent.parent.parent
    GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")

    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host

    _open_stbc_host.init(640, 360, "test_set_lighting_changes_pixel")
    try:
        tex_search = str(PROJECT_ROOT / "game" / "data" / "Models" /
                         "SharedTextures" / "FedShips" / "High")
        h = _open_stbc_host.load_model(str(GALAXY_NIF), tex_search)
        iid = _open_stbc_host.create_instance(h)
        _open_stbc_host.set_world_transform(iid, [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ])
        _open_stbc_host.set_camera(
            eye=(0.0, 0.0, 1500.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472, near=1.0, far=100000.0,
        )

        fw, fh = _open_stbc_host.framebuffer_size()
        cx, cy = fw // 2, fh // 2

        # Bright red ambient, no directionals.
        _open_stbc_host.set_lighting((1.0, 0.0, 0.0), [])
        _open_stbc_host.frame()
        red_r, red_g, red_b, _ = _open_stbc_host.read_pixel(cx, cy)

        # Black: no ambient, no directionals → fully unlit Galaxy.
        _open_stbc_host.set_lighting((0.0, 0.0, 0.0), [])
        _open_stbc_host.frame()
        dark_r, _, _, _ = _open_stbc_host.read_pixel(cx, cy)

        assert red_r > dark_r + 50, (
            f"Expected red ambient to brighten pixel: red_r={red_r}, "
            f"dark_r={dark_r}")
    finally:
        _open_stbc_host.destroy_instance(iid)
        _open_stbc_host.shutdown()
