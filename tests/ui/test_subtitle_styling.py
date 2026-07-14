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


def _px(rule: str, prop: str) -> float:
    m = re.search(prop + r"\s*:\s*([\d.]+)px", rule)
    assert m, "%r not found as a px value in rule" % prop
    return float(m.group(1))


def _clamp_max_px(rule: str) -> float:
    m = re.search(r"clamp\([^,]+,[^,]+,\s*([\d.]+)px\)", rule)
    assert m, "no clamp(...) max found in rule"
    return float(m.group(1))


# Reference viewport height used to convert the card's px-based type sizes
# into the same vh unit as its `bottom` offset, matching the arithmetic in
# the sdk_mirror.css comments. The ratio (not any one exact resolution) is
# what matters here.
REFERENCE_VIEWPORT_HEIGHT_PX = 1080.0


def test_episode_card_is_at_the_mockup_height():
    # Mark's design mockup puts the card's text block ~12vh off the bottom
    # edge -- at or below the caption box's normal 14vh `bottom`. Clearance
    # from the caption now comes from LIFTING THE CAPTION on the one
    # mission where both are live (E2M1), not from raising the card; see
    # test_title_live_caption_clears_the_cards_two_line_top_edge below. A
    # future edit that floats the card back up above the caption's normal
    # position must fail this.
    caption_bottom_vh = _vh(_rule(CSS, "#sdk-subtitle"), "bottom")
    episode_bottom_vh = _vh(_rule(CSS, "#sdk-episode-title"), "bottom")
    assert episode_bottom_vh <= caption_bottom_vh


def test_title_live_caption_clears_the_cards_two_line_top_edge():
    # Finding 1 (original review): E2M1's Ep2Cutscene.py appends
    # EpisodeTitleAction and chains three of Saffi's spoken lines right
    # after it, so the title card and a live caption ARE on screen together
    # in a shipped mission. Compute the card's actual top edge from its own
    # CSS -- its `bottom`, plus the eyebrow, plus a worst-case two-line
    # title (it can wrap at max-width: 62vw) -- and assert the
    # `--title-live` modifier's `bottom` clears it. This tracks the CSS
    # instead of hardcoding a number, so retuning any of eyebrow size,
    # title clamp, or the card's `bottom` without revisiting the modifier
    # fails here.
    card_bottom_vh = _vh(_rule(CSS, "#sdk-episode-title"), "bottom")

    eyebrow_rule = _rule(CSS, ".sdk-episode__eyebrow")
    eyebrow_px = _px(eyebrow_rule, "font-size")
    eyebrow_margin_px = _px(eyebrow_rule, "margin-bottom")

    title_rule = _rule(CSS, ".sdk-episode__title")
    title_max_px = _clamp_max_px(title_rule)
    two_line_title_px = title_max_px * 2  # line-height: 1.0, worst-case wrap

    card_top_extent_px = eyebrow_px + eyebrow_margin_px + two_line_title_px
    card_top_extent_vh = card_top_extent_px / REFERENCE_VIEWPORT_HEIGHT_PX * 100
    card_top_vh = card_bottom_vh + card_top_extent_vh

    live_bottom_vh = _vh(
        _rule(CSS, "#sdk-subtitle.sdk-subtitle--title-live"), "bottom"
    )
    assert live_bottom_vh >= card_top_vh


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
  const classes = new Set();
  return {
    hidden: false, innerHTML: "", style: {},
    querySelector: function () { return null; },
    classList: {
      add: function (c) { classes.add(c); },
      remove: function (c) { classes.delete(c); },
      contains: function (c) { return classes.has(c); },
    },
  };
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

// A live episode title (title_text present on the SAME subtitle entry)
// must add the modifier class that lifts the caption box clear of the
// card -- see .sdk-subtitle--title-live in sdk_mirror.css.
setSdkMirror({entries: [{
  type: "subtitle", visible: true, title_text: "The Long Way Home", lines: [],
}]});
out.titleLiveClassAdded =
  els["sdk-subtitle"].classList.contains("sdk-subtitle--title-live");

// When the title expires (payload drops title_text), the modifier must
// come back off so the caption returns to its normal height for whatever
// mission plays next.
setSdkMirror({entries: [{type: "subtitle", visible: true, lines: []}]});
out.titleLiveClassRemovedAfterExpiry =
  els["sdk-subtitle"].classList.contains("sdk-subtitle--title-live");

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
    assert out["titleLiveClassAdded"] is True
    assert out["titleLiveClassRemovedAfterExpiry"] is False
