"""engine.py15 lifts straight-line Python 1.5 bytecode to a Python 3 AST.

Every fixture is hand-assembled 1.5 bytecode (tests/helpers/py15_assembler),
so this file needs no BC install and contains no BC or mod content. The
expected output is always the AST the SDK loader would parse from the same
module's source -- that is the lifter's whole contract.
"""
import ast
import random
import textwrap

import pytest

from engine import py15
from engine.py15 import Py15Unsupported, lift
from engine.py15.marshal15 import Code15
from tests.helpers import py15_assembler as A

M, F = A.module, A.function
RET = [("LOAD_CONST", 0), ("RETURN_VALUE",)]


def _same(code, source):
    got = lift(A.pyc(code))
    want = ast.parse(textwrap.dedent(source))
    assert ast.dump(got) == ast.dump(want), ast.unparse(got)


def test_the_projectile_shape_lifts_to_its_source():
    _same(A.projectile_module(), """
        import App
        def Create(pTorp):
            pTorp.SetDamage(GetDamage())
            import Multiplayer.SpeciesToTorp
            pTorp.SetNetType(Multiplayer.SpeciesToTorp.PHOTON)
            return 0
        def GetDamage():
            return 500.0
    """)


def test_set_lineno_becomes_statement_line_numbers():
    tree = lift(A.pyc(A.projectile_module()))
    assert [s.lineno for s in tree.body] == [1, 2, 7]
    assert [s.lineno for s in tree.body[1].body] == [3, 4, 5, 6]


