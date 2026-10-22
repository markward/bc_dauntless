"""Developer Options -> "Hull damage" tab (layered damage phase 4 §2.5):
value-cycling rows over the plating dials and the Python damage knobs, an
interior toggle, the rooms near distance and "Reset hull damage dials".
Developer-only, like the rest of the panel."""
import json

import pytest

from engine import dev_hull_damage_tuning as tuning
from engine import dev_mode, renderer
from engine.appc import hull_wear, plating_dials
from engine.ui.developer_options_panel import DeveloperOptionsPanel

JS = "native/assets/ui-cef/js/developer_options.js"


@pytest.fixture(autouse=True)
def _dev_on(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    pushed = []
    monkeypatch.setattr(renderer, "set_plating_params",
                        lambda params: pushed.append(list(params)))
    monkeypatch.setattr(renderer, "set_interior_near_gu", lambda v: None,
                        raising=False)
    plating_dials.reset()
    tuning.reset()
    pushed.clear()
    yield pushed
    tuning.reset()
    plating_dials.reset()


def _payload(p):
    js = p.render_payload()
    assert js is not None
    return json.loads(js[js.index("(") + 1: js.rindex(")")])


def _open_on_tab():
    p = DeveloperOptionsPanel()
    p.open()
    assert p.dispatch_event("tab:hull_damage")
    return p


def _rows(data):
    return {r["key"]: r for r in data["hull_damage"]}


def test_the_hull_damage_tab_exists_with_its_label():
    p = DeveloperOptionsPanel()
    assert ("hull_damage", "Hull damage") in p._tabs


def test_rows_are_in_the_payload_and_focusable():
    p = _open_on_tab()
    rows = _rows(_payload(p))
    assert rows["hull_breach_wear"]["value"] == "4.5"
    assert rows["hull_reset"]["label"] == "Reset hull damage dials"
    foc = p._focusables()
    for key in rows:
        assert ("ctrl", key) in foc


def test_rows_are_absent_outside_developer_mode(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    p = _open_on_tab()
    assert _payload(p)["hull_damage"] == []
    assert not [f for f in p._focusables()
                if f[0] == "ctrl" and f[1].startswith("hull_")]
    assert p.dispatch_event("action:hull_breach_wear") is False


def test_cycling_a_row_pushes_the_value_and_re_emits(_dev_on):
    pushed = _dev_on
    p = _open_on_tab()
    _payload(p)
    assert p.dispatch_event("action:hull_breach_wear") is True
    slot = plating_dials.DIAL_ORDER.index("breach_wear")
    assert pushed[-1][slot] == 6.75
    assert _rows(_payload(p))["hull_breach_wear"]["value"] == "6.75"


def test_a_dial_key_step_shows_on_the_open_panel():
    p = _open_on_tab()
    _payload(p)
    plating_dials._step("soot", +1)
    assert _rows(_payload(p))["hull_soot"]["value"] == "0.85"


def test_enter_on_a_value_row_cycles_it():
    class _Keys:
        KEY_UP = 1; KEY_DOWN = 2; KEY_SPACE = 5; KEY_ENTER = 6

    class _Reader:
        keys = _Keys()

        def __init__(self):
            self._pressed = set()

        def press(self, k):
            self._pressed.add(k)

        def key_pressed(self, k):
            if k in self._pressed:
                self._pressed.discard(k)
                return True
            return False

    p = _open_on_tab()
    r = _Reader()
    for _ in range(p._focusables().index(("ctrl", "hull_phaser_rate")) + 1):
        r.press(r.keys.KEY_DOWN)
        p.handle_input(r)
    r.press(r.keys.KEY_ENTER)
    p.handle_input(r)
    assert hull_wear.PHASER_RATE == 1.5


def test_interior_row_is_a_toggle():
    p = _open_on_tab()
    assert p.dispatch_event("toggle:hull_interior") is True
    assert plating_dials.current()["interior"] == 0.0
    assert _rows(_payload(p))["hull_interior"]["value"] is False


def test_reset_restores_defaults():
    p = _open_on_tab()
    p.dispatch_event("action:hull_breach_wear")
    p.dispatch_event("action:hull_phaser_rate")
    p.dispatch_event("toggle:hull_interior")
    assert p.dispatch_event("action:hull_reset") is True
    cur = plating_dials.current()
    assert cur["breach_wear"] == plating_dials.defaults()["breach_wear"]
    assert cur["interior"] == 1.0
    assert hull_wear.PHASER_RATE == hull_wear.DEFAULT_PHASER_RATE
    rows = _rows(_payload(p))
    assert rows["hull_breach_wear"]["value"] == "4.5"


def test_js_renders_the_hull_damage_tab():
    text = open(JS).read()
    assert "function _doRenderHullDamageBody(state, focusables) {" in text
    assert ("(state.selected_tab === 'hull_damage')  ? "
            "_doRenderHullDamageBody(state, focusables)") in text
    body = text[text.index("function _doRenderHullDamageBody"):]
    assert "_doValueRow(r.label, r.key, String(r.value), isFoc(r.key))" in body
    assert "_doToggleRow(r.label, r.key, r.value, isFoc(r.key))" in body
    assert "_doActionRow(r.label, r.key, 'Reset', isFoc(r.key))" in body
    assert "if (state.selected_tab === 'hull_damage') {" in text
