"""Turn Python 1.5 bytecode into a Python 3 ``ast.Module``.

The output is the tree the SDK loader would have built from the module's
source: ``ast.parse(engine.py15.source.fix_source(source))``. The loader then
runs the same compatibility transforms over it, so a ``.pyc`` loads exactly
as its ``.py`` would.

Python 1.5's compiler has no optimiser: every statement compiles to one fixed
instruction shape (Python/compile.c, 1.5.2). The lifter recognises those
shapes by recursive descent over instruction ranges -- ``if``/``elif``/
``else``, ``and``/``or``, ``while``, ``for``, ``try``/``except``/``else``,
``try``/``finally``, ``assert``, classes, lambdas, nested and variadic
functions, ``from`` imports, chained and unpacking assignment, slices,
``del`` and ``raise`` -- and refuses everything else with
``Py15Unsupported`` rather than guessing.

A shape enters the accepted set only when the stock-corpus oracle
(tests/unit/test_py15_stock_oracle.py) proves stock modules using it lift to
the AST their SDK source parses to. Known places where two sources compile to
the same bytecode, so the lifter picks one (same program either way):
``a and (b and c)`` lifts flat as ``a and b and c``; ``import a; import b`` on
one line lifts as ``import a, b`` (and ``del`` likewise).

Specs: docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md,
docs/superpowers/specs/2026-11-11-legacy-script-parsing-design.md
"""
from __future__ import annotations

import ast
import bisect
import sys

from . import opcodes15 as op
from .marshal15 import Code15, Py15FormatError, load_pyc
from .source import decode_text


class Py15Unsupported(ImportError):
    """Python 1.5 bytecode this engine cannot load (yet)."""

    def __init__(self, reason, opcode=None, offset=None, path=None):
        self.reason = reason
        self.opcode = opcode
        self.offset = offset
        where = "" if opcode is None else " (%s at offset %d)" % (opcode, offset)
        super().__init__(reason + where, path=path)


_BINARY = {
    "BINARY_ADD": ast.Add, "BINARY_SUBTRACT": ast.Sub,
    "BINARY_MULTIPLY": ast.Mult, "BINARY_DIVIDE": ast.Div,
    "BINARY_MODULO": ast.Mod, "BINARY_POWER": ast.Pow,
    "BINARY_LSHIFT": ast.LShift, "BINARY_RSHIFT": ast.RShift,
    "BINARY_AND": ast.BitAnd, "BINARY_OR": ast.BitOr, "BINARY_XOR": ast.BitXor,
}
_UNARY = {
    "UNARY_NEGATIVE": ast.USub, "UNARY_POSITIVE": ast.UAdd,
    "UNARY_INVERT": ast.Invert, "UNARY_NOT": ast.Not,
}
_COMPARE = (ast.Lt, ast.LtE, ast.Eq, ast.NotEq, ast.Gt, ast.GtE, ast.In,
            ast.NotIn, ast.Is, ast.IsNot)
_EXC_MATCH = 10
_RELATIVE = frozenset({"JUMP_FORWARD", "JUMP_IF_FALSE", "JUMP_IF_TRUE",
                       "FOR_LOOP", "SETUP_LOOP", "SETUP_EXCEPT",
                       "SETUP_FINALLY"})
_STORES = frozenset({"STORE_NAME", "STORE_FAST", "STORE_GLOBAL"})
# type_params is a 3.12 field (PEP 695). Nothing in 1.5 bytecode carries
# type parameters; passing an empty list keeps a lifted tree's ast.dump()
# identical to a parsed one. A 3.11 interpreter rejects the keyword.
_TYPE_PARAMS = {"type_params": []} if sys.version_info >= (3, 12) else {}


# -- stack values that are not expressions -------------------------------------

class _Import:
    def __init__(self, name):
        self.name = name
        self.froms = None       # IMPORT_FROM names, once any is seen


class _CodeRef:
    def __init__(self, code):
        self.code = code


class _Function:
    def __init__(self, code, defaults):
        self.code = code
        self.defaults = defaults


class _ClassBody:
    """MAKE_FUNCTION + CALL_FUNCTION 0: a class body about to be built."""

    def __init__(self, code):
        self.code = code


class _Class:
    def __init__(self, name, bases, code):
        self.name = name
        self.bases = bases
        self.code = code


class _Locals:
    """LOAD_LOCALS: the end of a class body."""


class _DictDup:
    """The DUP_TOP'd dict of a 1.5 dict literal: BUILD_MAP, then per pair
    DUP_TOP <value> ROT_TWO <key> STORE_SUBSCR."""

    def __init__(self, target):
        self.target = target


# -- assignment targets in progress ---------------------------------------------

