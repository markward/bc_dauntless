# tests/unit/test_quick_battle_setup_page.py
"""Source-shape guards for the ported page (no JS runtime, as the keyboard
capture work decided: spec 2026-10-02-cef-text-input-keyboard-capture-design D6)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"
JS = (ROOT / "js" / "quick_battle_setup.js").read_text()
CSS = (ROOT / "css" / "quick_battle_setup.css").read_text()
HTML = (ROOT / "index.html").read_text()
SECTION = HTML.split('<section id="quick-battle-setup"', 1)[1].split("</section>", 1)[0]


def test_entry_points_exist():
    for fn in ("setQuickBattleCatalog", "setQuickBattleSetup", "qbEscape"):
        assert re.search(r"function\s+%s\s*\(" % fn, JS), fn


def test_section_declares_panel_for_key_capture():
    assert 'data-panel="quick-battle-setup"' in SECTION


def test_no_forbidden_offscreen_cef_constructs():
    for text in (JS, SECTION):
        assert "<select" not in text
        assert "draggable" not in text
        assert not re.search(r"\btitle\s*=", text)


def test_text_inputs_commit_on_change_not_keydown():
    assert "'change'" in JS or '"change"' in JS
    assert "keydown" not in JS


def test_every_event_verb_python_handles_is_used():
    verbs = ["era:", "species:", "select:", "add:", "set-player:", "target:", "group-new",
             "details:", "draft:", "draft-update", "draft-cancel", "rename:", "group-delete:",
             "variant:", "move:", "remove:", "preset-load:", "preset-save:", "preset-delete:",
             "confirm", "cancel", "start", "close", "esc"]
    for v in verbs:
        assert "quick-battle-setup/" + v in JS, v


def test_difficulty_row_and_spike_copy_present():
    # "Adding here" and "off scale" are the spike's literals (app.js); the
    # upper case on screen comes from CSS text-transform, as in the spike.
    for copy in ("Difficulty", "+ New group",
                 "No ships yet", "Load preset", "Out of era", "off scale",
                 "No hardpoint data for this entry.", "Start Battle"):
        assert copy in JS or copy in SECTION or copy in CSS, copy


def _fn(name):
    return JS.split("function " + name + "(", 1)[1].split("\nfunction ", 1)[0]


def test_add_target_is_picked_on_the_sheet_not_by_clicking_a_group():
    # The group picker on the ship sheet replaced click-a-group-to-target and
    # its "Adding here" tag.
    assert "Adding here" not in JS and "qbs-group--target" not in JS + CSS
    assert ".qbs-group'" not in _fn("qbsClick")
    picker = _fn("qbsAddGroupMenu")
    assert "QBS.setup.groups" in picker and "'target'" in picker
    assert re.search(r"qbsOpenMenu\(anchor,\s*h,\s*true\)", picker)   # drop-up
    assert "data-action=\"add-group-menu\"" in _fn("renderDetail")


def test_add_sends_ship_group_and_quantity():
    assert re.search(r"'quick-battle-setup/add:'\s*\+\s*qbsEnc\(arg\)\s*\+\s*':'\s*\+\s*"
                     r"QBS\.setup\.target\s*\+\s*':'\s*\+\s*qbsQty\(arg\)", JS)
    step = _fn("qbsStepQty")
    assert "add_max" in step and "Math.max(1" in step


def test_quantity_is_remembered_per_ship_type():
    # Bird of Prey at 3, Vor'cha shows 1, back to the Bird of Prey shows 3:
    # keyed by the lower-cased ship id, unset reads 1, cleared on close.
    assert "QBS.qty[String(id || '').toLowerCase()] || 1" in _fn("qbsQty")
    assert "QBS.qty[String(id).toLowerCase()] =" in _fn("qbsStepQty")
    assert "QBS.setup.selected" in _fn("qbsStepQty")
    assert "qbsQty(sh.id)" in _fn("renderDetail")
    assert "QBS.qty = {}" in _fn("setQuickBattleSetup")


def test_catalog_carries_the_add_cap():
    from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel
    panel = QuickBattleSetupPanel(catalog_fn=lambda: [], qb_module=None)
    assert panel._catalog_payload()["add_max"] == QuickBattleSetupPanel.ADD_MAX == 10


def test_difficulty_segments_render_python_labels_low_medium_high():
    # The segment labels are the panel's (catalog.difficulties, Task 9), not
    # page literals: the row must render that table, and the table must say
    # Low / Medium / High in that order.
    from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel
    assert re.search(r"qbsSeg\('difficulty',\s*c\.difficulties", JS)
    panel = QuickBattleSetupPanel(catalog_fn=lambda: [], qb_module=None)
    labels = [d["label"] for d in panel._catalog_payload()["difficulties"]]
    assert labels == ["Low", "Medium", "High"]


def test_css_scoped_and_prefixed():
    assert "qbx-" not in CSS and "qbs-" in CSS


def test_save_form_click_away_abandons_instead_of_saving():
    # A mousedown outside the popover while the preset-name field is focused
    # abandons the edit (text_capture's cancel path) and the change handler
    # honours that, so a click away never saves (only Enter or Save do).
    assert re.search(r"addEventListener\('mousedown',\s*qbsMouseDown,\s*true\)", JS)
    body = JS.split("function qbsMouseDown", 1)[1].split("\nfunction ", 1)[0]
    assert "saveCancelled = true" in body and "__dauntlessTextCancel" in body
    assert "preventDefault()" in body
    save = JS.split("function qbsSavePreset", 1)[1].split("\nfunction ", 1)[0]
    assert "saveCancelled" in save
    assert "saveCancelled = false" in JS.split("function qbsSaveMenu", 1)[1].split("\nfunction ", 1)[0]


def test_confirm_bolds_the_name_between_python_before_and_after():
    assert re.search(r"qbsEsc\(c\.before\)\s*\+\s*'<b>'\s*\+\s*qbsEsc\(c\.name\)"
                     r"\s*\+\s*'</b>'\s*\+\s*qbsEsc\(c\.after\)", JS)
    assert "indexOf(name)" not in JS


def test_no_noop_stop_propagation():
    assert "stopPropagation" not in JS
