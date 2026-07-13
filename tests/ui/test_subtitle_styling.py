"""The caption box and episode title card must stay on the house tokens.

sdk_mirror.css was the last place in the UI still on bare `sans-serif` with a
blue palette; these assertions stop it coming back, and pin the DOM contract
between index.html and sdk_mirror.js.
Spec: docs/superpowers/specs/2026-07-13-subtitle-episode-title-visual-language-design.md
"""
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"
CSS = (UI / "css" / "sdk_mirror.css").read_text()
JS = (UI / "js" / "sdk_mirror.js").read_text()
HTML = (UI / "index.html").read_text()


def _rule(css: str, selector: str) -> str:
    """Return the declaration block for `selector` (raises if absent)."""
    start = css.index(selector + " {") + len(selector) + 2
    return css[start:css.index("}", start)]


def test_caption_box_uses_antonio_not_bare_sans_serif():
    assert 'font-family: "Antonio", sans-serif;' in _rule(CSS, "#sdk-subtitle")


def test_caption_box_uses_house_body_and_salmon_rule():
    rule = _rule(CSS, "#sdk-subtitle")
    assert "background: rgba(10, 10, 16, 0.85);" in rule
    assert "border-left: 4px solid rgb(216, 94, 86);" in rule
    assert "border-top-right-radius: 14px;" in rule


def test_old_blue_palette_is_gone():
    for dead in ("#3a6bb8", "#9cc4ff", "rgba(20, 40, 80"):
        assert dead not in _rule(CSS, "#sdk-subtitle")
        assert dead not in _rule(CSS, ".sdk-subtitle__speaker")


def test_speaker_is_its_own_block_in_chrome_orange():
    rule = _rule(CSS, ".sdk-subtitle__speaker")
    assert "display: block;" in rule
    assert "color: #d88450;" in rule
    assert "text-transform: uppercase;" in rule


def test_speaker_has_no_colon_suffix_in_js():
    # The speaker is a block above the line now, not an inline "LIU:" prefix.
    assert '":</span>' not in JS


def test_episode_card_uses_house_purple_eyebrow():
    assert "color: rgb(147, 103, 255);" in _rule(CSS, ".sdk-episode__eyebrow")


@pytest.mark.parametrize("selector", [
    "#sdk-episode-title", ".sdk-episode__eyebrow", ".sdk-episode__title",
])
def test_episode_card_rules_exist(selector):
    assert selector + " {" in CSS


def test_fades_are_not_css_transitions():
    # Opacity is pushed per-frame from Python so fades freeze under pause.
    # A CSS transition/animation here would run on wall-clock -- see the spec.
    for banned in ("transition", "animation", "@keyframes"):
        assert banned not in CSS


@pytest.mark.parametrize("dom_id", ["sdk-episode-title"])
def test_episode_element_exists_in_index_html(dom_id):
    assert 'id="' + dom_id + '"' in HTML


@pytest.mark.parametrize("cls", ["sdk-episode__eyebrow", "sdk-episode__title"])
def test_episode_children_exist_in_index_html(cls):
    assert 'class="' + cls + '"' in HTML


def test_js_reads_the_new_payload_keys():
    for key in ("title_eyebrow", "title_text", "title_opacity", "lines"):
        assert key in JS
