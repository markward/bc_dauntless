"""The large modal — one shared window shape (configuration_panel.css
`.cp-modal-layer` / `.cp-modal--large`, engine/ui/modal_geometry.py).

Three contracts:
  * the CSS size literals and the Python mirror are the same four numbers;
  * every window that claims to be a large modal uses both classes and does
    not re-size or re-layer itself locally;
  * the layer sits above every HUD/panel element and below the pause menu,
    and js/modal_layer.js hides whatever paints beneath an open layer (the
    Player and Speed panels showed through Set Course's transparent map).
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from engine.ui import modal_geometry as mg

ASSETS = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"
CP_CSS = ASSETS / "css" / "configuration_panel.css"
LAYER_JS = ASSETS / "js" / "modal_layer.js"
NODE = shutil.which("node")

# Windows built on the large modal: root section id -> its own stylesheet.
LARGE_MODALS = {
    "quick-battle-setup": "quick_battle_setup.css",
    "star-map-panel": "star_map.css",
}

# Body-level screens that deliberately paint ABOVE a large modal.
_ABOVE_LAYER = ("#pause-menu", "#mission-picker", "#first-run",
                "#mods-screen", ".ms-menu")


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _block(css, selector):
    m = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}",
                  _strip_comments(css))
    assert m, "no " + selector + " rule"
    return m.group(1)


def _prop(block, prop):
    m = re.search(r"(?<![-\w])" + prop + r"\s*:\s*([^;]+);", block)
    assert m, "missing " + prop
    return m.group(1).strip()


def test_css_size_matches_the_python_mirror():
    block = _block(CP_CSS.read_text(encoding="utf-8"), ".cp-modal--large")
    pct = int(mg.LARGE_MODAL_FRACTION * 100)
    assert _prop(block, "width") == "%dvw" % pct
    assert _prop(block, "height") == "%dvh" % pct
    fit = int(mg.LARGE_MODAL_FIT_FRACTION * 100)
    assert _prop(block, "min-width") == "min(%dpx, %dvw)" % (mg.LARGE_MODAL_MIN_W, fit)
    assert _prop(block, "min-height") == "min(%dpx, %dvh)" % (mg.LARGE_MODAL_MIN_H, fit)


def test_large_modal_size_follows_the_view_and_floors():
    assert mg.large_modal_size(1280, 720) == (1024, 576)
    assert mg.large_modal_size(1000, 600) == (900, 560)
    # Smaller than the floor: the floor shrinks to 96% of the window, so the
    # modal never overflows it.
    w, h = mg.large_modal_size(680, 500)
    assert (w, h) == (680 * 0.96, 500 * 0.96)
    assert w < 680 and h < 500
    # Content origin: the 1px border cancels out of the centring.
    assert mg.large_modal_content_origin(1280, 720) == (128, 72)


def test_every_large_modal_uses_both_classes():
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    for root_id in LARGE_MODALS:
        m = re.search(r'<section id="' + root_id + r'"([^>]*)>\s*<div class="([^"]*)"',
                      index)
        assert m, root_id
        assert "cp-modal-layer" in m.group(1), root_id
        assert {"cp-modal", "cp-modal--large"} <= set(m.group(2).split()), root_id


def test_no_large_modal_resizes_or_relayers_itself():
    """A local width or z-index silently forks the shared shape — the very
    inconsistency the component exists to end."""
    for root_id, sheet in LARGE_MODALS.items():
        css = _strip_comments((ASSETS / "css" / sheet).read_text(encoding="utf-8"))
        for sel, block in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            sel = sel.strip()
            if sel not in ("#" + root_id, "#" + root_id + " .cp-modal") \
                    and not re.fullmatch(r"#" + root_id + r" \.qbs-modal", sel):
                continue
            for prop in ("width", "height", "min-width", "min-height",
                         "z-index", "inset"):
                if sel.endswith(".qbs-modal") and prop == "z-index":
                    continue   # local stacking context for the sheet, z 0
                assert not re.search(r"(?<![-\w])" + prop + r"\s*:", block), (
                    sheet + ": " + sel + " overrides the shared " + prop)


def _layer_z():
    return int(_prop(_block(CP_CSS.read_text(encoding="utf-8"),
                            ".cp-modal-layer"), "z-index"))


def test_the_layer_is_above_all_other_ui_and_below_the_pause_menu():
    z = _layer_z()
    global_css = (ASSETS / "css" / "global.css").read_text(encoding="utf-8")
    assert z < int(_prop(_block(global_css, "#pause-menu"), "z-index"))

    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)"', index)
    for sheet in sheets:
        css = _strip_comments((ASSETS / sheet).read_text(encoding="utf-8"))
        for sel, block in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            m = re.search(r"(?<![-\w])z-index\s*:\s*(\d+)", block)
            if not m or ".cp-modal-layer" in sel:
                continue
            if any(name in sel for name in _ABOVE_LAYER):
                continue
            assert int(m.group(1)) < z, (sheet, sel.strip(), m.group(1))


def test_occlusion_rule_beats_descendant_visibility():
    css = _strip_comments(CP_CSS.read_text(encoding="utf-8"))
    m = re.search(r"\.ui-occluded\s*,\s*\.ui-occluded\s+\*\s*\{([^}]*)\}", css)
    assert m, "the occlusion rule must cover descendants too"
    assert re.search(r"visibility\s*:\s*hidden\s*!important", m.group(1))


def test_layer_script_is_loaded_after_the_markup():
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    assert '<script src="js/modal_layer.js"></script>' in index
    assert index.index("js/modal_layer.js") > index.index('id="star-map-panel"')


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const f = ctx.modalLayerOccludedFlags;
const hud = {isLayer: false, open: false, z: 0};
const hud50 = {isLayer: false, open: false, z: 50};
const pause = {isLayer: false, open: false, z: 100};
const shut = {isLayer: true, open: false, z: 95};
const open = {isLayer: true, open: true, z: 95};
console.log(JSON.stringify({
  closed: f([hud, hud50, pause, shut]),
  opened: f([hud, hud50, pause, open]),
  twoLayers: f([hud, shut, open]),
}));
"""


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_an_open_layer_hides_only_what_paints_beneath_it():
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_HARNESS)
        harness = f.name
    try:
        r = subprocess.run([NODE, harness, str(LAYER_JS)],
                           capture_output=True, text=True, timeout=10)
    finally:
        Path(harness).unlink()
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["closed"] == [False, False, False, False]
    # HUD at auto and at 50 hidden; the pause menu above stays; the layer
    # itself is never occluded.
    assert out["opened"] == [True, True, False, False]
    # A closed layer is not occluded by an open one — it is not drawn anyway,
    # and stamping it would leave the class behind when it next opens.
    assert out["twoLayers"] == [True, False, False]
