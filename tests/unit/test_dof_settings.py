"""DOF and the modern lens flare ride the Camera Realism LEVEL.

Off / Medium / High. Medium (the default) is HDR, filmic, motion blur and the
modern lens flare at half strength with depth of field OFF; High adds DOF and
the full-strength flare. The fan-out lives in the settings_store row.
"""
from unittest.mock import Mock

import pytest

from engine.settings_store import setting_for
from engine.ui.configuration_panel import (
    CAMERA_REALISM_HIGH, CAMERA_REALISM_MEDIUM, CAMERA_REALISM_OFF,
)


def _apply(level):
    r = Mock()
    ctx = Mock(r=r)
    setting_for("camera_realism").apply(ctx, level)
    return r


def test_medium_turns_dof_off_and_halves_the_flare():
    r = _apply(CAMERA_REALISM_MEDIUM)
    r.set_dof_enabled.assert_called_once_with(False)
    r.set_hdr_lens_flare_enabled.assert_called_once_with(True)
    r.set_hdr_lens_flare_strength_scale.assert_called_once_with(0.5)
    for name in ("set_hdr_enabled", "set_filmic_enabled",
                 "set_motion_blur_enabled"):
        getattr(r, name).assert_called_once_with(True)


def test_high_turns_dof_on_at_full_flare_strength():
    r = _apply(CAMERA_REALISM_HIGH)
    r.set_dof_enabled.assert_called_once_with(True)
    r.set_hdr_lens_flare_enabled.assert_called_once_with(True)
    r.set_hdr_lens_flare_strength_scale.assert_called_once_with(1.0)


def test_off_turns_every_member_off():
    r = _apply(CAMERA_REALISM_OFF)
    for name in ("set_hdr_enabled", "set_filmic_enabled",
                 "set_motion_blur_enabled", "set_hdr_lens_flare_enabled",
                 "set_dof_enabled"):
        getattr(r, name).assert_called_once_with(False)


def test_reset_restores_medium():
    from engine.settings_store import resolve_reset_default
    assert resolve_reset_default(setting_for("camera_realism"), Mock()) \
        == CAMERA_REALISM_MEDIUM


@pytest.mark.parametrize("on,dof,expected", [
    (False, False, CAMERA_REALISM_OFF),
    (True, False, CAMERA_REALISM_MEDIUM),
    (True, True, CAMERA_REALISM_HIGH),
])
def test_display_default_reads_the_live_level(on, dof, expected):
    from engine.settings_store import resolve_default
    r = Mock()
    r.filmic_enabled.return_value = on
    r.motion_blur_enabled.return_value = on
    r.hdr_lens_flare_enabled.return_value = on
    r.dof_enabled.return_value = dof
    assert resolve_default(setting_for("camera_realism"), Mock(r=r)) == expected
