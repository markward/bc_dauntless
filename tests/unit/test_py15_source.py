"""engine.py15.source turns Python 1.5 source into source Python 3 parses
to the program Python 1.5 would have run.

Both SDK loaders (tools/mission_harness.py and tests/conftest.py) call it, so
these cases hold in the game and under test alike. Every fixture is our own
code: no BC or mod content.
"""
import ast
import textwrap

import pytest

import tests.conftest as conftest
from engine.py15 import source
from tools import mission_harness


def _run(src):
    """Execute fixed source; return its namespace (printing captured)."""
    out = []
    ns = {"print": lambda *a, **k: out.append((a, k))}
    exec(compile(source.fix_source(textwrap.dedent(src)), "<t>", "exec"), ns)
    ns["_printed"] = out
    return ns


# -- one implementation, used by both loaders --------------------------------

def test_both_loaders_use_the_shared_fixer():
    assert mission_harness._fix_py2_syntax is source.fix_syntax
    assert conftest._fix_py2_syntax is source.fix_syntax


# -- indentation: Python 1.5 expands a tab to the next multiple of 8 ---------

def test_a_tab_is_eight_columns_of_indentation():
    # Line 3 is 8 spaces; under 4-column tabs it would be deeper than line 2
    # and an unexpected indent. Under 1.5's rule it lines up with line 2.
    ns = _run("if 1:\n\tx = 1\n        y = 2\n")
    assert (ns["x"], ns["y"]) == (1, 2)


def test_mixed_tab_and_space_indentation_nests_as_in_python_1_5():
    ns = _run("def f(a):\n    if a:\n\treturn 1\n    return 2\nr = (f(1), f(0))\n")
    assert ns["r"] == (1, 2)


def test_a_tab_inside_a_string_is_not_expanded():
    assert _run("s = 'a\tb'\n")["s"] == "a\tb"


# -- literals ----------------------------------------------------------------

@pytest.mark.parametrize("src, want", [
    ("x = 10L", 10),
    ("x = 0xffffffffL", 0xffffffff),
    ("x = 1L << 53", 1 << 53),
    ("x = 0777L", 0o777),
    ("x = 0755", 0o755),
    ("x = 7.7e-05", 7.7e-05),
])
def test_numeric_literals(src, want):
    assert _run(src)["x"] == want


@pytest.mark.parametrize("src, want", [
    # \N, \u and \U are not escapes in Python 1.5: kept literally.
    (r"s = 'scripts\Custom\NanoFXv2'", "scripts\\Custom\\NanoFXv2"),
    (r"s = 'a\u0041'", "a\\u0041"),
    (r"s = 'a\U00000041'", "a\\U00000041"),
    # \x takes EVERY following hex digit and keeps the low byte (1.5).
    (r"s = '\x4142'", "\x42"),
    (r"s = '\x7'", "\x07"),
    (r"s = '\xq'", "\\xq"),
    # Octal escapes keep the low byte too.
    (r"s = '\777'", "\xff"),
    (r"s = '\101'", "A"),
    # Ordinary escapes are unchanged, and raw strings are left alone.
    (r"s = 'a\tb\n\\'", "a\tb\n\\"),
    (r"s = r'\N\u'", "\\N\\u"),
    (r's = """x\Ny"""', "x\\Ny"),
])
def test_string_escapes_mean_what_they_meant_in_python_1_5(src, want):
    assert _run(src)["s"] == want


@pytest.mark.parametrize("src", [
    "s = '10L'", "s = 'mode 0755'", "s = 'a <> b'", "s = 'print x'",
    "s = '`x`'", "s = 'd.has_key(k)'",
])
def test_code_rewrites_never_touch_string_contents(src):
    assert _run(src)["s"] == ast.literal_eval(src.split("=", 1)[1].strip())


def test_backticks_become_repr():
    assert _run("x = 5\ns = `x` + `'a'`\n")["s"] == "5'a'"


def test_not_equal_and_has_key():
    ns = _run("d = {'k': 1}\nr = (1 <> 2, d.has_key('k'))\n")
    assert ns["r"] == (True, True)


# -- statements --------------------------------------------------------------

@pytest.mark.parametrize("src, want", [
    ("print 'a', 1", [(("a", 1), {})]),
    ("print", [((), {})]),
    ("if 1: print 'a'", [(("a",), {})]),
    ("if 1: print", [((), {})]),
    ("for i in (1,): print i", [((1,), {})]),
    ("x = 1; print x; print 'b'", [((1,), {}), (("b",), {})]),
    ("print 'a'   # trailing comment", [(("a",), {})]),
    ("print 'a;b # c'", [(("a;b # c",), {})]),
    ("print (1)", [((1,), {})]),
])
def test_print_statements(src, want):
    assert _run(src + "\n")["_printed"] == want


def test_print_to_a_file():
    class F:
        pass
    out = []
    ns = {"print": lambda *a, **k: out.append((a, k)), "f": F}
    exec(compile(source.fix_source("print >>f, 'a', 2\n"), "<t>", "exec"), ns)
    assert out == [(("a", 2), {"file": F})]


def test_a_print_inside_a_multiline_string_is_left_alone():
    ns = _run('s = """\nprint x\n"""\n')
    assert ns["s"] == "\nprint x\n" and ns["_printed"] == []


def test_raise_with_a_value_and_a_trailing_comment():
    with pytest.raises(ValueError, match="bad"):
        _run("raise ValueError, 'bad'   # why\n")


def test_raise_whose_message_holds_commas():
    with pytest.raises(KeyError, match="a, b c"):
        _run("raise KeyError, 'a, %s c' % ('b',)\n")


@pytest.mark.parametrize("header", ["except ValueError, e:",
                                    "except (KeyError, ValueError), e:"])
def test_except_with_a_target(header):
    ns = _run("try:\n    raise ValueError('v')\n%s\n    r = str(e)\n" % header)
    assert ns["r"] == "v"


@pytest.mark.parametrize("src, want", [
    ("exec 'x = 1'", 1),
    ("g = {}\nexec 'x = 2' in g\nx = g['x']", 2),
    ("g = {}\nl = {}\nexec 'x = 3' in g, l\nx = l['x']", 3),
])
def test_exec_statements(src, want):
    assert _run(src + "\n")["x"] == want


def test_a_continuation_line_inside_brackets_is_not_a_statement():
    ns = _run("x = (1,\n     print)\n")
    assert len(ns["x"]) == 2


def test_fix_syntax_leaves_valid_python_3_alone():
    src = "def f(a, b=2):\n    return {'a': a, 'b': [b, (1, 2)]}\n"
    assert source.fix_syntax(src) == src
