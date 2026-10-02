"""Source-shape guards for text_capture.js (no JS runtime harness in this
repo -- brainstorm D6). Behaviour is covered by Mark's live check (spec S8).

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S3
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "native/assets/ui-cef/js/text_capture.js")
HTML = (ROOT / "native/assets/ui-cef/index.html")


def _src():
    return JS.read_text()


def _fn(src, name):
    """Body of `function name(...) {...}` or `window.name = function (...) {...}`."""
    m = re.search(r"(function\s+%s\s*\(|window\.%s\s*=\s*function\s*\()" % (name, name), src)
    assert m, name
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[i:j + 1]
    raise AssertionError(name)


def test_loaded_after_pause_menu_and_before_the_panels():
    html = HTML.read_text()
    pm = html.index('src="js/pause_menu.js"')
    tc = html.index('src="js/text_capture.js"')
    spv = html.index('src="js/ship_property_viewer.js"')
    assert pm < tc < spv


def test_editable_excludes_checkbox_range_and_buttons():
    body = _fn(_src(), "isEditable")
    types = re.search(r"TEXT_TYPES\s*=\s*\[([^\]]*)\]", _src()).group(1)
    for t in ("text", "search", "number", "email", "url", "password", "tel"):
        assert "'%s'" % t in types
    for t in ("checkbox", "range", "button", "submit", "radio"):
        assert t not in types
    assert "TEXTAREA" in body and "isContentEditable" in body


def test_listeners_are_capture_phase():
    src = _src()
    for ev in ("focusin", "blur", "keydown"):
        m = re.search(r"addEventListener\('%s',.*?\},\s*true\)" % ev, src, re.S)
        assert m, ev


def test_release_is_reported_on_capture_phase_blur_not_focusout():
    """Live bug (2026-10-02): the SPV row's own `blur` handler removes the
    input from the DOM, and Chromium fires `blur` BEFORE `focusout` -- so a
    document `focusout` listener never saw the detached field, `kbd/blur` was
    never sent, and capture stuck on until the panel closed (no orbit, game
    deaf). A capture-phase `blur` listener on the document runs before the
    target's own handlers, while the field is still attached."""
    src = _src()
    assert "addEventListener('focusout'" not in src
    block = src[src.index("addEventListener('blur'"):src.index("'keydown'")]
    assert "dauntlessEvent('kbd/blur')" in block


def test_focus_reports_owner_and_saves_value():
    src = _src()
    block = src[src.index("'focusin'"):src.index("addEventListener('blur'")]
    assert "saved.set(" in block
    assert "dauntlessEvent('kbd/focus:' + ownerOf(" in block
    assert "closest('[data-panel]')" in _fn(src, "ownerOf")


def test_blur_to_another_editable_sends_nothing():
    src = _src()
    block = src[src.index("addEventListener('blur'"):src.index("'keydown'")]
    assert block.index("isEditable(e.relatedTarget)") < block.index("dauntlessEvent('kbd/blur')")


def test_escape_restores_before_blurring_and_stops_propagation():
    src = _src()
    assert _fn(src, "revertAndBlur").index("setValue(") < _fn(src, "revertAndBlur").index(".blur()")
    block = src[src.index("'keydown'"):]
    esc = block[block.index("'Escape'"):block.index("'Enter'")]
    assert "stopPropagation()" in esc and "revertAndBlur(" in esc


def test_enter_blurs_except_in_textarea():
    block = _src()[_src().index("'Enter'"):]
    assert "TEXTAREA" in block[:200] and ".blur()" in block[:200]


def test_forced_blur_reverts():
    body = _fn(_src(), "__dauntlessBlurText")
    assert "revertAndBlur(" in body
    assert "revertAndBlur(" in _fn(_src(), "__dauntlessTextCancel")
    assert ".blur()" in _fn(_src(), "__dauntlessTextCommit")
