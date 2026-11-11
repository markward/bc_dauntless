"""engine.py15 lifts Python 1.5 control flow and the statements around it.

Each fixture is hand-assembled bytecode laid out exactly as CPython 1.5.2's
Python/compile.c emits it (com_if_stmt, com_and_test, com_while_stmt,
com_for_stmt, com_try_except, com_try_finally, com_assert_stmt, com_classdef,
com_import_stmt, com_expr_stmt, com_assign, ...), with SET_LINENO left out
where line numbers do not matter. The expected output is the AST the SDK
loader parses from the equivalent source. No BC or mod content: the stock
proof is tests/unit/test_py15_stock_oracle.py, over every retail module.
"""
import ast
import textwrap

import pytest

from engine.py15 import Py15Unsupported, lift
from tests.helpers import py15_assembler as A

M, F = A.module, A.function
RET = [("LOAD_CONST", 0), ("RETURN_VALUE",)]
POP = ("POP_TOP",)
CALL0 = ("CALL_FUNCTION", 0)


def L(name):
    return ("LABEL", name)


def _def(code_obj, name="f"):
    return M([("LOAD_CONST", 1), ("MAKE_FUNCTION", 0), ("STORE_NAME", 0)] + RET,
             consts=(None, code_obj), names=(name,))


FLOW = {
    "if-elif-else": (
        M([("LOAD_NAME", 0), ("JUMP_IF_FALSE", "e1"), POP,
           ("LOAD_CONST", 1), ("STORE_NAME", 1), ("JUMP_FORWARD", "end"),
           L("e1"), POP, ("LOAD_NAME", 2), ("JUMP_IF_FALSE", "e2"), POP,
           ("LOAD_CONST", 2), ("STORE_NAME", 1), ("JUMP_FORWARD", "end"),
           L("e2"), POP, ("LOAD_CONST", 3), ("STORE_NAME", 1),
           L("end")] + RET,
          consts=(None, 1, 2, 3), names=("a", "x", "b")),
        """
        if a:
            x = 1
        elif b:
            x = 2
        else:
            x = 3
        """),
    "if-on-a-boolean-condition": (
        M([("LOAD_NAME", 0), ("JUMP_IF_FALSE", "c"), POP, ("LOAD_NAME", 1),
           L("c"), ("JUMP_IF_FALSE", "e"), POP, ("LOAD_NAME", 2), CALL0, POP,
           ("JUMP_FORWARD", "end"), L("e"), POP, L("end")] + RET,
          names=("a", "b", "f")),
        """
        if a and b:
            f()
        """),
    "and-or": (
        M([("LOAD_NAME", 0), ("JUMP_IF_FALSE", "l1"), POP, ("LOAD_NAME", 1),
           L("l1"), ("JUMP_IF_TRUE", "l2"), POP, ("LOAD_NAME", 2),
           L("l2"), ("STORE_NAME", 3)] + RET,
          names=("a", "b", "c", "x")),
        "x = a and b or c"),
    # `a and (b and c)` compiles to these very bytes; the lifter picks flat.
    "and-chain-is-flat": (
        M([("LOAD_NAME", 0), ("JUMP_IF_FALSE", "l"), POP, ("LOAD_NAME", 1),
           ("JUMP_IF_FALSE", "l"), POP, ("LOAD_NAME", 2), L("l"),
           ("STORE_NAME", 3)] + RET,
          names=("a", "b", "c", "x")),
        "x = a and b and c"),
    "boolean-expression-statement": (
        M([("LOAD_NAME", 0), ("JUMP_IF_FALSE", "l"), POP, ("LOAD_NAME", 1),
           CALL0, L("l"), POP] + RET, names=("a", "f")),
        "a and f()"),
    "while-break-continue-else": (
        M([("SETUP_LOOP", "end"), L("top"), ("LOAD_NAME", 0),
           ("JUMP_IF_FALSE", "x"), POP,
           ("LOAD_NAME", 1), ("JUMP_IF_FALSE", "i1"), POP, ("BREAK_LOOP",),
           ("JUMP_FORWARD", "i1e"), L("i1"), POP, L("i1e"),
           ("LOAD_NAME", 2), ("JUMP_IF_FALSE", "i2"), POP,
           ("JUMP_ABSOLUTE", "top"), ("JUMP_FORWARD", "i2e"), L("i2"), POP,
           L("i2e"),
           ("LOAD_NAME", 3), CALL0, POP, ("JUMP_ABSOLUTE", "top"),
           L("x"), POP, ("POP_BLOCK",), ("LOAD_NAME", 4), CALL0, POP,
           L("end")] + RET,
          names=("a", "b", "c", "f", "g")),
        """
        while a:
            if b:
                break
            if c:
                continue
            f()
        else:
            g()
        """),
    "for-unpack-else": (
        M([("SETUP_LOOP", "end"), ("LOAD_NAME", 0), ("LOAD_CONST", 1),
           L("top"), ("FOR_LOOP", "x"), ("UNPACK_TUPLE", 2),
           ("STORE_NAME", 1), ("STORE_NAME", 2),
           ("LOAD_NAME", 3), ("LOAD_NAME", 1), ("CALL_FUNCTION", 1), POP,
           ("JUMP_ABSOLUTE", "top"), L("x"), ("POP_BLOCK",),
           ("LOAD_NAME", 4), CALL0, POP, L("end")] + RET,
          consts=(None, 0), names=("d", "k", "v", "f", "g")),
        """
        for k, v in d:
            f(k)
        else:
            g()
        """),
    "for-inside-while": (
        M([("SETUP_LOOP", "wend"), L("wtop"), ("LOAD_NAME", 0),
           ("JUMP_IF_FALSE", "wx"), POP,
           ("SETUP_LOOP", "fend"), ("LOAD_NAME", 1), ("LOAD_CONST", 1),
           L("ftop"), ("FOR_LOOP", "fx"), ("STORE_NAME", 2),
           ("BREAK_LOOP",), ("JUMP_ABSOLUTE", "ftop"),
           L("fx"), ("POP_BLOCK",), L("fend"),
           ("JUMP_ABSOLUTE", "wtop"), L("wx"), POP, ("POP_BLOCK",),
           L("wend")] + RET,
          consts=(None, 0), names=("a", "s", "i")),
        """
        while a:
            for i in s:
                break
        """),
    "try-except-else": (
        M([("SETUP_EXCEPT", "h"), ("LOAD_NAME", 0), CALL0, POP,
           ("POP_BLOCK",), ("JUMP_FORWARD", "else"),
           L("h"), ("DUP_TOP",), ("LOAD_NAME", 1), ("COMPARE_OP", 10),
           ("JUMP_IF_FALSE", "n1"), POP, POP, ("STORE_NAME", 2), POP,
           ("LOAD_NAME", 3), ("LOAD_NAME", 2), ("CALL_FUNCTION", 1), POP,
           ("JUMP_FORWARD", "end"), L("n1"), POP,
           POP, POP, POP, ("LOAD_NAME", 4), CALL0, POP,
           ("JUMP_FORWARD", "end"), ("END_FINALLY",),
           L("else"), ("LOAD_NAME", 5), CALL0, POP, L("end")] + RET,
          names=("f", "KeyError", "e", "g", "h", "i")),
        """
        try:
            f()
        except KeyError as e:
            g(e)
        except:
            h()
        else:
            i()
        """),
    "try-except-without-a-name": (
        M([("SETUP_EXCEPT", "h"), ("LOAD_NAME", 0), CALL0, POP,
           ("POP_BLOCK",), ("JUMP_FORWARD", "end"),
           L("h"), ("DUP_TOP",), ("LOAD_NAME", 1), ("COMPARE_OP", 10),
           ("JUMP_IF_FALSE", "n1"), POP, POP, POP, POP,
           ("JUMP_FORWARD", "end"), L("n1"), POP, ("END_FINALLY",),
           L("end")] + RET,
          names=("f", "NameError")),
        """
        try:
            f()
        except NameError:
            pass
        """),
    "try-finally": (
        M([("SETUP_FINALLY", "f"), ("LOAD_NAME", 0), CALL0, POP,
           ("POP_BLOCK",), ("LOAD_CONST", 0), L("f"),
           ("LOAD_NAME", 1), CALL0, POP, ("END_FINALLY",)] + RET,
          names=("f", "g")),
        """
        try:
            f()
        finally:
            g()
        """),
    "assert": (
        M([("LOAD_GLOBAL", 0), ("JUMP_IF_FALSE", "a1"), POP, ("LOAD_NAME", 1),
           ("JUMP_IF_TRUE", "a1"), POP, ("LOAD_GLOBAL", 2),
           ("RAISE_VARARGS", 1), L("a1"), POP,
           ("SET_LINENO", 2),
           ("LOAD_GLOBAL", 0), ("JUMP_IF_FALSE", "a2"), POP, ("LOAD_NAME", 1),
           ("JUMP_IF_TRUE", "a2"), POP, ("LOAD_GLOBAL", 2), ("LOAD_CONST", 1),
           ("RAISE_VARARGS", 2), L("a2"), POP] + RET,
          consts=(None, "m"), names=("__debug__", "x", "AssertionError")),
        """
        assert x
        assert x, 'm'
        """),
    "class-with-docstring-and-method": (
        M([("LOAD_CONST", 1), ("LOAD_NAME", 0), ("BUILD_TUPLE", 1),
           ("LOAD_CONST", 2), ("MAKE_FUNCTION", 0), CALL0, ("BUILD_CLASS",),
           ("STORE_NAME", 1)] + RET,
          consts=(None, "C", F("C", [
              ("LOAD_CONST", 0), ("STORE_NAME", 0),
              ("LOAD_CONST", 1), ("MAKE_FUNCTION", 0), ("STORE_NAME", 1),
              ("LOAD_LOCALS",), ("RETURN_VALUE",)],
              consts=("Doc.", F("m", [("LOAD_CONST", 1), ("RETURN_VALUE",)] + RET,
                                consts=(None, 1), varnames=("self",),
                                argcount=1)),
              names=("__doc__", "m"))),
          names=("B", "C")),
        """
        class C(B):
            'Doc.'
            def m(self):
                return 1
        """),
    "lambda-nested-def-varargs": (
        _def(F("f", [
            ("LOAD_CONST", 1), ("MAKE_FUNCTION", 0), ("STORE_FAST", 3),
            ("LOAD_CONST", 2), ("LOAD_CONST", 3), ("MAKE_FUNCTION", 1),
            ("STORE_FAST", 4), ("LOAD_FAST", 3), ("RETURN_VALUE",)] + RET,
            consts=(None,
                    F("g", [("LOAD_FAST", 0), ("RETURN_VALUE",)] + RET,
                      varnames=("x",), argcount=1),
                    2,
                    F("<lambda>", [("LOAD_FAST", 0), ("LOAD_FAST", 1),
                                   ("BINARY_ADD",), ("RETURN_VALUE",)],
                      varnames=("y", "z"), argcount=2)),
            varnames=("a", "args", "kw", "g", "h"), argcount=1,
            flags=A.FUNCTION_FLAGS | 0x4 | 0x8)),
        """
        def f(a, *args, **kw):
            def g(x):
                return x
            h = lambda y, z=2: y + z
            return g
        """),
    "from-imports": (
        M([("IMPORT_NAME", 0), ("IMPORT_FROM", 1), ("IMPORT_FROM", 2), POP,
           ("SET_LINENO", 2), ("IMPORT_NAME", 3), ("IMPORT_FROM", 4), POP]
          + RET, names=("a.b", "c", "d", "e", "*")),
        """
        from a.b import c, d
        from e import *
        """),
    # `import a; import b` on one line compiles to these bytes too.
    "import-a-b-is-one-statement": (
        M([("IMPORT_NAME", 0), ("STORE_NAME", 0), ("IMPORT_NAME", 1),
           ("STORE_NAME", 1), ("SET_LINENO", 2), ("IMPORT_NAME", 2),
           ("STORE_NAME", 2)] + RET, names=("a", "b", "c")),
        """
        import a, b
        import c
        """),
    "chained-assignment": (
        M([("LOAD_CONST", 1), ("DUP_TOP",), ("STORE_NAME", 0), ("DUP_TOP",),
           ("LOAD_NAME", 1), ("STORE_ATTR", 2), ("LOAD_NAME", 3),
           ("LOAD_CONST", 2), ("STORE_SUBSCR",)] + RET,
          consts=(None, 1, 0), names=("a", "b", "c", "d")),
        "a = b.c = d[0] = 1"),
    "nested-unpack": (
        M([("LOAD_NAME", 0), ("UNPACK_TUPLE", 2), ("STORE_NAME", 1),
           ("UNPACK_LIST", 2), ("STORE_NAME", 2), ("STORE_NAME", 3)] + RET,
          names=("t", "x", "y", "z")),
        "x, [y, z] = t"),
    "slices": (
        M([("LOAD_NAME", 0), ("LOAD_CONST", 1), ("SLICE_1",), ("STORE_NAME", 1),
           ("SET_LINENO", 2), ("LOAD_NAME", 2), ("LOAD_NAME", 0),
           ("LOAD_CONST", 2), ("STORE_SLICE_2",),
           ("SET_LINENO", 3), ("LOAD_NAME", 0), ("LOAD_CONST", 1),
           ("LOAD_CONST", 2), ("DELETE_SLICE_3",),
           ("SET_LINENO", 4), ("LOAD_NAME", 0), ("SLICE_0",),
           ("STORE_NAME", 3)] + RET,
          consts=(None, 1, 2), names=("s", "x", "y", "z")),
        """
        x = s[1:]
        s[:2] = y
        del s[1:2]
        z = s[:]
        """),
    "del-several-targets": (
        M([("DELETE_NAME", 0), ("LOAD_NAME", 1), ("DELETE_ATTR", 2),
           ("LOAD_NAME", 3), ("LOAD_CONST", 1), ("DELETE_SUBSCR",)] + RET,
          consts=(None, 0), names=("a", "b", "c", "d")),
        "del a, b.c, d[0]"),
    # `raise E, 'm'`: the source path writes it as `raise E('m')`.
    "raise-forms": (
        M([("RAISE_VARARGS", 0), ("SET_LINENO", 2), ("LOAD_NAME", 0),
           ("RAISE_VARARGS", 1), ("SET_LINENO", 3), ("LOAD_NAME", 0),
           ("LOAD_CONST", 1), ("RAISE_VARARGS", 2)] + RET,
          consts=(None, "m"), names=("E",)),
        """
        raise
        raise E
        raise E('m')
        """),
    "backticks-are-repr": (
        M([("LOAD_NAME", 0), ("UNARY_CONVERT",), ("STORE_NAME", 1)] + RET,
          names=("x", "s")),
        "s = repr(x)"),
    # `global X; import X` in a def binds the GLOBAL X.
    "global-import-keeps-its-global": (
        _def(F("f", [("IMPORT_NAME", 0), ("STORE_GLOBAL", 0)] + RET,
               names=("X",))),
        """
        def f():
            global X
            import X
        """),
    # A bare `return` is LOAD_CONST None; `return None` loads the NAME None.
    "bare-return-and-return-none": (
        _def(F("f", [
            ("LOAD_FAST", 0), ("JUMP_IF_FALSE", "l1"), POP,
            ("LOAD_CONST", 0), ("RETURN_VALUE",), ("JUMP_FORWARD", "e1"),
            L("l1"), POP, L("e1"),
            ("LOAD_FAST", 0), ("JUMP_IF_FALSE", "l2"), POP,
            ("LOAD_GLOBAL", 0), ("RETURN_VALUE",), ("JUMP_FORWARD", "e2"),
            L("l2"), POP, L("e2"),
            ("LOAD_FAST", 0), ("RETURN_VALUE",)] + RET,
            names=("None",), varnames=("a",), argcount=1)),
        """
        def f(a):
            if a:
                return
            if a:
                return None
            return a
        """),
    "trailing-comma-print-then-a-print-on-the-next-line": (
        M([("LOAD_CONST", 1), ("PRINT_ITEM",), ("SET_LINENO", 2),
           ("LOAD_CONST", 2), ("PRINT_ITEM",), ("PRINT_NEWLINE",)] + RET,
          consts=(None, "a", "b")),
        """
        print('a')
        print('b')
        """),
    # 1.5 writes 'a' before f() runs; the source path's print('a', f())
    # evaluates f() first, and the lifter matches the source path.
    "print-item-after-a-call-matches-the-source-path": (
        M([("LOAD_CONST", 1), ("PRINT_ITEM",), ("LOAD_NAME", 0), CALL0,
           ("PRINT_ITEM",), ("PRINT_NEWLINE",)] + RET,
          consts=(None, "a"), names=("f",)),
        "print('a', f())"),
    "statement-after-a-trailing-comma-print-keeps-its-order": (
        M([("LOAD_CONST", 1), ("PRINT_ITEM",), ("LOAD_NAME", 0), CALL0, POP,
           ("LOAD_CONST", 2), ("PRINT_ITEM",), ("PRINT_NEWLINE",)] + RET,
          consts=(None, "a", "b"), names=("foo",)),
        """
        print('a')
        foo()
        print('b')
        """),
}


