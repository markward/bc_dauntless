import ast

import pytest

from engine.appc import mod_hardpoint_writer as mw

SRC = '''# my refit, do not touch this comment
import App

PortWarp = App.EngineProperty_Create("Port Warp")
PortWarp.SetPosition(-1.300000, -2.100000, -0.060000)   # tuned by hand
PortWarp.SetRadius(1.200000)
App.g_kModelPropertyManager.RegisterLocalTemplate(PortWarp)

Hull = App.HullProperty_Create("Hull")
App.g_kModelPropertyManager.RegisterLocalTemplate(Hull)
'''


def _changed_lines(a, b):
    return [(x, y) for x, y in zip(a.splitlines(), b.splitlines()) if x != y]


def test_setposition_rewritten_in_place_only():
    out = mw.rewrite(SRC, "refit", [("Port Warp", "SetPosition", (1.0, 2.0, 3.5))])
    assert _changed_lines(SRC, out) == [(
        "PortWarp.SetPosition(-1.300000, -2.100000, -0.060000)   # tuned by hand",
        "PortWarp.SetPosition(1.000000, 2.000000, 3.500000)   # tuned by hand")]
    assert mw.START_MARKER not in out        # nothing needed the block


def test_setradius_rewritten_in_place():
    out = mw.rewrite(SRC, "refit", [("Port Warp", "SetRadius", (0.5,))])
    assert "PortWarp.SetRadius(0.500000)" in out
    assert len(_changed_lines(SRC, out)) == 1


def test_missing_setter_falls_back_to_the_block():
    out = mw.rewrite(SRC, "refit", [("Hull", "SetRadius", (4.0,))])
    assert SRC in out                          # author text untouched
    _author, block = mw.split_block(out)
    assert mw.read_block(block)["Hull"] == [("SetRadius", (4.0,))]


def test_loop_created_subsystem_falls_back():
    src = SRC + 'for n in ["A"]:\n    q = App.EngineProperty_Create(n)\n    q.SetRadius(1.0)\n'
    out = mw.rewrite(src, "refit", [("A", "SetRadius", (2.0,))])
    assert out.startswith(src)
    assert mw.read_block(mw.split_block(out)[1])["A"] == [("SetRadius", (2.0,))]


def test_py2_syntax_file_puts_everything_in_the_block():
    src = SRC + "print 'hello'\n"
    out = mw.rewrite(src, "refit", [("Port Warp", "SetPosition", (1.0, 2.0, 3.0))])
    assert out.startswith(src)
    assert mw.read_block(mw.split_block(out)[1])["Port Warp"] == [
        ("SetPosition", (1.0, 2.0, 3.0))]


def test_glow_goes_to_block_and_block_merges_across_saves():
    once = mw.rewrite(SRC, "refit", [("Port Warp", "__region__", 0,
                                      [("SetGlowRegionShape", (0, "Box"))])])
    twice = mw.rewrite(once, "refit", [("Hull", "SetRadius", (4.0,))])
    assert twice.count(mw.START_MARKER) == 1
    model = mw.read_block(mw.split_block(twice)[1])
    assert model["Port Warp"] == [("SetGlowRegionShape", (0, "Box"))]
    assert model["Hull"] == [("SetRadius", (4.0,))]


def test_inplace_success_drops_a_stale_block_entry():
    # An older save put SetPosition in the block (e.g. before the author added
    # the call). Once it is done in place, the block copy must go.
    stale = mw.append_block(SRC, mw.emit_block({"Port Warp": [
        ("SetPosition", (9.0, 9.0, 9.0)), ("SetGlowRegionShape", (0, "Box"))]}), "\n")
    out = mw.rewrite(stale, "refit", [("Port Warp", "SetPosition", (1.0, 2.0, 3.0))])
    model = mw.read_block(mw.split_block(out)[1])
    assert model["Port Warp"] == [("SetGlowRegionShape", (0, "Box"))]
    assert "PortWarp.SetPosition(1.000000, 2.000000, 3.000000)" in out


def test_emptying_the_block_removes_it():
    with_block = mw.rewrite(SRC, "refit", [("wing", "__part__",
                                            [("SetTransitionSeconds", (2.0,))])])
    out = mw.rewrite(with_block, "refit", [("wing", "__part__", [])])
    assert out == SRC


def test_reused_variable_only_rewrites_the_named_subsystem():
    src = ('import App\n'
           'p = App.EngineProperty_Create("A")\np.SetRadius(1.000000)\n'
           'p = App.EngineProperty_Create("B")\np.SetRadius(2.000000)\n')
    out = mw.rewrite(src, "x", [("A", "SetRadius", (7.0,))])
    assert out == src.replace("p.SetRadius(1.000000)", "p.SetRadius(7.000000)")


def test_crlf_preserved_for_inplace_and_block():
    src = SRC.replace("\n", "\r\n")
    out = mw.rewrite(src, "refit", [
        ("Port Warp", "SetRadius", (0.5,)),
        ("Hull", "__region__", 0, [("SetGlowRegionShape", (0, "Box"))])])
    assert "\n" not in out.replace("\r\n", "")
    assert "PortWarp.SetRadius(0.500000)\r\n" in out


def test_malformed_markers_raise():
    with pytest.raises(mw.ManagedBlockError):
        mw.rewrite(SRC + mw.START_MARKER + "\n", "refit",
                   [("Port Warp", "SetRadius", (0.5,))])


def test_result_parses():
    out = mw.rewrite(SRC, "refit", [
        ("Port Warp", "SetPosition", (1.0, 2.0, 3.0)),
        ("wing", "__part__", [("SetTransitionSeconds", (2.0,))])])
    ast.parse(out)


# ── Extra: non-ASCII byte/char-offset handling ──────────────────────────────

def test_non_ascii_earlier_on_a_line_with_an_unrewritten_setter_call():
    # 'é' is 2 UTF-8 bytes but 1 char; put it BEFORE a setter call on its own
    # line so a byte-offset bug would misplace the span for THAT call. Only
    # PortWarp.SetPosition is being rewritten, so this call must survive
    # untouched and the rewritten call elsewhere must still be exactly right.
    src = SRC.replace(
        'PortWarp.SetRadius(1.200000)',
        'PortWarp.SetRadius(1.200000)  # café note')  # non-ASCII before EOL, not before a call
    out = mw.rewrite(src, "refit", [("Port Warp", "SetPosition", (1.0, 2.0, 3.0))])
    assert "PortWarp.SetPosition(1.000000, 2.000000, 3.000000)" in out
    assert "PortWarp.SetRadius(1.200000)  # café note" in out
    assert _changed_lines(src, out) == [(
        "PortWarp.SetPosition(-1.300000, -2.100000, -0.060000)   # tuned by hand",
        "PortWarp.SetPosition(1.000000, 2.000000, 3.000000)   # tuned by hand")]


def test_non_ascii_trailing_comment_on_the_rewritten_call_line():
    src = SRC.replace(
        'PortWarp.SetPosition(-1.300000, -2.100000, -0.060000)   # tuned by hand',
        'PortWarp.SetPosition(-1.300000, -2.100000, -0.060000)   # tunéd by hand')
    out = mw.rewrite(src, "refit", [("Port Warp", "SetPosition", (1.0, 2.0, 3.0))])
    assert "PortWarp.SetPosition(1.000000, 2.000000, 3.000000)   # tunéd by hand" in out
    assert mw.START_MARKER not in out
