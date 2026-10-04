"""Regression test: dynamic text (a player-typed variant_of, a payload
species name, a mod name) must not be able to break out of an inline
onclick="..." attribute in mods_screen.js.

msJs() escapes only backslash and single-quote for the INNER JS string;
until this fix nothing escaped the OUTER HTML attribute, so a value
containing a literal double quote (e.g. `USS "Enterprise"` typed as a
variant-of class on one row) corrupted the generated popup markup for
every other row that lists it, and the same was true of any payload
species name or mod name containing a quote.

There is no headless CEF render, so this drives the real script under
node with a minimal stubbed document/window -- enough to call msRender,
msVariantMenu and msPick directly -- rather than asserting against
Python-side string reconstruction of the escaping rules.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS_FILE = (Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"
           / "js" / "mods_screen.js")

_NODE = shutil.which("node")

_HARNESS = r"""
'use strict';
const fs = require('fs');
const vm = require('vm');

const jsPath = process.argv[2];
const src = fs.readFileSync(jsPath, 'utf8');

const elements = {};
function makeEl(id) {
    return {
        id: id, innerHTML: '', textContent: '', style: {},
        getBoundingClientRect: function () { return { bottom: 10, top: 10, left: 10 }; },
        scrollHeight: 100, offsetWidth: 100,
        querySelectorAll: function () { return []; },
        focus: function () {}, getAttribute: function () { return null; },
        closest: function () { return null; },
        classList: { contains: function () { return false; } }
    };
}
function getElementById(id) {
    if (!elements[id]) { elements[id] = makeEl(id); }
    return elements[id];
}

const sandbox = {
    document: { getElementById: getElementById, addEventListener: function () {} },
    window: { innerHeight: 1000, innerWidth: 1000 },
    dauntlessEvent: function () {},
    console: console
};
vm.createContext(sandbox);
vm.runInContext(src, sandbox, { filename: jsPath });

const payload = {
    mode: 'gate', header: 'h', intro: 'i', error: '',
    rows: [
        { file: 'OTHER', mod: 'My "Cool" Mod', icon: '', icon_url: '', title: 'Other',
          variant_of: 'USS "Enterprise"', is_default: false, stock_class: false,
          star_locked: false, era: null, role: null, species: null, playable: null,
          editable: true, ticked: false, missing: [], conflict: '' },
        { file: 'TARGET', mod: 'My "Cool" Mod', icon: '', icon_url: '', title: 'Target',
          variant_of: '', is_default: false, stock_class: false, star_locked: false,
          era: null, role: null, species: null, playable: null, editable: true,
          ticked: false, missing: [], conflict: '' }
    ],
    mods: [{ name: 'My "Cool" Mod', ships: 2, classes: 2 }],
    species: ['Bird "of" Prey'],
    stock_classes: [],
    eras: [{ id: 'tos', tag: 'TOS', name: 'The Original Series' }],
    roles: [{ id: 'tactical', label: 'Tactical' }],
    ticked: 0, status: 'ok', status_ok: true, can_continue: true
};
sandbox.MS.p = payload;

sandbox.msRender();
const tableHtml = elements['ms-table'].innerHTML;

const fakeAnchor = { getBoundingClientRect: function () { return { bottom: 1, top: 1, left: 1 }; } };

sandbox.msVariantMenu(Object.assign({ value: '' }, fakeAnchor), 'TARGET');
const variantMenuHtml = elements['ms-menu'].innerHTML;

sandbox.msPick(
    { stopPropagation: function () {}, currentTarget: fakeAnchor },
    'TARGET', 'species'
);
const speciesMenuHtml = elements['ms-menu'].innerHTML;

process.stdout.write(JSON.stringify({
    tableHtml: tableHtml,
    variantMenuHtml: variantMenuHtml,
    speciesMenuHtml: speciesMenuHtml
}));
"""


def _run_harness(tmp_path: Path) -> dict:
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS)
    result = subprocess.run([_NODE, str(harness), str(JS_FILE)],
                            capture_output=True, text=True)
    assert result.returncode == 0, (
        "harness threw while exercising mods_screen.js:\n" + result.stderr)
    return json.loads(result.stdout)


def _onclick_values(html: str) -> list:
    """Every onclick="..." VALUE, extracted with a naive non-greedy regex.

    This only extracts cleanly when no raw `"` is left inside the value --
    which is exactly the property under test. A regression that stops
    escaping the outer attribute makes this regex truncate at the first
    embedded quote, so the extracted value no longer equals the full,
    expected handler call and the assertions below catch it.
    """
    import re
    return re.findall(r'onclick="([^"]*)"', html)


@pytest.mark.skipif(_NODE is None, reason="node not available to run the harness")
def test_variant_of_quick_pick_escapes_a_quoted_class_name(tmp_path):
    out = _run_harness(tmp_path)
    values = _onclick_values(out["variantMenuHtml"])
    expected = "msSet('TARGET','variant_of','USS &quot;Enterprise&quot;');msCloseMenu()"
    assert expected in values, (values, out["variantMenuHtml"])
    # Decoding the HTML entity recovers exactly the original quoted text,
    # sitting safely inside the single-quoted JS string (no JS-escaping of
    # a bare double quote is ever needed inside a single-quoted string).
    assert expected.replace("&quot;", '"') == \
        "msSet('TARGET','variant_of','USS \"Enterprise\"');msCloseMenu()"


@pytest.mark.skipif(_NODE is None, reason="node not available to run the harness")
def test_species_picker_escapes_a_quoted_species_name(tmp_path):
    out = _run_harness(tmp_path)
    values = _onclick_values(out["speciesMenuHtml"])
    expected = "msSet('TARGET','species','Bird &quot;of&quot; Prey');msCloseMenu()"
    assert expected in values, (values, out["speciesMenuHtml"])


@pytest.mark.skipif(_NODE is None, reason="node not available to run the harness")
def test_tick_mod_escapes_a_quoted_mod_name(tmp_path):
    out = _run_harness(tmp_path)
    values = _onclick_values(out["tableHtml"])
    expected = "msSend('tick-mod:My &quot;Cool&quot; Mod')"
    assert expected in values, (values, out["tableHtml"])


@pytest.mark.skipif(_NODE is None, reason="node not available to run the harness")
def test_no_raw_double_quote_survives_inside_any_onclick_value(tmp_path):
    """Every single onclick value across all three payloads must be a
    COMPLETE, unterminated-by-injection handler call -- not just the three
    specific cases named above. A value that was truncated by an embedded
    raw quote never ends in ')' (it ends mid-string, at the character
    right before the quote that broke out), so this is a generic guard
    against the whole bug class, not just the three reproduction cases."""
    out = _run_harness(tmp_path)
    checked = 0
    for name, html in out.items():
        for value in _onclick_values(html):
            assert '"' not in value, (name, value, html)
            assert value.endswith(')'), (name, value, html)
            checked += 1
    assert checked >= 10, "the harness produced no onclick attributes to check"
