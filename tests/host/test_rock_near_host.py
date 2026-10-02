"""Rock fields near band, host wiring (rock-fields plan Task 7).

frame() streams the native NearField around the player (or the main camera),
steps its contacts, and draws its meshes and billboards per drawn camera;
far_stats() reports what it holds and drew. Everything is gated on the far
tier being enabled.
"""
import os

import pytest

h = pytest.importorskip("_dauntless_host")

from engine.rocks import far_tier  # noqa: E402


def _sphere_source(radius=2000.0):
    """One full-density view-space sphere around the origin, no noise."""
    return {
        "id": 41, "frame": "", "centre": (0.0, 0.0, 0.0), "normal": (0.0, 0.0, 1.0),
        "table": [], "outer_fade_gu": 0.0, "scale_height_frac": 0.03,
        "scale_height_min_gu": 1000.0, "seed": 5, "explicit_regions": [],
        "populations": [], "shape": "sphere", "procedural": False,
        "view_space": True, "sphere_radius_gu": radius, "sphere_edge_frac": 0.0}


def _row_major(x, y, z, s=1.0):
    return [s, 0, 0, x, 0, s, 0, y, 0, 0, s, z, 0, 0, 0, 1.0]


def _set_camera_at_origin(host):
    host.set_camera(eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, -1.0),
                    up=(0.0, 1.0, 0.0), fov_y_rad=1.0472, near=0.1, far=1.0e7)


def _push_real_catalogue():
    """The real catalogue, pushed exactly as reconcile pushes it."""
    from engine import renderer
    far_tier.reset()
    far_tier._push_catalogue(renderer)


def _stream_at_origin(host):
    _push_real_catalogue()
    host.far_set_dials({})
    host.far_set_sources([_sphere_source(radius=2000.0)])
    host.far_set_frame(None, (0.0, 0.0, 0.0))
    _set_camera_at_origin(host)
    host.frame()


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(64, 64, "test_rock_near")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        yield h
    finally:
        h.far_clear()
        h.far_set_dials({})
        h.far_set_enabled(True)
        h.minors_set_player(None)
        h.shutdown()
        far_tier.reset()


def test_near_bindings_are_on_the_facade():
    from engine import renderer
    for name in ("rockfield_drain_contacts", "rockfield_set_shield_inflate"):
        assert callable(getattr(renderer, name))


def test_inside_a_tile_field_streams_and_draws_near_rocks(host):
    _stream_at_origin(host)
    st = host.far_stats()
    assert st["near_cells"] > 0
    assert st["near_small"] > 0 and st["near_large"] > 0
    assert st["near_meshes"] > 0 and st["near_billboards"] > 0


def test_far_clear_drops_the_near_field(host):
    _stream_at_origin(host)
    assert host.far_stats()["near_cells"] > 0
    host.far_clear()
    st = host.far_stats()
    assert st["near_cells"] == 0 and st["near_small"] == 0 and st["near_large"] == 0
    assert host.rockfield_drain_contacts() == []


def test_disabled_far_tier_streams_nothing(host):
    host.far_set_enabled(False)
    _stream_at_origin(host)
    st = host.far_stats()
    assert st["near_cells"] == 0
    assert st["near_meshes"] == 0 and st["near_billboards"] == 0


def test_a_player_sweeping_through_large_rocks_reports_contacts(host):
    """The player box streams the field and its swept path touches large
    rocks: rockfield_drain_contacts returns them, with the documented keys."""
    _push_real_catalogue()
    # Dense large rocks so a 300 GU sweep certainly crosses some.
    host.far_set_dials({"near_large_density": 0.002, "near_small_density": 0.0})
    host.far_set_sources([_sphere_source(radius=2000.0)])
    host.far_set_frame(None, (0.0, 0.0, 0.0))
    _set_camera_at_origin(host)
    from engine.rocks import catalogue
    rock = catalogue.pick("x", kind="fragment", family="silicate")
    ship = host.create_instance(
        host.load_model(rock.lod_paths[0], [], None, decals=None, scale=1.0))
    host.minors_set_player(ship)
    contacts = []
    for i in range(31):
        host.damage_decals_tick(0.1 * i)
        host.set_world_transform(ship, _row_major(-150.0 + 10.0 * i, 0.0, 0.0, 0.05))
        host.frame()
        contacts += host.rockfield_drain_contacts()
    assert host.far_stats()["near_cells"] > 0
    assert contacts, "a dense 300 GU sweep touched no large rock"
    c = contacts[0]
    assert set(c) == {"point", "normal", "rock_centre", "rock_radius", "rel_speed", "pen"}
    assert len(c["point"]) == 3 and len(c["normal"]) == 3 and len(c["rock_centre"]) == 3
    assert c["rock_radius"] > 0.0 and c["rel_speed"] > 0.0 and c["pen"] >= 0.0


def _sweep_player(host, steps=31):
    from engine.rocks import catalogue
    rock = catalogue.pick("x", kind="fragment", family="silicate")
    ship = host.create_instance(
        host.load_model(rock.lod_paths[0], [], None, decals=None, scale=1.0))
    host.minors_set_player(ship)
    minor, large = [], []
    for i in range(steps):
        host.damage_decals_tick(0.1 * i)
        host.set_world_transform(ship, _row_major(-150.0 + 10.0 * i, 0.0, 0.0, 0.05))
        host.frame()
        minor += host.minors_drain_contacts()
        large += host.rockfield_drain_contacts()
    return minor, large


