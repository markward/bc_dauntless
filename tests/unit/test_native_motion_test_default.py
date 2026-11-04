"""Tests fly kernel M by default, as the game does (native motion phase 2,
closing review I1).

conftest's per-test reset calls ``native_combat.reset()``, which turns the
motion switch off, so it must call ``native_motion.configure()`` again;
otherwise every test calling ``tick_all_ship_motion`` directly would fly the
Python copy and a kernel regression would be invisible to the gate. This file
has no fixture of its own that touches the switch.
"""
import os

from engine.appc import native_motion


def test_tests_fly_kernel_m_by_default():
    # The switch, not enabled(): a bare test has no native transform store.
    want = os.environ.get("DAUNTLESS_NATIVE_MOTION") != "0"
    assert native_motion._switch is want
