"""_fix_py2_syntax's octal rewrite must leave float exponents alone.

`(?<![\\w.])0([0-7]+)` saw the `05` of `7.7e-05` as a Python 2 octal literal
and produced `7.7e-0o5` -- a SyntaxError that made the ship unloadable once the
Ship Property Viewer saved a tiny float (repr() writes `e-05`) into a mod's
hardpoint file. Checked in BOTH twins: tools/mission_harness.py (the
production loader) and tests/conftest.py.
"""
import ast

import pytest

import tests.conftest as conftest
from tools import mission_harness

TWINS = [mission_harness._fix_py2_syntax, conftest._fix_py2_syntax]


@pytest.mark.parametrize("fix", TWINS)
@pytest.mark.parametrize("src", [
    "x = -7.766295250279852e-05\n",
    "x = 1.5E+07\n",
    "x = 2e-010\n",
    "p.SetStatePose('warp', -0.01, -7.7e-05, 0.0)\n",
])
def test_float_exponents_are_untouched(fix, src):
    out = fix(src)
    assert out == src
    ast.parse(out)


@pytest.mark.parametrize("fix", TWINS)
@pytest.mark.parametrize("src, want", [
    ("mode = 0755\n", "mode = 0o755\n"),
    ("a = -010\n", "a = -0o10\n"),
    ("f(1, 07)\n", "f(1, 0o7)\n"),
])
def test_py2_octals_still_convert(fix, src, want):
    assert fix(src) == want