def test_small_near_rock_touches_ride_the_minor_contacts(host):
    """Ruling 3: small near rocks are minors to the game -- their touches
    come back from minors_drain_contacts, after MinorField's own."""
    _push_real_catalogue()
    host.far_set_dials({"near_small_density": 0.05, "near_large_density": 0.0})
    host.far_set_sources([_sphere_source(radius=2000.0)])
    host.far_set_frame(None, (0.0, 0.0, 0.0))
    _set_camera_at_origin(host)
    minor, large = _sweep_player(host)
    assert minor, "a dense small-rock sweep reported no minor contacts"
    assert set(minor[0]) == {"point", "radius", "rel_speed"}
    assert large == []


def _catalogue_entries(atlas_ok):
    from engine import renderer
    from engine.rocks import catalogue
    entries = []
    for i, rock in enumerate(catalogue.load()):
        e = far_tier._catalogue_entry(renderer, rock)
        if not atlas_ok:
            e["albedo"] = "/nonexistent/near_host_test/a%d.png" % i
            e["normal"] = "/nonexistent/near_host_test/n%d.png" % i
        entries.append(e)
    return entries, [tuple(d) for d in catalogue.impostor_view_dirs()]


def _stream_with(host, entries, dirs):
    host.far_clear()
    host.far_set_catalogue(entries, dirs)
    host.far_set_dials({})
    host.far_set_sources([_sphere_source(radius=2000.0)])
    host.far_set_frame(None, (0.0, 0.0, 0.0))
    _set_camera_at_origin(host)
    host.frame()
    host.frame()
    return host.far_stats()


def test_a_near_rock_whose_atlas_fails_keeps_its_mesh_and_draws_no_billboard(host):
    """Ruling 2 (revised): an atlas that cannot load never mutates the near
    field from the draw -- the rock keeps its mesh tier and simply draws no
    billboard; the streamed cells are exactly those of a good catalogue."""
    far_tier.reset()
    # The failing catalogue first: FarPass keeps an atlas it has loaded
    # across set_atlas_paths, so a fresh session must meet the bad paths.
    bad = _stream_with(host, *_catalogue_entries(atlas_ok=False))
    good = _stream_with(host, *_catalogue_entries(atlas_ok=True))
    assert good["near_billboards"] > 0
    assert bad["near_meshes"] > 0
    assert bad["near_billboards"] == 0
    for k in ("near_cells", "near_small", "near_large", "near_ghosted"):
        assert bad[k] == good[k], k
    assert host.rockfield_drain_contacts() == []
    host.far_set_catalogue([], [])


def test_near_cells_stream_around_the_player_not_the_camera(host):
    """Centre = render origin + the player's render position + the far
    anchor: with a non-zero origin and anchor, a small sphere around the
    player's SYSTEM position streams, while the camera sits far outside it."""
    _push_real_catalogue()
    host.far_set_dials({})
    anchor = (3000.0, -2000.0, 500.0)
    # View-space sphere: system centre = anchor + centre = anchor.
    host.far_set_sources([_sphere_source(radius=150.0)])
    host.far_set_frame(None, anchor)
    host.set_render_origin(1000.0, 0.0, 0.0)
    from engine.rocks import catalogue
    rock = catalogue.pick("x", kind="fragment", family="silicate")
    ship = host.create_instance(
        host.load_model(rock.lod_paths[0], [], None, decals=None, scale=1.0))
    # VIEW translation 0 -> render (-1000, 0, 0) -> system = anchor.
    host.set_world_transform(ship, _row_major(0.0, 0.0, 0.0, 0.05))
    host.set_camera(eye=(5000.0, 0.0, 0.0), target=(5000.0, 0.0, -1.0),
                    up=(0.0, 1.0, 0.0), fov_y_rad=1.0472, near=0.1, far=1.0e7)
    host.frame()
    assert host.far_stats()["near_cells"] == 0      # no player: camera, outside
    host.minors_set_player(ship)
    host.frame()
    assert host.far_stats()["near_cells"] > 0       # the player, inside
    host.reset_render_origin()


def _contacts_of_sweep(host, inflate):
    host.far_clear()
    host.minors_set_player(None)
    host.far_set_dials({"near_large_density": 0.0005, "near_small_density": 0.0})
    host.far_set_sources([_sphere_source(radius=2000.0)])
    host.far_set_frame(None, (0.0, 0.0, 0.0))
    _set_camera_at_origin(host)
    host.rockfield_set_shield_inflate(inflate)
    _minor, large = _sweep_player(host)
    return large


def test_shield_inflate_widens_the_contact_box(host):
    """The same deterministic sweep touches more large rocks with the box
    inflated (shields up) than with the bare hull box."""
    _push_real_catalogue()
    bare = _contacts_of_sweep(host, 0.0)
    inflated = _contacts_of_sweep(host, 4.0)
    assert len(inflated) > len(bare)
    host.rockfield_set_shield_inflate(0.0)


def test_host_reinit_repushes_the_near_catalogue(host):
    """Model handles die with the session, so native empties the near
    catalogue on init; far_tier must notice and push it again even with no
    mission swap (its catalogue-root guard alone would skip it)."""
    from engine import renderer
    far_tier.reset()
    far_tier.reconcile_with(renderer, None, {})
    assert host.rockfield_catalogue_size() > 0
    host.shutdown()
    host.init(64, 64, "test_rock_near_reinit")
    assert host.rockfield_catalogue_size() == 0
    far_tier.reconcile_with(renderer, None, {})
    assert host.rockfield_catalogue_size() > 0