CASES = {
    # 1.5 has no None constant: it is LOAD_GLOBAL/LOAD_NAME "None".
    "none-is-a-name-in-1.5": (
        M([("LOAD_GLOBAL", 0), ("STORE_NAME", 1)] + RET, names=("None", "x")),
        "x = None"),
    "dict-literal": (
        M([("BUILD_MAP", 0),
           ("DUP_TOP",), ("LOAD_CONST", 1), ("ROT_TWO",), ("LOAD_CONST", 2),
           ("STORE_SUBSCR",),
           ("DUP_TOP",), ("LOAD_CONST", 3), ("ROT_TWO",), ("LOAD_CONST", 4),
           ("STORE_SUBSCR",),
           ("STORE_NAME", 0)] + RET,
          consts=(None, 1, "a", 2, "b"), names=("d",)),
        "d = {'a': 1, 'b': 2}"),
    # _fix_py2_syntax rewrites `.has_key(` in source; same result here.
    "has-key-call": (
        M([("LOAD_NAME", 0), ("LOAD_ATTR", 1), ("LOAD_CONST", 1),
           ("CALL_FUNCTION", 1), ("STORE_NAME", 2)] + RET,
          consts=(None, "a"), names=("d", "has_key", "x")),
        "x = d.__contains__('a')"),
    "print-statement": (
        M([("LOAD_CONST", 1), ("PRINT_ITEM",), ("LOAD_NAME", 0),
           ("PRINT_ITEM",), ("PRINT_NEWLINE",), ("PRINT_NEWLINE",)] + RET,
          consts=(None, "a"), names=("b",)),
        "print('a', b)\nprint()"),
    "function-docstring-and-global": (
        M([("LOAD_CONST", 1), ("MAKE_FUNCTION", 0), ("STORE_NAME", 0)] + RET,
          consts=(None, F("f", [("LOAD_CONST", 1), ("STORE_GLOBAL", 0),
                                ("LOAD_CONST", 2), ("RETURN_VALUE",)],
                          consts=("Doc.", 1, None), names=("g",))),
          names=("f",)),
        "def f():\n    'Doc.'\n    global g\n    g = 1"),
    "module-docstring": (
        M([("LOAD_CONST", 1), ("STORE_NAME", 0)] + RET,
          consts=(None, "Module doc."), names=("__doc__",)),
        "'Module doc.'"),
    "default-arguments": (
        M([("LOAD_CONST", 1), ("LOAD_CONST", 2), ("MAKE_FUNCTION", 1),
           ("STORE_NAME", 0)] + RET,
          consts=(None, 2.0, F("f", [("LOAD_FAST", 1), ("RETURN_VALUE",)] + RET,
                               varnames=("a", "b"), argcount=2)),
          names=("f",)),
        "def f(a, b=2.0):\n    return b"),
    "keyword-call": (
        M([("LOAD_NAME", 0), ("LOAD_CONST", 1), ("LOAD_CONST", 2),
           ("CALL_FUNCTION", 256), ("POP_TOP",)] + RET,
          consts=(None, "x", 1), names=("f",)),
        "f(x=1)"),
    "stores-operators-compare": (
        M([("LOAD_NAME", 0), ("LOAD_NAME", 1), ("STORE_ATTR", 2),
           ("LOAD_CONST", 1), ("LOAD_NAME", 1), ("LOAD_CONST", 2),
           ("STORE_SUBSCR",),
           ("LOAD_NAME", 1), ("LOAD_CONST", 2), ("BINARY_SUBSCR",),
           ("LOAD_CONST", 3), ("BINARY_DIVIDE",), ("UNARY_NEGATIVE",),
           ("STORE_NAME", 3),
           ("LOAD_NAME", 3), ("LOAD_CONST", 4), ("COMPARE_OP", 7),
           ("STORE_NAME", 4)] + RET,
          consts=(None, 5, 0, 2.0, (1, 2)), names=("v", "o", "attr", "y", "z")),
        "o.attr = v\no[0] = 5\ny = -(o[0] / 2.0)\nz = y not in (1, 2)"),
    # The SDK loader reads source as utf-8 with errors="replace".
    "non-utf8-string-matches-the-source-path": (
        M([("LOAD_CONST", 1), ("STORE_NAME", 0)] + RET,
          consts=(None, b"caf\xe9"), names=("s",)),
        "s = 'caf�'"),
    "list-in-tuple": (
        M([("LOAD_CONST", 1), ("LOAD_CONST", 2), ("BUILD_LIST", 2),
           ("BUILD_TUPLE", 1), ("STORE_NAME", 0)] + RET,
          consts=(None, 1, 2), names=("t",)),
        "t = ([1, 2],)"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_supported_construct_lifts_to_its_source(case):
    code, source = CASES[case]
    _same(code, source)


@pytest.mark.parametrize("opname", [
    "JUMP_IF_FALSE", "JUMP_IF_TRUE", "JUMP_FORWARD", "JUMP_ABSOLUTE",
    "FOR_LOOP", "SETUP_LOOP", "SETUP_EXCEPT", "SETUP_FINALLY", "BUILD_CLASS",
    "IMPORT_FROM", "UNPACK_TUPLE", "UNPACK_LIST", "EXEC_STMT", "UNARY_CONVERT",
    "RAISE_VARARGS", "DELETE_NAME", "SLICE_0", "LOAD_LOCALS", "PRINT_EXPR",
    "BUILD_SLICE",
])
def test_an_opcode_outside_the_subset_is_refused_by_name(opname):
    ins = (opname, 0) if A.OPCODES[opname] >= 90 else (opname,)
    code = M([("LOAD_CONST", 0), ins] + RET, names=("n",))
    with pytest.raises(Py15Unsupported) as info:
        lift(A.pyc(code))
    assert (info.value.opcode, info.value.offset) == (opname, 3)
    assert opname in str(info.value)


def _def(code_obj):
    return M([("LOAD_CONST", 1), ("MAKE_FUNCTION", 0), ("STORE_NAME", 0)] + RET,
             consts=(None, code_obj), names=("f",))


SHAPES = {
    "*args": _def(F("f", RET, flags=A.FUNCTION_FLAGS | 0x4, varnames=("a",))),
    "lambda": _def(F("<lambda>", RET)),
    "nested function": _def(F(
        "f", [("LOAD_CONST", 1), ("MAKE_FUNCTION", 0), ("STORE_FAST", 0)] + RET,
        consts=(None, F("g", RET)), varnames=("g",))),
    "import alias": M([("IMPORT_NAME", 0), ("STORE_NAME", 1)] + RET,
                      names=("a.b", "x")),
    "DUP_TOP outside a dict literal": M(
        [("LOAD_CONST", 1), ("DUP_TOP",), ("STORE_NAME", 0),
         ("STORE_NAME", 1)] + RET, consts=(None, 1), names=("a", "b")),
    "module-level return": M([("LOAD_CONST", 1), ("RETURN_VALUE",)] + RET,
                             consts=(None, 1)),
    "trailing comma": M([("LOAD_CONST", 1), ("PRINT_ITEM",)] + RET,
                        consts=(None, 1)),
    "malformed bytecode": M([("LOAD_CONST", 7)] + RET),
}


@pytest.mark.parametrize("needle", sorted(SHAPES))
def test_a_shape_outside_the_subset_is_refused(needle):
    with pytest.raises(Py15Unsupported, match=needle.replace("*", r"\*")):
        lift(A.pyc(SHAPES[needle]))


def test_an_unknown_opcode_byte_is_refused():
    base = M(RET)
    code = Code15(base.argcount, base.nlocals, base.stacksize, base.flags,
                  bytes([200]) + base.code, base.consts, base.names,
                  base.varnames, base.filename, base.name, base.firstlineno,
                  base.lnotab)
    with pytest.raises(Py15Unsupported, match="unknown opcode 200"):
        lift(A.pyc(code))


def test_non_15_bytecode_is_refused():
    with pytest.raises(Py15Unsupported, match="not Python 1.5"):
        lift(b"\xa7\r\r\n" + A.pyc(M(RET))[4:])


def test_corrupt_bytecode_only_ever_raises_py15unsupported():
    """Truncated or bit-flipped files must give the one exception the loader
    turns into a log line -- never a struct.error/IndexError from deep in a
    half-read value -- and whatever still lifts must compile."""
    data = A.pyc(A.projectile_module())
    for n in range(len(data)):
        with pytest.raises(Py15Unsupported):
            lift(data[:n])
    rng = random.Random(1)
    for _ in range(2000):
        mutated = bytearray(data)
        mutated[rng.randrange(8, len(mutated))] = rng.randrange(256)
        try:
            tree = lift(bytes(mutated))
        except Py15Unsupported:
            continue
        compile(tree, "<fuzz>", "exec")


def test_the_lifted_projectile_runs_create_against_the_real_sdk():
    """Executed in the test harness: `import App` is our shim and
    Multiplayer.SpeciesToTorp is the real SDK module."""
    import Multiplayer.SpeciesToTorp as species

    namespace = {}
    exec(compile(lift(A.pyc(A.projectile_module(750.0))), "<lifted>", "exec"),
         namespace)
    calls = []

    class Recorder:
        def __getattr__(self, name):
            return lambda *args: calls.append((name,) + args)

    assert namespace["Create"](Recorder()) == 0
    assert calls == [("SetDamage", 750.0), ("SetNetType", species.PHOTON)]


@pytest.fixture
def _fresh_reports():
    py15._reported.clear()
    yield
    py15._reported.clear()


def test_load_tree_returns_the_module_ast(tmp_path, _fresh_reports, capsys):
    path = tmp_path / "Ok.pyc"
    path.write_bytes(A.pyc(A.projectile_module()))
    tree = py15.load_tree(path, "Tactical.Projectiles.Ok")
    assert isinstance(tree, ast.Module)
    assert "[sdk-loader]" not in capsys.readouterr().out


def test_load_tree_names_an_unloadable_file_exactly_once(tmp_path, _fresh_reports,
                                                         capsys):
    path = tmp_path / "Jumpy.pyc"
    path.write_bytes(A.pyc(M([("JUMP_FORWARD", 0)] + RET)))
    for _ in range(2):
        with pytest.raises(Py15Unsupported) as info:
            py15.load_tree(path, "Tactical.Projectiles.Jumpy")
        assert info.value.path == str(path)
    lines = [l for l in capsys.readouterr().out.splitlines() if "[sdk-loader]" in l]
    assert len(lines) == 1
    assert "Tactical.Projectiles.Jumpy" in lines[0]
    assert "JUMP_FORWARD" in lines[0]
