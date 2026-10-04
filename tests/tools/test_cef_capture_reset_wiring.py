"""Native clears keyboard capture when the page reloads/navigates or the
renderer dies, with no Python round trip -- so a field that vanished with its
page can never leave the game deaf. CEF reloads/crashes can't run in the
suite, so this pins the wiring at source level.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S2.4
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT_CC = ROOT / "native/src/ui_cef/cef_client.cc"
CLIENT_H = ROOT / "native/src/ui_cef/cef_client.h"
BINDINGS = ROOT / "native/src/host/host_bindings.cc"


def _body(src, signature_regex):
    m = re.search(signature_regex, src)
    assert m, signature_regex
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[i:j + 1]
    raise AssertionError("unbalanced body")


def test_load_start_fires_the_reset_for_the_main_frame():
    body = _body(CLIENT_CC.read_text(), r"DauntlessCefClient::OnLoadStart\s*\(")
    main = body[body.index("IsMain()"):]
    assert "fire_capture_reset()" in main


def test_renderer_crash_fires_the_reset():
    assert "CefRequestHandler" in CLIENT_H.read_text()
    body = _body(CLIENT_CC.read_text(),
                 r"DauntlessCefClient::OnRenderProcessTerminated\s*\(")
    assert "fire_capture_reset()" in body


def test_bindings_wire_the_reset_to_the_window_gate():
    src = BINDINGS.read_text()
    m = re.search(r"set_capture_reset_handler\s*\(", src)
    assert m, "host_bindings never installs the capture-reset handler"
    tail = src[m.end():m.end() + 400]
    assert "set_key_capture(false)" in tail
