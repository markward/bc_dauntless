"""Tests for MissionPicker — the dev-only mission loader panel.

The picker subclasses engine.ui.panel.Panel and is pumped by
PanelRegistry like the other panels. These tests cover construction,
state transitions, payload emission, and dispatch — without touching
CEF or _dauntless_host.
"""
import json
from unittest.mock import Mock

import pytest

from engine.dev_mission_picker import MissionPicker
from engine.missions import FamilyEntry, EpisodeEntry, MissionEntry, MissionRegistry


# ---- construction --------------------------------------------------------

def test_constructor_does_not_call_registry_getter():
    getter = Mock()
    on_pick = Mock()
    MissionPicker(registry_getter=getter, on_pick=on_pick)
    assert getter.call_count == 0


def test_name_is_mission_picker():
    p = MissionPicker(registry_getter=Mock(), on_pick=Mock())
    assert p.name == "mission-picker"


def test_initially_closed():
    p = MissionPicker(registry_getter=Mock(), on_pick=Mock())
    assert p.is_open() is False


# ---- transitions and dispatch -------------------------------------------

def _empty_registry() -> MissionRegistry:
    return MissionRegistry()


def test_open_resolves_registry_exactly_once():
    getter = Mock(return_value=_empty_registry())
    p = MissionPicker(registry_getter=getter, on_pick=Mock())
    p.open()
    p.open()
    p.open()
    assert getter.call_count == 1
    assert p.is_open() is True


def test_close_flips_visible():
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=Mock())
    p.open()
    p.close()
    assert p.is_open() is False


def test_dispatch_pick_calls_on_pick_and_closes():
    on_pick = Mock()
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=on_pick)
    p.open()
    handled = p.dispatch_event("pick:Custom.Foo.Bar")
    assert handled is True
    on_pick.assert_called_once_with("Custom.Foo.Bar")
    assert p.is_open() is False


def test_dispatch_cancel_closes_without_calling_on_pick():
    on_pick = Mock()
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=on_pick)
    p.open()
    handled = p.dispatch_event("cancel")
    assert handled is True
    assert on_pick.call_count == 0
    assert p.is_open() is False


def test_dispatch_unknown_returns_false_and_does_not_close():
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=Mock())
    p.open()
    handled = p.dispatch_event("bogus")
    assert handled is False
    assert p.is_open() is True


def test_handle_key_esc_when_open_closes():
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=Mock())
    p.open()
    p.handle_key_esc()
    assert p.is_open() is False


def test_handle_key_esc_when_closed_is_noop():
    p = MissionPicker(registry_getter=lambda: _empty_registry(), on_pick=Mock())
    p.handle_key_esc()
    assert p.is_open() is False
