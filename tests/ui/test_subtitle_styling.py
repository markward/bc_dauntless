"""The caption box and episode title card must stay on the house tokens.

sdk_mirror.css was the last place in the UI still on bare `sans-serif` with a
blue palette; these assertions stop it coming back, and pin the DOM contract
between index.html and sdk_mirror.js.
Spec: docs/superpowers/specs/2026-07-13-subtitle-episode-title-visual-language-design.md
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"
CSS = (UI / "css" / "sdk_mirror.css").read_text()
JS = (UI / "js" / "sdk_mirror.js").read_text()
JS_PATH = UI / "js" / "sdk_mirror.js"
HTML = (UI / "index.html").read_text()

NODE = shutil.which("node")

# Comments (including the header block) can legitimately mention a selector or
# the words "transition"/"animation" in prose -- strip them before searching
# so a rule lookup or a banned-word check never keys off a /* ... */ block.
_CSS_NO_COMMENTS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)


def _rule(css: str, selector: str) -> str:
    """Return the declaration block for `selector` (raises if absent)."""
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    start = stripped.index(selector + " {") + len(selector) + 2
    return stripped[start:stripped.index("}", start)]


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


def _vh(rule: str, prop: str) -> float:
    m = re.search(prop + r"\s*:\s*([\d.]+)vh", rule)
    assert m, "%r not found as a vh value in rule" % prop
    return float(m.group(1))


# A three-line #sdk-subtitle caption (padding 10+12, the speaker block's
# 13px + 3px margin, three 17px/1.25 lines) is ~14vh tall -- see the
# design-review finding this test pins and the matching comment on
# #sdk-episode-title in sdk_mirror.css.
THREE_LINE_CAPTION_HEIGHT_VH = 14.0


def test_episode_card_clears_a_three_line_caption_box():
    # Finding 1: E2M1's Ep2Cutscene.py appends EpisodeTitleAction and chains
    # three of Saffi's spoken lines right after it, so the title card and a
    # long, wrapped caption ARE on screen together in a shipped mission. The
    # card's `bottom` must clear the caption box's `bottom` plus a
    # worst-case three-line caption, or the card's opaque glyphs paint over
    # the caption box. A future edit that lowers the card back toward the
    # caption band must fail this.
    caption_bottom_vh = _vh(_rule(CSS, "#sdk-subtitle"), "bottom")
    episode_bottom_vh = _vh(_rule(CSS, "#sdk-episode-title"), "bottom")
    assert episode_bottom_vh >= caption_bottom_vh + THREE_LINE_CAPTION_HEIGHT_VH


@pytest.mark.parametrize("selector", [
    "#sdk-episode-title", ".sdk-episode__eyebrow", ".sdk-episode__title",
])
def test_episode_card_rules_exist(selector):
    assert selector + " {" in CSS


def test_fades_are_not_css_transitions():
    # Opacity is pushed per-frame from Python and is authoritative; a CSS
    # transition/animation here would interpolate between those per-frame
    # writes and fight the Python-driven fade (smearing/lagging it) -- see
    # the spec. (It would NOT make fades freeze under pause -- dwell and
    # fade both run on time.monotonic() regardless of this rule.)
    # Matched as declarations, not as prose: the header comment must stay free to
    # explain WHY the rule exists.
    assert not re.search(r"\btransition\s*:", _CSS_NO_COMMENTS)
    assert not re.search(r"\banimation\s*:", _CSS_NO_COMMENTS)
    assert "@keyframes" not in _CSS_NO_COMMENTS


@pytest.mark.parametrize("dom_id", ["sdk-episode-title"])
def test_episode_element_exists_in_index_html(dom_id):
    assert 'id="' + dom_id + '"' in HTML


@pytest.mark.parametrize("cls", ["sdk-episode__eyebrow", "sdk-episode__title"])
def test_episode_children_exist_in_index_html(cls):
    assert 'class="' + cls + '"' in HTML


def test_js_reads_the_new_payload_keys():
    for key in ("title_eyebrow", "title_text", "title_opacity", "lines"):
        assert key in JS


_NODE_HARNESS = r"""
const fs = require("fs");

function makeEl() {
  return {hidden: false, innerHTML: "", style: {}, querySelector: function () { return null; }};
}

const els = {"sdk-subtitle": makeEl()};
global.document = {getElementById: function (id) { return els[id] || null; }};
global.dauntlessEvent = function () {};

eval(fs.readFileSync(process.argv[2], "utf8"));

function run(payload) {
  els["sdk-subtitle"].style.opacity = "unset";
  setSdkMirror(payload);
  return els["sdk-subtitle"].style.opacity;
}

const out = {};

// Banner only (no crew line): container opacity must mirror the (single)
// line's fade opacity, not stay pinned at full alpha.
out.bannerOnly = run({entries: [{
  type: "subtitle", visible: true, lines: [{text: "x", opacity: 0.4}],
}]});

// Crew caption present alongside a fading banner line in the same payload:
// the caption must never be dimmed by the banner's fade -- container stays
// at full opacity.
out.captionWithFadingBannerLine = run({entries: [{
  type: "subtitle", visible: true, speaker: "LIU", speech: "Captain.",
  lines: [{text: "x", opacity: 0.2}],
}]});

// A fully hidden render (nothing live) must reset the container's inline
// opacity so a previously-fading banner cannot leave the box dimmed for
// whatever renders in it next.
els["sdk-subtitle"].style.opacity = "0.123";
setSdkMirror({entries: [{type: "subtitle", visible: false, lines: []}]});
out.hiddenReset = els["sdk-subtitle"].style.opacity;

process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node not found on PATH")
def test_banner_box_fades_with_its_text_but_a_caption_box_never_dims():
    """Finding 3: actually execute sdk_mirror.js (via node, with a minimal
    getElementById shim) rather than pattern-match its source, so this pins
    real behaviour instead of a string that merely looks right."""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_NODE_HARNESS)
        harness_path = f.name
    try:
        result = subprocess.run(
            [NODE, harness_path, str(JS_PATH)],
            capture_output=True, text=True, timeout=10,
        )
    finally:
        Path(harness_path).unlink()
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["bannerOnly"] == "0.400"
    assert out["captionWithFadingBannerLine"] == "1"
    assert out["hiddenReset"] == "1"
