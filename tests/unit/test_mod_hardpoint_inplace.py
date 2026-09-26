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
#
# Fix round 1, item 6: the original two non-ASCII tests never actually
# exercised _char_span's byte->char conversion -- the multi-byte chars sat on
# a later line, or after the rewritten call's own end_col_offset, so a
# byte-offset bug could not have been caught by either. This test puts a
# multi-byte character BEFORE the rewritten call on its OWN line, as an
# earlier `;`-separated statement, so the call's col_offset (a UTF-8 BYTE
# offset) is shifted relative to its char offset.

def test_non_ascii_before_the_rewritten_call_on_the_same_line():
    src = ('import App\n'
           'PortWarp = App.EngineProperty_Create("Port Warp")\n'
           'z = "é"; PortWarp.SetRadius(1.200000)\n')
    out = mw.rewrite(src, "refit", [("Port Warp", "SetRadius", (7.0,))])
    assert out == src.replace(
        "PortWarp.SetRadius(1.200000)", "PortWarp.SetRadius(7.000000)")
    assert 'z = "é"; PortWarp.SetRadius(7.000000)\n' in out


# ── Fix round 1 (review) ────────────────────────────────────────────────────

def test_shifted_span_is_rejected(monkeypatch):
    """item 1: the verify step must be a REAL check against the source, not
    a tautology that undoes its own splice. Shifting every span by +2 chars
    must be caught as ManagedBlockError, not silently accepted (nor left to
    an incidental downstream SyntaxError)."""
    orig = mw._char_span

    def shifted(text, node):
        start, end = orig(text, node)
        return start + 2, end + 2

    monkeypatch.setattr(mw, "_char_span", shifted)
    with pytest.raises(mw.ManagedBlockError):
        mw.rewrite(SRC, "refit", [("Port Warp", "SetRadius", (0.5,))])


def test_duplicate_inplace_edits_last_one_wins():
    """item 2: two edits for the same (subsystem, setter) must collapse to
    the last one before any span is located, not both independently splice
    the identical source span."""
    out = mw.rewrite(SRC, "refit", [
        ("Port Warp", "SetRadius", (0.5,)),
        ("Port Warp", "SetRadius", (0.75,))])
    assert "PortWarp.SetRadius(0.750000)" in out
    assert "PortWarp.SetRadius(0.500000)" not in out
    assert len(_changed_lines(SRC, out)) == 1


def test_managed_block_is_parse_checked_even_when_author_does_not_parse(monkeypatch):
    """item 3: spec 5.6 -- the managed block must parse on its own whenever
    non-empty, regardless of whether the author's (possibly py1.5/py2)
    text parses under Python 3."""
    monkeypatch.setattr(mw, "emit_block", lambda per_sub, newline="\n": "not: valid( python")
    src = SRC + "print 'hello'\n"
    with pytest.raises(SyntaxError):
        mw.rewrite(src, "refit", [("Port Warp", "SetPosition", (1.0, 2.0, 3.0))])


def test_nested_override_after_toplevel_call_falls_back_to_block():
    """item 4: a later NON-top-level `V.<setter>(...)` (inside an `if`, loop,
    or function body) while V is still bound overrides our rewritten
    top-level call at runtime, so the edit must fall back to the block
    rather than silently doing nothing."""
    src = ('import App\n'
           'p = App.EngineProperty_Create("A")\n'
           'p.SetRadius(1.2)\n'
           'if 1:\n'
           '    p.SetRadius(3.0)\n')
    out = mw.rewrite(src, "refit", [("A", "SetRadius", (7.0,))])
    assert out.startswith(src)                 # author text byte-identical
    assert mw.read_block(mw.split_block(out)[1])["A"] == [("SetRadius", (7.0,))]


def test_non_property_create_is_not_treated_as_the_binding():
    """item 5: _is_create_of must require the literal `...Property_Create`
    suffix (spec 4.1), not any `..._Create`."""
    src = ('import App\n'
           'V = App.SomeOther_Create("A")\n'
           'V.SetRadius(1.0)\n')
    out = mw.rewrite(src, "x", [("A", "SetRadius", (9.0,))])
    assert out.startswith(src)                 # not rewritten in place
    assert mw.read_block(mw.split_block(out)[1])["A"] == [("SetRadius", (9.0,))]