class _Slot:
    """A value on the stack that a store will consume as a TARGET rather than
    as the value of a new assignment."""

    def __init__(self, owner, index):
        self.owner = owner
        self.index = index


class _Assign:
    """``a = b = v`` and the root of ``a, b = v``: one value, the targets in
    the order their stores run."""

    def __init__(self, value):
        self.value = value
        self.targets = []
        self.open = 0

    def slot(self):
        self.open += 1
        return _Slot(self, None)

    def fill(self, lifter, index, node):
        self.targets.append(node)
        self.open -= 1
        if not self.open:
            lifter.emit(ast.Assign(self.targets, self.value))


class _Unpack:
    """UNPACK_TUPLE / UNPACK_LIST: n element targets, then one target."""

    def __init__(self, parent, n, as_list):
        self.parent = parent
        self.elts = [None] * n
        self.open = n
        self.as_list = as_list

    def fill(self, lifter, index, node):
        self.elts[index] = node
        self.open -= 1
        if not self.open:
            node = (ast.List if self.as_list else ast.Tuple)(self.elts, ast.Store())
            lifter.fill(self.parent, node)


class _Capture:
    """A lone target with no assignment: a for-loop or except-clause name."""

    def __init__(self):
        self.node = None

    def fill(self, lifter, index, node):
        self.node = node


# -- decoding ------------------------------------------------------------------

def _instructions(code: bytes):
    """(offset, name, arg) for every instruction; arg is None below
    HAVE_ARGUMENT."""
    i = 0
    while i < len(code):
        num = code[i]
        name = op.NAMES.get(num)
        if name is None:
            raise Py15Unsupported("unknown opcode %d" % num, "?", i)
        if num >= op.HAVE_ARGUMENT:
            if i + 2 >= len(code):
                raise Py15Unsupported("truncated instruction", name, i)
            yield i, name, code[i + 1] | (code[i + 2] << 8)
            i += 3
        else:
            yield i, name, None
            i += 1


class _Ins:
    __slots__ = ("off", "name", "arg", "line")

    def __init__(self, off, name, arg, line):
        self.off, self.name, self.arg, self.line = off, name, arg, line


def _decode(co):
    """Instructions with SET_LINENO folded into a per-instruction line."""
    out, line = [], max(co.firstlineno or 1, 1)
    for off, name, arg in _instructions(co.code):
        if name == "SET_LINENO":
            line = max(arg, 1)
        else:
            out.append(_Ins(off, name, arg, line))
    return out


def _text(raw: bytes) -> str:
    # The same character for each byte as the source path gives it, whether
    # the source wrote the byte raw or as an escape (source.decode_text).
    return decode_text(raw)


def _const(value):
    if isinstance(value, bytes):
        return ast.Constant(_text(value))
    if isinstance(value, int) and not isinstance(value, bool) and value < 0:
        # 1.5 compiles `-5` as 5 then UNARY_NEGATIVE; a negative constant is
        # a 32-bit hex/octal literal (0xFFFFFFFF), which the source path
        # writes as (-1).
        return ast.UnaryOp(ast.USub(), ast.Constant(-value))
    if isinstance(value, tuple):
        return ast.Tuple([_const(v) for v in value], ast.Load())
    if value is None or isinstance(value, (int, float, complex)) \
            or value is Ellipsis:
        return ast.Constant(value)
    raise Py15Unsupported("constant of type %s" % type(value).__name__)


def _place(node, lineno):
    """Give a node a source span starting at ``lineno`` that covers every
    statement inside it; fix_missing_locations fills the expressions."""
    node.lineno = lineno
    node.col_offset = node.end_col_offset = 0
    end = lineno
    for child in ast.walk(node):
        if child is not node and isinstance(child, ast.stmt):
            end = max(end, getattr(child, "end_lineno", None) or child.lineno)
    node.end_lineno = end
    return node


def _is_none_return(stmt):
    return (isinstance(stmt, ast.Return)
            and (stmt.value is None
                 or (isinstance(stmt.value, ast.Constant)
                     and stmt.value.value is None)))


