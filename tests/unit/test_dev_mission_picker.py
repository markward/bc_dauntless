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
