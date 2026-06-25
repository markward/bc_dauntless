"""Tests for QuickBattleSetupPanel — the on-theme "Quick Battle Setup" shell.

T1 scope: header + a single Ships tab + Start/Close, no body content yet.
Mirrors test_developer_options_panel.py / test_configuration_panel.py: state,
open/close, dispatch_event branches, render_payload snapshot dedup, and ESC.
"""
import json

import pytest

from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel


@pytest.fixture
def panel():
    return QuickBattleSetupPanel()


def _body(payload):
    return json.loads(payload[len("setQuickBattleSetup("):-2])


# ---- construction / open-close -------------------------------------------

def test_name_is_quick_battle_setup(panel):
    assert panel.name == "quick-battle-setup"


def test_initially_closed(panel):
    assert panel.is_open() is False


def test_default_selected_tab_is_ships(panel):
    panel.open()
    body = _body(panel.render_payload())
    assert body["selected_tab"] == "ships"


def test_open_close_round_trip(panel):
    panel.open()
    assert panel.is_open() is True
    panel.close()
    assert panel.is_open() is False


# ---- dispatch_event -------------------------------------------------------

def test_dispatch_tab_ships_selects_tab(panel):
    panel.open()
    assert panel.dispatch_event("tab:ships") is True
    body = _body(panel.render_payload())
    assert body["selected_tab"] == "ships"


def test_dispatch_unknown_tab_returns_false(panel):
    panel.open()
    assert panel.dispatch_event("tab:nope") is False


def test_dispatch_close_closes(panel):
    panel.open()
    assert panel.dispatch_event("close") is True
    assert panel.is_open() is False


def test_dispatch_start_returns_true_and_calls_callback(panel):
    calls = []
    p = QuickBattleSetupPanel(on_start=lambda: calls.append("start"))
    p.open()
    assert p.dispatch_event("start") is True
    assert calls == ["start"]


def test_dispatch_start_without_callback_is_noop(panel):
    panel.open()
    # No on_start wired — Start is still "handled" (later task wires it).
    assert panel.dispatch_event("start") is True


def test_dispatch_unknown_returns_false(panel):
    panel.open()
    assert panel.dispatch_event("bogus") is False


# ---- render_payload -------------------------------------------------------

def test_render_payload_shape(panel):
    panel.open()
    body = _body(panel.render_payload())
    assert body["open"] is True
    assert body["selected_tab"] == "ships"
    assert body["tabs"] == [{"id": "ships", "label": "Ships"}]


def test_render_payload_dedups(panel):
    panel.open()
    assert panel.render_payload() is not None
    assert panel.render_payload() is None


def test_render_payload_close_emits_hide(panel):
    panel.open()
    panel.render_payload()
    panel.close()
    out = panel.render_payload()
    assert _body(out) == {"open": False}


def test_invalidate_re_emits(panel):
    panel.open()
    first = panel.render_payload()
    assert panel.render_payload() is None
    panel.invalidate()
    assert panel.render_payload() == first


# ---- keyboard -------------------------------------------------------------

def test_handle_key_esc_when_open_closes(panel):
    panel.open()
    panel.handle_key_esc()
    assert panel.is_open() is False


def test_handle_key_esc_when_closed_is_noop(panel):
    panel.handle_key_esc()
    assert panel.is_open() is False
