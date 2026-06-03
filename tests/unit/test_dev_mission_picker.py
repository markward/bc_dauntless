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


# ---- tree payload and render -------------------------------------------

def _registry(families: list[FamilyEntry]) -> MissionRegistry:
    reg = MissionRegistry()
    reg.families = families
    return reg


def _mission(module: str, dir_name: str, display: str) -> MissionEntry:
    return MissionEntry(module_name=module, dir_name=dir_name, display_name=display)


def _episode(dir_name: str, display: str, missions: list[MissionEntry]) -> EpisodeEntry:
    return EpisodeEntry(dir_name=dir_name, display_name=display, missions=missions)


def _family(dir_name: str, display: str, episodes: list[EpisodeEntry]) -> FamilyEntry:
    return FamilyEntry(dir_name=dir_name, display_name=display, episodes=episodes)


def test_render_payload_emits_tree_after_open():
    fam = _family("Tutorial", "Tutorial",
                  [_episode("Ep1", "Episode 1",
                            [_mission("Custom.Tutorial.Ep1.M1Basic.M1Basic",
                                      "M1Basic", "M1Basic")])])
    p = MissionPicker(registry_getter=lambda: _registry([fam]), on_pick=Mock())
    p.open()
    payload = p.render_payload()
    assert payload is not None
    assert payload.startswith("setMissionPicker(")
    body = json.loads(payload[len("setMissionPicker("):-2])
    assert body["visible"] is True
    assert body["tree"] == [
        {
            "kind": "family",
            "label": "Tutorial",
            "children": [
                {
                    "kind": "episode",
                    "label": "Episode 1",
                    "children": [
                        {"kind": "mission",
                         "label": "M1Basic",
                         "module": "Custom.Tutorial.Ep1.M1Basic.M1Basic"},
                    ],
                },
            ],
        },
    ]


def test_render_payload_emits_hide_after_close():
    p = MissionPicker(registry_getter=lambda: _registry([]), on_pick=Mock())
    p.open()
    p.render_payload()  # consume the open emit
    p.close()
    payload = p.render_payload()
    assert payload is not None
    body = json.loads(payload[len("setMissionPicker("):-2])
    assert body == {"visible": False}


def test_render_payload_returns_none_when_state_unchanged():
    p = MissionPicker(registry_getter=lambda: _registry([]), on_pick=Mock())
    p.open()
    first = p.render_payload()
    second = p.render_payload()
    assert first is not None
    assert second is None


def test_render_payload_skip_episode_level_when_single_episode_named_Episode():
    """When a family has exactly one episode named 'Episode', flatten
    so family.children contains the mission rows directly."""
    fam = _family("Multiplayer", "Multiplayer",
                  [_episode("Episode", "Episode",
                            [_mission("Custom.Multiplayer.Episode.MpA.MpA",
                                      "MpA", "Multiplayer A")])])
    p = MissionPicker(registry_getter=lambda: _registry([fam]), on_pick=Mock())
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setMissionPicker("):-2])
    assert body["tree"] == [
        {
            "kind": "family",
            "label": "Multiplayer",
            "children": [
                {"kind": "mission",
                 "label": "Multiplayer A",
                 "module": "Custom.Multiplayer.Episode.MpA.MpA"},
            ],
        },
    ]


def test_render_payload_skip_episode_level_when_single_episode_named_dot():
    """Same flatten heuristic when the episode dir is '.'."""
    fam = _family("QuickBattle", "QuickBattle",
                  [_episode(".", ".",
                            [_mission("Custom.QuickBattle.QB1.QB1",
                                      "QB1", "QB1")])])
    p = MissionPicker(registry_getter=lambda: _registry([fam]), on_pick=Mock())
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setMissionPicker("):-2])
    assert body["tree"][0]["children"] == [
        {"kind": "mission",
         "label": "QB1",
         "module": "Custom.QuickBattle.QB1.QB1"},
    ]


def test_render_payload_does_not_flatten_when_multiple_episodes():
    """Two episodes — keep the episode level even if one is named 'Episode'."""
    fam = _family("Family", "Family", [
        _episode("Episode", "Episode",
                 [_mission("a", "A", "A")]),
        _episode("Other", "Other",
                 [_mission("b", "B", "B")]),
    ])
    p = MissionPicker(registry_getter=lambda: _registry([fam]), on_pick=Mock())
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setMissionPicker("):-2])
    family_children = body["tree"][0]["children"]
    # Both children are episode-kind, not flattened to mission rows.
    assert all(c["kind"] == "episode" for c in family_children)
    assert len(family_children) == 2
