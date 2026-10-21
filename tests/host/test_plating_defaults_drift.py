"""One source of plating defaults: C++ dauntless_plating::g_params (layered
damage phase 4 §2.5). `plating_dials.DEFAULTS` is only the headless fallback,
so it must equal what the real module reports, slot for slot in DIAL_ORDER.
Runs against the built `_dauntless_host`; skips only when it is absent.
"""
import pytest

pytest.importorskip("_dauntless_host")

import _dauntless_host as _h  # noqa: E402

from engine.appc import plating_dials  # noqa: E402
from engine import dev_hull_damage_tuning as tuning  # noqa: E402

KPARAMCOUNT = 32


def test_python_defaults_equal_the_native_defaults_in_dial_order():
    native = list(_h.plating_param_defaults())
    assert len(native) == KPARAMCOUNT
    order = plating_dials.DIAL_ORDER
    assert native[:len(order)] == pytest.approx(
        [plating_dials.DEFAULTS[k] for k in order], rel=1e-6)
    # the shortest-round-trip conversion lands exactly on the Python literals
    assert plating_dials.native_defaults() == plating_dials.DEFAULTS


def test_defaults_are_the_shipped_values_not_the_live_params():
    before = list(_h.plating_param_defaults())
    live = [v + 1.0 for v in before]
    _h.set_plating_params(live)
    try:
        assert list(_h.plating_param_defaults()) == before
    finally:
        _h.set_plating_params(before)


def test_rooms_near_distance_default_and_round_trip():
    assert _h.interior_near_gu_default() == tuning.DEFAULT_NEAR_GU
    saved = _h.interior_near_gu()
    try:
        _h.set_interior_near_gu(35.0)
        assert _h.interior_near_gu() == 35.0
    finally:
        _h.set_interior_near_gu(saved)