@pytest.mark.parametrize("case", sorted(FLOW))
def test_control_flow_lifts_to_its_source(case):
    code, source = FLOW[case]
    got = lift(A.pyc(code))
    want = ast.parse(textwrap.dedent(source))
    assert ast.dump(got) == ast.dump(want), ast.unparse(got)
    compile(got, "<lifted>", "exec")


def test_a_lifted_loop_runs_like_its_source():
    namespace = {"a": [1, 2], "d": [(1, 2), (3, 4)], "f": None, "g": None}
    calls = []
    namespace["f"] = lambda k: calls.append(("f", k))
    namespace["g"] = lambda: calls.append(("g",))
    exec(compile(lift(A.pyc(FLOW["for-unpack-else"][0])), "<l>", "exec"),
         namespace)
    assert calls == [("f", 1), ("f", 3), ("g",)]


SHAPES = {
    "lambda body is not one expression": _def(F("<lambda>", RET)),
    "tuple parameters": _def(F("f", RET, varnames=(".0",), argcount=1)),
    "DUP_TOP outside a dict literal or assignment": M(
        [("IMPORT_NAME", 0), ("DUP_TOP",)] + RET, names=("a",)),
    "raise with a traceback": M(
        [("LOAD_NAME", 0), ("LOAD_NAME", 0), ("LOAD_NAME", 0),
         ("RAISE_VARARGS", 3)] + RET, names=("E",)),
    "jump that is not a continue": M([("JUMP_ABSOLUTE", 0)] + RET),
    "except target is not a name": M(
        [("SETUP_EXCEPT", "h"), ("POP_BLOCK",), ("JUMP_FORWARD", "end"),
         L("h"), ("DUP_TOP",), ("LOAD_NAME", 0), ("COMPARE_OP", 10),
         ("JUMP_IF_FALSE", "n"), POP, POP,
         ("LOAD_NAME", 1), ("STORE_ATTR", 2), POP,
         ("JUMP_FORWARD", "end"), L("n"), POP, ("END_FINALLY",),
         L("end")] + RET,
        names=("E", "o", "a")),
    "loop with values pending on the stack": M(
        [("LOAD_NAME", 0), ("SETUP_LOOP", "e"), ("POP_BLOCK",), L("e"), POP]
        + RET, names=("a",)),
}


@pytest.mark.parametrize("needle", sorted(SHAPES))
def test_a_shape_outside_the_lifter_is_refused(needle):
    with pytest.raises(Py15Unsupported, match=needle):
        lift(A.pyc(SHAPES[needle]))
