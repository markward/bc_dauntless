"""Per-instance decal override through the real _dauntless_host binding.

``set_instance_decals(iid, decals | None)`` is the Ship Property Viewer's
live preview (spec 2026-09-28-spv-decal-editing-design.md §2.5): a list
REPLACES the instance's baked decals for drawing, ``None`` clears it. Like
``load_model``'s decals, a malformed entry is skipped with a warning and the
binding never raises -- not for a bad entry, and not for an unknown id.
``instance_decal_override_size`` is the read-back: the number of decals the
override draws, or None when the instance draws its baked list.
"""
import os

import pytest

from tests.helpers import bc_assets
from engine.appc import hull_decals

GAME_DATA = bc_assets.GAME_ROOT / "data"
AMBASSADOR_NIF = GAME_DATA / "Models" / "Ships" / "Ambassador" / "Ambassador.nif"
AMBASSADOR_TEX = GAME_DATA / "Models" / "Ships" / "Ambassador" / "High"


def _skip_unless_assets_available():
    if not AMBASSADOR_NIF.is_file():
        pytest.skip(f"BC asset not available at {AMBASSADOR_NIF}")
    if not AMBASSADOR_TEX.is_dir():
        pytest.skip(f"BC texture dir not available at {AMBASSADOR_TEX}")


def _init_host(label):
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(640, 480, label)
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    return _dauntless_host


def _zhukov_top():
    decals = hull_decals.decals_for("data/Models/Ships/Ambassador", "Zhukov")
    assert decals, "expected the committed Zhukov 'top' decal to resolve"
    return decals[0]


def _plain_ambassador(host):
    handle = host.load_model(str(AMBASSADOR_NIF), str(AMBASSADOR_TEX))
    return host.create_instance(handle)


def test_malformed_entry_is_skipped_and_the_valid_one_kept(capfd):
    _skip_unless_assets_available()
    good = _zhukov_top()
    host = _init_host("instance-decal-malformed")
    try:
        iid = _plain_ambassador(host)
        malformed = ("amb saucer:0", ("not", "a", "vector"), (1.0, 0.0, 0.0),
                     (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 1.0, "/nonexistent.png")
        host.set_instance_decals(iid, [malformed, good, 42])
        assert host.instance_decal_override_size(iid) == 1
    finally:
        host.shutdown()
    assert "malformed decal" in capfd.readouterr().err


def test_none_clears_and_an_empty_list_is_an_override():
    _skip_unless_assets_available()
    good = _zhukov_top()
    host = _init_host("instance-decal-none")
    try:
        iid = _plain_ambassador(host)
        assert host.instance_decal_override_size(iid) is None
        host.set_instance_decals(iid, [good])
        assert host.instance_decal_override_size(iid) == 1
        host.set_instance_decals(iid, None)
        assert host.instance_decal_override_size(iid) is None
        host.set_instance_decals(iid, [])
        assert host.instance_decal_override_size(iid) == 0, (
            "an empty list replaces the baked decals with none")
    finally:
        host.shutdown()


def test_more_than_four_keeps_four():
    _skip_unless_assets_available()
    good = _zhukov_top()
    host = _init_host("instance-decal-cap")
    try:
        iid = _plain_ambassador(host)
        host.set_instance_decals(iid, [good] * 6)
        assert host.instance_decal_override_size(iid) == 4
    finally:
        host.shutdown()


def test_unknown_iid_does_not_raise():
    _skip_unless_assets_available()
    good = _zhukov_top()
    host = _init_host("instance-decal-unknown")
    try:
        iid = _plain_ambassador(host)
        host.destroy_instance(iid)
        host.set_instance_decals(iid, [good])
        host.set_instance_decals(iid, None)
        host.set_instance_decals(host.InstanceId(), [good])
        assert host.instance_decal_override_size(iid) is None
    finally:
        host.shutdown()


def test_destroy_and_session_end_clear_overrides():
    _skip_unless_assets_available()
    good = _zhukov_top()
    host = _init_host("instance-decal-lifetime")
    try:
        doomed = _plain_ambassador(host)
        kept = _plain_ambassador(host)
        host.set_instance_decals(doomed, [good])
        host.set_instance_decals(kept, [good])
        host.destroy_instance(doomed)
        assert host.instance_decal_override_size(doomed) is None
        assert host.frame_state_debug()["instance_decal_overrides"] == 1
        host.frame()  # the override draws without error
    finally:
        host.shutdown()
    assert host.frame_state_debug()["instance_decal_overrides"] == 0
