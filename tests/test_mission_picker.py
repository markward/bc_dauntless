"""MissionPicker — opens a centered modal, closes on pick / cancel / ESC."""
import pytest

from engine.missions.discovery import (
    MissionRegistry, FamilyEntry, EpisodeEntry, MissionEntry,
)
from engine.mission_picker import MissionPicker


@pytest.fixture
def fake_dom(monkeypatch):
    from engine.ui import bindings as bindings_module
    from engine.ui._dom import FakeDom
    dom = FakeDom()
    monkeypatch.setattr(bindings_module, "_active_dom", dom)
    return dom


@pytest.fixture
def two_family_registry():
    return MissionRegistry(families=[
        FamilyEntry(
            dir_name="Tutorial", display_name="Tutorial",
            episodes=[EpisodeEntry(
                dir_name="Episode", display_name="Episode",
                missions=[
                    MissionEntry(
                        module_name="Custom.Tutorial.Episode.M1.M1",
                        dir_name="M1", display_name="Basic Maneuvers"),
                    MissionEntry(
                        module_name="Custom.Tutorial.Episode.M2.M2",
                        dir_name="M2", display_name="Objects"),
                ],
            )],
        ),
        FamilyEntry(
            dir_name="Maelstrom", display_name="Maelstrom",
            episodes=[
                EpisodeEntry(
                    dir_name="Episode1", display_name="The Long Night",
                    missions=[MissionEntry(
                        module_name="Maelstrom.Episode1.E1M1.E1M1",
                        dir_name="E1M1", display_name="Shakedown")],
                ),
                EpisodeEntry(
                    dir_name="Episode2", display_name="The Second Wave",
                    missions=[MissionEntry(
                        module_name="Maelstrom.Episode2.E2M0.E2M0",
                        dir_name="E2M0", display_name="Prologue")],
                ),
            ],
        ),
    ])


def _header_titles(fake_dom):
    """All visible collapsible header titles in the DOM, by class bc-title."""
    return [
        fake_dom.element(eid).text
        for eid, el in fake_dom._elements.items()
        if "bc-title" in el.classes
    ]


def _buttons_with_text(fake_dom, text):
    return [
        eid for eid, el in fake_dom._elements.items()
        if el.text == text and "bc-button" in el.classes
    ]


def test_open_creates_centered_panel(fake_dom, two_family_registry):
    picker = MissionPicker(
        registry=two_family_registry,
        on_load=lambda name: None,
        on_cancel=lambda: None,
    )
    picker.open()
    assert picker.is_open()
    panels = list(fake_dom._panels.values())
    assert len(panels) == 1
    assert panels[0].anchor == "center"


def test_open_builds_family_and_episode_collapsibles(fake_dom, two_family_registry):
    picker = MissionPicker(
        registry=two_family_registry,
        on_load=lambda name: None,
        on_cancel=lambda: None,
    )
    picker.open()
    titles = _header_titles(fake_dom)
    # Family + episode rows.
    assert "Tutorial" in titles
    assert "Maelstrom" in titles
    assert "The Long Night" in titles
    assert "The Second Wave" in titles
    # Tutorial's single "Episode" episode-row is collapsed away (skipped).
    assert "Episode" not in titles


def test_picking_a_mission_closes_panel_and_invokes_callback(
        fake_dom, two_family_registry):
    chosen: list[str] = []
    picker = MissionPicker(
        registry=two_family_registry,
        on_load=lambda name: chosen.append(name),
        on_cancel=lambda: None,
    )
    picker.open()
    btn_ids = _buttons_with_text(fake_dom, "Basic Maneuvers")
    assert len(btn_ids) == 1
    fake_dom.fire_click(btn_ids[0])
    # Click only queues the action — close + callback fire on drain.
    assert picker.is_open()
    assert chosen == []
    picker.drain()
    assert chosen == ["Custom.Tutorial.Episode.M1.M1"]
    assert not picker.is_open()
    # Panel is hidden (kept alive across opens), not destroyed.
    assert fake_dom._panels


def test_cancel_button_closes_and_invokes_on_cancel(
        fake_dom, two_family_registry):
    cancelled: list[int] = []
    picker = MissionPicker(
        registry=two_family_registry,
        on_load=lambda name: None,
        on_cancel=lambda: cancelled.append(1),
    )
    picker.open()
    cancel_ids = _buttons_with_text(fake_dom, "Cancel")
    assert len(cancel_ids) == 1
    fake_dom.fire_click(cancel_ids[0])
    # Click only queues — drain runs the close + callback.
    assert picker.is_open()
    assert cancelled == []
    picker.drain()
    assert cancelled == [1]
    assert not picker.is_open()


def test_handle_key_esc_cancels_when_open(fake_dom, two_family_registry):
    cancelled: list[int] = []
    picker = MissionPicker(
        registry=two_family_registry,
        on_load=lambda name: None,
        on_cancel=lambda: cancelled.append(1),
    )
    picker.open()
    picker.handle_key_esc()
    assert cancelled == [1]
    assert not picker.is_open()


def test_handle_key_esc_noop_when_closed(fake_dom, two_family_registry):
    picker = MissionPicker(
        registry=two_family_registry,
        on_load=lambda name: None,
        on_cancel=lambda: pytest.fail("on_cancel must not fire"),
    )
    picker.handle_key_esc()
    assert not picker.is_open()


def test_close_is_idempotent(fake_dom, two_family_registry):
    picker = MissionPicker(
        registry=two_family_registry,
        on_load=lambda name: None,
        on_cancel=lambda: None,
    )
    picker.open()
    picker.close()
    picker.close()       # second call must not raise
    assert not picker.is_open()