class _Lifter:
    """One code object. ``kind`` is module, class, function or lambda."""

    def __init__(self, code: Code15, kind: str):
        self.co = code
        self.kind = kind
        self.ins = _decode(code)
        self.offs = [i.off for i in self.ins]
        self.stack = []
        self.body = []
        self.globals = []
        self.loops = []          # loop-top instruction indices, innermost last
        self.print_items = None
        self.print_line = None
        self.lineno = max(code.firstlineno or 1, 1)

    # -- helpers ---------------------------------------------------------
    def fail(self, reason, k=None):
        if k is None:
            raise Py15Unsupported(reason)
        raise Py15Unsupported(reason, self.ins[k].name, self.ins[k].off)

    def at(self, k, *names):
        return 0 <= k < len(self.ins) and self.ins[k].name in names

    def target(self, k):
        """Index of the instruction jump ``k`` lands on (past SET_LINENO)."""
        ins = self.ins[k]
        dest = ins.arg if ins.name == "JUMP_ABSOLUTE" else ins.off + 3 + ins.arg
        return bisect.bisect_left(self.offs, dest)

    def flush_print(self):
        if self.print_items is not None:
            # `print a,` -- 1.5 suppresses the newline; the source path's
            # `print(a,)` prints it. Same AST either way.
            items, self.print_items = self.print_items, None
            self.emit(ast.Expr(ast.Call(ast.Name("print", ast.Load()), items, [])))

    def emit(self, stmt):
        if self.print_items is not None:
            self.flush_print()
        if self.stack:
            # Values still pending would be evaluated AFTER this statement
            # once lifted (f() g() POP POP runs f first in 1.5, g first here).
            raise Py15Unsupported("statement with values pending on the stack")
        prev = self.body[-1] if self.body else None
        # `import a, b` and `del a, b` are one statement; the bytecode is the
        # same as two, minus the SET_LINENO between them.
        if (isinstance(stmt, (ast.Import, ast.Delete)) and type(prev) is type(stmt)
                and prev.lineno == self.lineno):
            if isinstance(stmt, ast.Import):
                prev.names.extend(stmt.names)
            else:
                prev.targets.extend(stmt.targets)
            return
        self.body.append(_place(stmt, self.lineno))

    def pop_expr(self, k):
        if not self.stack:
            self.fail("stack underflow", k)
        value = self.stack.pop()
        if not isinstance(value, ast.expr):
            self.fail("%s used as a value" % type(value).__name__, k)
        return value

    def fill(self, slot, node):
        slot.owner.fill(self, slot.index, node)

    def store_to(self, node, k):
        """Store the top of the stack into target ``node``."""
        if not self.stack:
            self.fail("stack underflow", k)
        value = self.stack.pop()
        if isinstance(value, _Slot):
            self.fill(value, node)
        elif isinstance(value, ast.expr):
            self.emit(ast.Assign([node], value))
        else:
            self.fail("%s stored" % type(value).__name__, k)

    def block(self, i, j, loop_top=None):
        """The statements of instructions [i, j)."""
        saved = (self.stack, self.body, self.print_items)
        self.stack, self.body, self.print_items = [], [], None
        if loop_top is not None:
            self.loops.append(loop_top)
        try:
            while i < j:
                i = self.step(i, j)
            if i != j:
                self.fail("block overran its end")
            self.flush_print()
            if self.stack:
                self.fail("values left on the stack")
            return self.body or [_place(ast.Pass(), self.lineno)]
        finally:
            if loop_top is not None:
                self.loops.pop()
            self.stack, self.body, self.print_items = saved

    def expr(self, i, j):
        """The single expression instructions [i, j) compute."""
        saved = (self.stack, self.body)
        self.stack, self.body = [], []
        try:
            while i < j:
                i = self.step(i, j)
            if i != j or self.body or len(self.stack) != 1 \
                    or not isinstance(self.stack[0], ast.expr):
                self.fail("not a single expression")
            return self.stack[0]
        finally:
            self.stack, self.body = saved

    def capture(self, i, j):
        """Run instructions from ``i`` until one target has been stored;
        return (target node, next index)."""
        cap = _Capture()
        saved = (self.stack, self.body)
        self.stack, self.body = [_Slot(cap, None)], []
        try:
            while cap.node is None:
                if i >= j:
                    self.fail("target ran past its block")
                i = self.step(i, j)
            if self.body or self.stack:
                self.fail("not a simple target")
            return cap.node, i
        finally:
            self.stack, self.body = saved

    # -- definitions -------------------------------------------------------
    def arguments(self, co, defaults, k):
        if any(not v.isidentifier() for v in co.varnames[:co.argcount]):
            self.fail("tuple parameters", k)
        params = [ast.arg(p) for p in co.varnames[:co.argcount]]
        extra = co.argcount
        vararg = kwarg = None
        if co.flags & op.CO_VARARGS:
            vararg = ast.arg(co.varnames[extra])
            extra += 1
        if co.flags & op.CO_VARKEYWORDS:
            kwarg = ast.arg(co.varnames[extra])
        return ast.arguments(posonlyargs=[], args=params, vararg=vararg,
                             kwonlyargs=[], kw_defaults=[], kwarg=kwarg,
                             defaults=defaults)

    def function_def(self, name, func, k):
        co = func.code
        if co.name != name:
            self.fail("function %r stored as %r" % (co.name, name), k)
        args = self.arguments(co, func.defaults, k)
        body = _Lifter(co, "function").run()
        while body and _is_none_return(body[-1]):
            body.pop()
        # 1.5 always reserves co_consts[0] for the docstring (None if absent).
        if co.consts and isinstance(co.consts[0], bytes):
            body.insert(0, _place(ast.Expr(ast.Constant(_text(co.consts[0]))),
                                  max(co.firstlineno, 1)))
        if not body:
            body = [_place(ast.Pass(), max(co.firstlineno, 1))]
        node = ast.FunctionDef(name=name, args=args, body=body,
                               decorator_list=[], returns=None,
                               type_comment=None, **_TYPE_PARAMS)
        return node

    def lambda_expr(self, func, k):
        co = func.code
        args = self.arguments(co, func.defaults, k)
        body = _Lifter(co, "lambda").run()
        while len(body) > 1 and _is_none_return(body[-1]):
            body.pop()
        if len(body) != 1 or not isinstance(body[0], ast.Return) \
                or body[0].value is None:
            self.fail("lambda body is not one expression", k)
        return ast.Lambda(args, body[0].value)

    def class_def(self, name, cls, k):
        if cls.name != name:
            self.fail("class %r stored as %r" % (cls.name, name), k)
        body = _Lifter(cls.code, "class").run()
        return ast.ClassDef(name=name, bases=cls.bases, keywords=[], body=body,
                            decorator_list=[], **_TYPE_PARAMS)

    def store_name(self, name, is_global, k):
        if not self.stack:
            self.fail("stack underflow", k)
        value = self.stack[-1]
        if is_global and self.kind == "function" and name not in self.globals:
            self.globals.append(name)
        if isinstance(value, _Import):
            self.stack.pop()
            if value.froms is not None or value.name.split(".")[0] != name:
                self.fail("import alias", k)
            self.emit(ast.Import([ast.alias(value.name, None)]))
        elif isinstance(value, _Function):
            self.stack.pop()
            self.emit(self.function_def(name, value, k))
        elif isinstance(value, _Class):
            self.stack.pop()
            self.emit(self.class_def(name, value, k))
        elif (self.kind != "function" and name == "__doc__" and not self.body
              and isinstance(value, ast.Constant) and isinstance(value.value, str)):
            self.stack.pop()
            self.emit(ast.Expr(value))           # the module/class docstring
        else:
            self.store_to(ast.Name(name, ast.Store()), k)

    # -- control flow --------------------------------------------------------
    def conditional(self, k, j):
        """JUMP_IF_FALSE / JUMP_IF_TRUE at ``k``: an if statement, an assert,
        or a boolean operator."""
        ins = self.ins[k]
        t = self.target(k)
        if t > j or not self.at(k + 1, "POP_TOP"):
            self.fail("conditional jump out of its block", k)
        if ins.name == "JUMP_IF_FALSE" and len(self.stack) == 1:
            top = self.stack[0]
            if isinstance(top, ast.Name) and top.id == "__debug__":
                return self.assert_stmt(k, t, j)
            if (self.at(t, "POP_TOP") and t - 1 > k
                    and self.at(t - 1, "JUMP_FORWARD")):
                cond = self.pop_expr(k)
                end = self.target(t - 1)
                if end < t or end > j:
                    self.fail("if statement end out of its block", t - 1)
                body = self.block(k + 2, t - 1)
                orelse = self.block(t + 1, end) if end > t + 1 else []
                self.lineno = ins.line
                self.emit(ast.If(cond, body, orelse))
                return end
        left = self.pop_expr(k)
        right = self.expr(k + 2, t)
        cls = ast.And if ins.name == "JUMP_IF_FALSE" else ast.Or
        values = [left]
        if isinstance(right, ast.BoolOp) and isinstance(right.op, cls):
            values += right.values
        else:
            values.append(right)
        self.stack.append(ast.BoolOp(cls(), values))
        return t

    def assert_stmt(self, k, t, j):
        # LOAD_GLOBAL __debug__; JUMP_IF_FALSE t; POP_TOP; <test>;
        # JUMP_IF_TRUE t; POP_TOP; LOAD_GLOBAL AssertionError; [<msg>];
        # RAISE_VARARGS 2 (1 with no message); t: POP_TOP
        m = next((x for x in range(k + 2, t)
                  if self.at(x, "JUMP_IF_TRUE") and self.target(x) == t
                  and self.at(x + 1, "POP_TOP") and self.at(x + 2, "LOAD_GLOBAL")
                  and self.co.names[self.ins[x + 2].arg] == "AssertionError"), None)
        if m is None or not self.at(t - 1, "RAISE_VARARGS") \
                or self.ins[t - 1].arg not in (1, 2) or not self.at(t, "POP_TOP"):
            self.fail("unrecognised assert", k)
        self.stack.pop()
        test = self.expr(k + 2, m)
        msg = None
        if self.ins[t - 1].arg == 2:
            msg = self.expr(m + 3, t - 1)
        elif m + 3 != t - 1:
            self.fail("unrecognised assert", k)
        self.lineno = self.ins[k].line
        self.emit(ast.Assert(test, msg))
        return t + 1

    def loop(self, k, j):
        end = self.target(k)
        if end > j:
            self.fail("loop end out of its block", k)
        line = self.ins[k].line
        first = k + 1
        # for: SETUP_LOOP; <seq>; LOAD_CONST 0; top: FOR_LOOP x; <target>;
        #      <body>; JUMP_ABSOLUTE top; x: POP_BLOCK; <else>; end:
        f = next((x for x in range(first, end) if self.ins[x].name in
                  ("FOR_LOOP", "SETUP_LOOP")), None)
        if f is not None and self.at(f, "FOR_LOOP") and self.at(f - 1, "LOAD_CONST") \
                and self.co.consts[self.ins[f - 1].arg] == 0:
            x = self.target(f)
            if not (self.at(x, "POP_BLOCK") and self.at(x - 1, "JUMP_ABSOLUTE")
                    and self.target(x - 1) == f and x < end):
                self.fail("unrecognised for loop", f)
            seq = self.expr(first, f - 1)
            tgt, body_start = self.capture(f + 1, x - 1)
            body = self.block(body_start, x - 1, loop_top=f)
            orelse = self.block(x + 1, end) if end > x + 1 else []
            self.lineno = line
            self.emit(ast.For(tgt, seq, body, orelse, None))
            return end
        # while: SETUP_LOOP; top: <cond>; JUMP_IF_FALSE x; POP_TOP; <body>;
        #        JUMP_ABSOLUTE top; x: POP_TOP; POP_BLOCK; <else>; end:
        for m in range(first, end):
            if not self.at(m, "JUMP_IF_FALSE"):
                continue
            x = self.target(m)
            if (self.at(x, "POP_TOP") and self.at(x + 1, "POP_BLOCK")
                    and self.at(x - 1, "JUMP_ABSOLUTE")
                    and self.target(x - 1) == first and self.at(m + 1, "POP_TOP")):
                cond = self.expr(first, m)
                body = self.block(m + 2, x - 1, loop_top=first)
                orelse = self.block(x + 2, end) if end > x + 2 else []
                self.lineno = line
                self.emit(ast.While(cond, body, orelse))
                return end
        self.fail("unrecognised loop", k)

    def try_except(self, k, j):
        # SETUP_EXCEPT h; <body>; POP_BLOCK; JUMP_FORWARD e; h: <clauses>
        # END_FINALLY; e: <else>; end:
        h = self.target(k)
        if not (self.at(h - 1, "JUMP_FORWARD") and self.at(h - 2, "POP_BLOCK")):
            self.fail("unrecognised try", k)
        e = self.target(h - 1)
        if not self.at(e - 1, "END_FINALLY") or e > j:
            self.fail("unrecognised try", k)
        line = self.ins[k].line
        body = self.block(k + 1, h - 2)
        handlers, end, i = [], None, h
        while i < e - 1:
            hline = self.ins[i].line
            if self.at(i, "DUP_TOP"):
                # DUP_TOP; <type>; COMPARE_OP exception-match; JUMP_IF_FALSE n;
                # POP_TOP; POP_TOP; <name> | POP_TOP; POP_TOP; <body>;
                # JUMP_FORWARD end; n: POP_TOP
                c = next((x for x in range(i + 1, e) if self.at(x, "COMPARE_OP")
                          and self.ins[x].arg == _EXC_MATCH), None)
                if c is None or not (self.at(c + 1, "JUMP_IF_FALSE")
                                     and self.at(c + 2, "POP_TOP")
                                     and self.at(c + 3, "POP_TOP")):
                    self.fail("unrecognised except clause", i)
                typ = self.expr(i + 1, c)
                n = self.target(c + 1)
                p, name = c + 4, None
                if self.at(p, "POP_TOP"):
                    p += 1
                else:
                    node, p = self.capture(p, n)
                    if not isinstance(node, ast.Name):
                        self.fail("except target is not a name", p)
                    name = node.id
                if not (self.at(p, "POP_TOP") and self.at(n - 1, "JUMP_FORWARD")
                        and self.at(n, "POP_TOP")):
                    self.fail("unrecognised except clause", i)
                hbody = self.block(p + 1, n - 1)
                clause_end = self.target(n - 1)
                i = n + 1
            else:
                # bare except: POP_TOP x3; <body>; JUMP_FORWARD end; END_FINALLY
                if not (self.at(i, "POP_TOP") and self.at(i + 1, "POP_TOP")
                        and self.at(i + 2, "POP_TOP") and self.at(e - 2, "JUMP_FORWARD")):
                    self.fail("unrecognised except clause", i)
                typ, name = None, None
                hbody = self.block(i + 3, e - 2)
                clause_end = self.target(e - 2)
                i = e - 1
            if end is not None and clause_end != end:
                self.fail("except clauses end in different places", i - 1)
            end = clause_end
            handlers.append(_place(ast.ExceptHandler(typ, name, hbody), hline))
        if not handlers or i != e - 1 or end < e or end > j:
            self.fail("unrecognised try", k)
        orelse = self.block(e, end) if end > e else []
        self.lineno = line
        self.emit(ast.Try(body, handlers, orelse, []))
        return end

    def try_finally(self, k, j):
        # SETUP_FINALLY f; <body>; POP_BLOCK; LOAD_CONST None; f: <final>;
        # END_FINALLY
        f = self.target(k)
        if not (self.at(f - 1, "LOAD_CONST") and self.at(f - 2, "POP_BLOCK")):
            self.fail("unrecognised try/finally", k)
        depth, ef = 0, None
        for x in range(f, j):
            name = self.ins[x].name
            if name in ("SETUP_EXCEPT", "SETUP_FINALLY"):
                depth += 1
            elif name == "END_FINALLY":
                if depth == 0:
                    ef = x
                    break
                depth -= 1
        if ef is None:
            self.fail("unrecognised try/finally", k)
        line = self.ins[k].line
        body = self.block(k + 1, f - 2)
        final = self.block(f, ef)
        self.lineno = line
        self.emit(ast.Try(body, [], [], final))
        return ef + 1

    # -- one instruction (or one structure) ---------------------------------
    def step(self, k, j):
        ins = self.ins[k]
        name, arg = ins.name, ins.arg
        self.lineno = ins.line
        names, varnames = self.co.names, self.co.varnames
        if name == "LOAD_CONST":
            value = self.co.consts[arg]
            self.stack.append(_CodeRef(value) if isinstance(value, Code15)
                              else _const(value))
            if value is None:
                # Compiler-made None (a bare `return`), not the name None.
                self.stack[-1]._bare = True
        elif name in ("LOAD_NAME", "LOAD_GLOBAL", "LOAD_FAST"):
            ident = varnames[arg] if name == "LOAD_FAST" else names[arg]
            # 1.5 has no None constant: it is a name lookup.
            self.stack.append(ast.Constant(None) if ident == "None"
                              else ast.Name(ident, ast.Load()))
        elif name == "LOAD_ATTR":
            self.stack.append(ast.Attribute(self.pop_expr(k), names[arg],
                                            ast.Load()))
        elif name in ("STORE_NAME", "STORE_GLOBAL"):
            self.store_name(names[arg], name == "STORE_GLOBAL", k)
        elif name == "STORE_FAST":
            self.store_name(varnames[arg], False, k)
        elif name == "STORE_ATTR":
            obj = self.pop_expr(k)
            self.store_to(ast.Attribute(obj, names[arg], ast.Store()), k)
        elif name == "STORE_SUBSCR":
            key = self.pop_expr(k)
            obj = self.stack.pop() if self.stack else None
            if isinstance(obj, _DictDup):
                value = self.pop_expr(k)
                obj.target.keys.append(key)
                obj.target.values.append(value)
            elif isinstance(obj, ast.expr):
                self.store_to(ast.Subscript(obj, key, ast.Store()), k)
            else:
                self.fail("subscript store target", k)
        elif name == "BINARY_SUBSCR":
            key = self.pop_expr(k)
            obj = self.pop_expr(k)
            self.stack.append(ast.Subscript(obj, key, ast.Load()))
        elif name.startswith(("SLICE_", "STORE_SLICE_", "DELETE_SLICE_")):
            n = int(name[-1])
            upper = self.pop_expr(k) if n & 2 else None
            lower = self.pop_expr(k) if n & 1 else None
            obj = self.pop_expr(k)
            sl = ast.Slice(lower, upper, None)
            if name.startswith("SLICE_"):
                self.stack.append(ast.Subscript(obj, sl, ast.Load()))
            elif name.startswith("STORE_"):
                self.store_to(ast.Subscript(obj, sl, ast.Store()), k)
            else:
                self.emit(ast.Delete([ast.Subscript(obj, sl, ast.Del())]))
        elif name in _BINARY:
            right = self.pop_expr(k)
            left = self.pop_expr(k)
            self.stack.append(ast.BinOp(left, _BINARY[name](), right))
        elif name in _UNARY:
            self.stack.append(ast.UnaryOp(_UNARY[name](), self.pop_expr(k)))
        elif name == "UNARY_CONVERT":
            # Backticks; the source path rewrites them to repr().
            self.stack.append(ast.Call(ast.Name("repr", ast.Load()),
                                       [self.pop_expr(k)], []))
        elif name == "COMPARE_OP":
            if arg >= len(_COMPARE):
                self.fail("comparison %r" % op.COMPARE[min(arg, len(op.COMPARE) - 1)], k)
            right = self.pop_expr(k)
            left = self.pop_expr(k)
            self.stack.append(ast.Compare(left, [_COMPARE[arg]()], [right]))
        elif name == "CALL_FUNCTION":
            if arg == 0 and self.stack and isinstance(self.stack[-1], _Function):
                self.stack.append(_ClassBody(self.stack.pop().code))
                return k + 1
            keywords = []
            for _ in range(arg >> 8):
                value = self.pop_expr(k)
                key = self.pop_expr(k)
                keywords.insert(0, ast.keyword(key.value, value))
            positional = [self.pop_expr(k) for _ in range(arg & 0xFF)][::-1]
            func = self.pop_expr(k)
            # The source path's `.has_key(` -> `.__contains__(`.
            if isinstance(func, ast.Attribute) and func.attr == "has_key":
                func.attr = "__contains__"
            self.stack.append(ast.Call(func, positional, keywords))
        elif name in ("BUILD_TUPLE", "BUILD_LIST"):
            items = [self.pop_expr(k) for _ in range(arg)][::-1]
            node = ast.Tuple if name == "BUILD_TUPLE" else ast.List
            self.stack.append(node(items, ast.Load()))
        elif name == "BUILD_MAP":
            if arg:
                self.fail("BUILD_MAP with a size", k)
            self.stack.append(ast.Dict([], []))
        elif name == "BUILD_CLASS":
            body = self.stack.pop() if self.stack else None
            bases = self.pop_expr(k)
            cname = self.pop_expr(k)
            if not (isinstance(body, _ClassBody) and isinstance(bases, ast.Tuple)
                    and isinstance(cname, ast.Constant)
                    and isinstance(cname.value, str)):
                self.fail("unrecognised class", k)
            self.stack.append(_Class(cname.value, bases.elts, body.code))
        elif name == "DUP_TOP":
            top = self.stack[-1] if self.stack else None
            following = self.ins[k + 1].name if k + 1 < len(self.ins) else ""
            if isinstance(top, ast.Dict) and following not in _STORES \
                    and not following.startswith("UNPACK_"):
                self.stack.append(_DictDup(top))
            elif isinstance(top, _Slot) and isinstance(top.owner, _Assign):
                self.stack.append(top.owner.slot())      # a = b = c = v
            elif isinstance(top, ast.expr):
                assign = _Assign(self.stack.pop())       # a = b = v
                self.stack.append(assign.slot())
                self.stack.append(assign.slot())
            else:
                self.fail("DUP_TOP outside a dict literal or assignment", k)
        elif name == "ROT_TWO":
            if len(self.stack) < 2 or not isinstance(self.stack[-2], _DictDup):
                self.fail("ROT_TWO outside a dict literal", k)
            self.stack[-1], self.stack[-2] = self.stack[-2], self.stack[-1]
        elif name in ("UNPACK_TUPLE", "UNPACK_LIST"):
            if not self.stack:
                self.fail("stack underflow", k)
            value = self.stack.pop()
            if isinstance(value, ast.expr):
                assign = _Assign(value)
                value = assign.slot()
            elif not isinstance(value, _Slot):
                self.fail("unpacking a non-value", k)
            unpack = _Unpack(value, arg, name == "UNPACK_LIST")
            for index in reversed(range(arg)):
                self.stack.append(_Slot(unpack, index))
        elif name == "POP_TOP":
            value = self.stack.pop() if self.stack else None
            if isinstance(value, _Import) and value.froms:
                self.emit(ast.ImportFrom(value.name,
                                         [ast.alias(n, None) for n in value.froms], 0))
            else:
                self.stack.append(value)
                self.emit(ast.Expr(self.pop_expr(k)))
        elif name == "RETURN_VALUE":
            if not self.stack:
                self.fail("stack underflow", k)
            if isinstance(self.stack[-1], _Locals):
                if self.kind != "class" or k != len(self.ins) - 1:
                    self.fail("LOAD_LOCALS outside a class body end", k)
                self.stack.pop()
                return k + 1
            value = self.pop_expr(k)
            if self.kind in ("function", "lambda"):
                bare = getattr(value, "_bare", False)
                self.emit(ast.Return(None if bare else value))
            elif not (k == len(self.ins) - 1 and isinstance(value, ast.Constant)
                      and value.value is None):
                self.fail("module-level return", k)
        elif name == "LOAD_LOCALS":
            self.stack.append(_Locals())
        elif name == "IMPORT_NAME":
            self.stack.append(_Import(names[arg]))
        elif name == "IMPORT_FROM":
            top = self.stack[-1] if self.stack else None
            if not isinstance(top, _Import):
                self.fail("IMPORT_FROM without IMPORT_NAME", k)
            top.froms = (top.froms or []) + [names[arg]]
        elif name == "MAKE_FUNCTION":
            code = self.stack.pop() if self.stack else None
            if not isinstance(code, _CodeRef):
                self.fail("MAKE_FUNCTION without code", k)
            defaults = [self.pop_expr(k) for _ in range(arg)][::-1]
            func = _Function(code.code, defaults)
            self.stack.append(self.lambda_expr(func, k)
                              if code.code.name == "<lambda>" else func)
        elif name in ("DELETE_NAME", "DELETE_FAST", "DELETE_GLOBAL"):
            ident = varnames[arg] if name == "DELETE_FAST" else names[arg]
            if name == "DELETE_GLOBAL" and self.kind == "function" \
                    and ident not in self.globals:
                self.globals.append(ident)
            self.emit(ast.Delete([ast.Name(ident, ast.Del())]))
        elif name == "DELETE_ATTR":
            self.emit(ast.Delete([ast.Attribute(self.pop_expr(k), names[arg],
                                                ast.Del())]))
        elif name == "DELETE_SUBSCR":
            key = self.pop_expr(k)
            obj = self.pop_expr(k)
            self.emit(ast.Delete([ast.Subscript(obj, key, ast.Del())]))
        elif name == "RAISE_VARARGS":
            if arg == 0:
                self.emit(ast.Raise(None, None))
            elif arg == 1:
                self.emit(ast.Raise(self.pop_expr(k), None))
            elif arg == 2:
                # `raise X, v` -- the source path rewrites it to `raise X(v)`.
                value = self.pop_expr(k)
                exc = self.pop_expr(k)
                self.emit(ast.Raise(ast.Call(exc, [value], []), None))
            else:
                self.fail("raise with a traceback", k)
        elif name == "PRINT_ITEM":
            item = self.pop_expr(k)
            if self.print_items is not None and self.print_line != ins.line:
                self.flush_print()      # `print a,` on an earlier line
            if self.print_items is None:
                self.print_items = []
                self.print_line = ins.line
            # 1.5 writes earlier items before a later one is evaluated;
            # print(a, f()) evaluates f() first. The source path's print()
            # rewrite has the same difference, and this matches it.
            self.print_items.append(item)
        elif name == "PRINT_NEWLINE":
            items, self.print_items = self.print_items or [], None
            self.emit(ast.Expr(ast.Call(ast.Name("print", ast.Load()), items, [])))
        elif name in ("JUMP_IF_FALSE", "JUMP_IF_TRUE"):
            return self.conditional(k, j)
        elif name == "SETUP_LOOP":
            if self.stack:
                self.fail("loop with values pending on the stack", k)
            return self.loop(k, j)
        elif name == "SETUP_EXCEPT":
            if self.stack:
                self.fail("try with values pending on the stack", k)
            return self.try_except(k, j)
        elif name == "SETUP_FINALLY":
            if self.stack:
                self.fail("try with values pending on the stack", k)
            return self.try_finally(k, j)
        elif name == "BREAK_LOOP":
            if not self.loops:
                self.fail("break outside a loop", k)
            self.emit(ast.Break())
        elif name == "JUMP_ABSOLUTE":
            if not self.loops or self.target(k) != self.loops[-1]:
                self.fail("jump that is not a continue", k)
            self.emit(ast.Continue())
        else:
            self.fail("unsupported opcode", k)
        return k + 1

    def run(self):
        body = self.block(0, len(self.ins))
        if body and isinstance(body[0], ast.Pass) and len(body) == 1 \
                and self.kind != "function":
            body = body if self.kind == "class" else []
        if self.globals:
            at = 1 if (body and isinstance(body[0], ast.Expr)
                       and isinstance(body[0].value, ast.Constant)
                       and isinstance(body[0].value.value, str)) else 0
            body.insert(at, _place(ast.Global(self.globals),
                                   max(self.co.firstlineno, 1)))
        return body


def lift(data: bytes) -> ast.Module:
    """The Python 3 module AST for a Python 1.5 .pyc file's bytes."""
    try:
        code = load_pyc(data)
    except Py15FormatError as exc:
        raise Py15Unsupported("not a readable Python 1.5 .pyc: %s" % exc) from exc
    try:
        body = _Lifter(code, "module").run()
    except (IndexError, KeyError, AttributeError, TypeError, ValueError,
            RecursionError) as exc:
        # An operand index past its table, or a stack shape no real
        # compiler emits: corrupt or hand-made bytecode, not a new shape.
        raise Py15Unsupported("malformed bytecode: %s: %s"
                              % (type(exc).__name__, exc)) from exc
    tree = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(tree)
    return tree
