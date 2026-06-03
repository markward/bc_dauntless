"""Unit tests for the TopWindow shim (engine/appc/top_window.py)."""
import pytest


def test_singleton_exists():
    from engine.appc import top_window
    assert top_window._the_top_window is not None


def test_factory_returns_singleton():
    from engine.appc import top_window
    a = top_window.TopWindow_GetTopWindow()
    b = top_window.TopWindow_GetTopWindow()
    assert a is b
    assert a is top_window._the_top_window


def test_reset_for_tests_replaces_singleton_with_default_state():
    from engine.appc import top_window
    tw = top_window._the_top_window
    tw._cutscene_active = True
    top_window.reset_for_tests()
    new_tw = top_window._the_top_window
    assert new_tw is not tw
    assert new_tw._cutscene_active is False
