"""DOF rides the existing Camera Realism master.

No new player-facing row and no schema migration: the master already owns
HDR, the filmic grade, motion blur and modern lens flares, and DOF is squarely
that family.
"""
from engine.ui.configuration_panel import MASTER_TOGGLES


def _appliers_for(key):
    for k, _label, appliers in MASTER_TOGGLES:
        if k == key:
            return appliers
    raise AssertionError(f"no master toggle {key!r}")


def test_dof_is_a_member_of_camera_realism():
    assert "dof" in _appliers_for("camera_realism")


def test_camera_realism_still_owns_its_original_four():
    appliers = _appliers_for("camera_realism")
    for name in ("hdr", "filmic", "motion_blur", "hdr_lens_flare"):
        assert name in appliers


def test_schema_version_is_unchanged():
    """Adding an applier to an existing master must not need a migration."""
    from engine.settings_store import SCHEMA_VERSION
    assert SCHEMA_VERSION == 2


def test_the_master_fans_out_to_set_dof_enabled():
    import inspect
    import engine.settings_store as store
    src = inspect.getsource(store)
    assert "set_dof_enabled" in src, (
        "camera_realism's fan-out never reaches the DOF toggle"
    )
