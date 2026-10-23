"""Turn straight-line Python 1.5 bytecode into a Python 3 ``ast.Module``.

The output is the tree the SDK loader would have built from the module's
source: ``ast.parse(_fix_py2_syntax(source))``. The loader then runs the same
compatibility transforms over it, so a ``.pyc`` loads exactly as its ``.py``
would.

Only a closed subset is accepted: code with no jump of any kind, no class, no
nested or variadic function, no ``from`` import. Every opcode or shape outside
it raises ``Py15Unsupported`` rather than guessing. The subset grows only when
stock modules exercise a new shape and the stock-corpus oracle test
(tests/unit/test_py15_stock_oracle.py) proves them identical to their SDK
source. Spec: docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md
"""
from __future__ import annotations

import ast
import sys

from . import opcodes15 as op
from .marshal15 import Code15, Py15FormatError, load_pyc


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


# Stack values that are not expressions. Consuming one as an expression is
# a shape outside the subset.
class _Import:
    def __init__(self, name):
        self.name = name


class _CodeRef:
    def __init__(self, code):
        self.code = code


class _Function:
    def __init__(self, code, defaults):
        self.code = code
        self.defaults = defaults


class _DictDup:
    """The DUP_TOP'd dict of a 1.5 dict literal: BUILD_MAP, then per pair
    DUP_TOP <value> ROT_TWO <key> STORE_SUBSCR."""

    def __init__(self, target):
        self.target = target


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


def _text(raw: bytes) -> str:
    # The SDK loader reads source as utf-8 with errors="replace"; raw high
    # bytes in a string constant come out the way the same bytes would from a
    # .py. Not exact for a source ESCAPE: "\xe9" parses to U+00E9 from source,
    # but the same byte here decodes to U+FFFD. One of the two cases has to
    # diverge; this one was chosen to match raw bytes.
    return raw.decode("utf-8", errors="replace")


def _const(value):
    if isinstance(value, bytes):
        return ast.Constant(_text(value))
    if isinstance(value, tuple):
        return ast.Tuple([_const(v) for v in value], ast.Load())
    if value is None or isinstance(value, (int, float, complex)) \
            or value is Ellipsis:
        return ast.Constant(value)
    raise Py15Unsupported("constant of type %s" % type(value).__name__)


def _place(node, lineno):
    """Give a statement a one-line source span; fix_missing_locations then
    copies it onto every expression inside."""
    node.lineno = node.end_lineno = lineno
    node.col_offset = node.end_col_offset = 0
    return node


class _Lifter:
    def __init__(self, code: Code15, in_function: bool):
        self.co = code
        self.in_function = in_function
        self.stack = []
        self.body = []
        self.globals = []
        self.print_items = None
        self.lineno = code.firstlineno or 1

    # -- helpers ---------------------------------------------------------
    def emit(self, stmt):
        if self.print_items is not None:
            raise Py15Unsupported("statement inside a print statement")
        if self.stack:
            # Values still pending would be evaluated AFTER this statement
            # once lifted (f() g() POP POP runs f first in 1.5, g first here).
            raise Py15Unsupported("statement with values pending on the stack")
        span_end = getattr(stmt, "end_lineno", None)   # a def computed its own
        _place(stmt, self.lineno)
        if span_end is not None:
            stmt.end_lineno = max(span_end, self.lineno)
        self.body.append(stmt)

    def pop_expr(self, opcode, offset):
        if not self.stack:
            raise Py15Unsupported("stack underflow", opcode, offset)
        value = self.stack.pop()
        if not isinstance(value, ast.expr):
            raise Py15Unsupported("%s used as a value" % type(value).__name__,
                                  opcode, offset)
        return value

    def store(self, name, is_global, opcode, offset):
        value = self.stack.pop()
        if is_global and isinstance(value, (_Import, _Function)):
            # `global X; import X` would lift as a plain import, which binds
            # X locally; the global declaration cannot be kept in this shape.
            raise Py15Unsupported("global import or def", opcode, offset)
        if isinstance(value, _Import):
            if value.name.split(".")[0] != name:
                raise Py15Unsupported("import alias", opcode, offset)
            self.emit(ast.Import([ast.alias(value.name, None)]))
            return
        if isinstance(value, _Function):
            self.emit(self.function_def(name, value, opcode, offset))
            return
        if not isinstance(value, ast.expr):
            raise Py15Unsupported("%s stored" % type(value).__name__,
                                  opcode, offset)
        if (not self.in_function and name == "__doc__" and not self.body
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)):
            self.emit(ast.Expr(value))           # the module docstring
            return
        if is_global and self.in_function and name not in self.globals:
            self.globals.append(name)
        self.emit(ast.Assign([ast.Name(name, ast.Store())], value))

    def function_def(self, name, func, opcode, offset):
        co = func.code
        if self.in_function:
            raise Py15Unsupported("nested function", opcode, offset)
        if co.name != name:
            raise Py15Unsupported("function %r stored as %r (lambda?)"
                                  % (co.name, name), opcode, offset)
        if co.flags & (op.CO_VARARGS | op.CO_VARKEYWORDS):
            raise Py15Unsupported("*args/**kwargs parameters", opcode, offset)
        params = list(co.varnames[:co.argcount])
        if not all(p.isidentifier() for p in params):
            raise Py15Unsupported("tuple parameters", opcode, offset)
        body = _Lifter(co, in_function=True).run()
        while (body and isinstance(body[-1], ast.Return)
               and isinstance(body[-1].value, ast.Constant)
               and body[-1].value.value is None):
            body.pop()
        # 1.5 always reserves co_consts[0] for the docstring (None if absent).
        if co.consts and isinstance(co.consts[0], bytes):
            body.insert(0, _place(ast.Expr(ast.Constant(_text(co.consts[0]))),
                                  co.firstlineno))
        if not body:
            body = [_place(ast.Pass(), co.firstlineno)]
        args = ast.arguments(posonlyargs=[], args=[ast.arg(p) for p in params],
                             vararg=None, kwonlyargs=[], kw_defaults=[],
                             kwarg=None, defaults=func.defaults)
        # type_params is a 3.12 field (PEP 695). Omitting it leaves the node
        # structurally different from one ast.parse() produces on 3.12 -- the
        # two unparse identically, so the only thing that notices is an
        # ast.dump() comparison, which is exactly what the lifter's tests do.
        # Nothing in 1.5 bytecode can carry type parameters, so it is always
        # empty; passing it keeps a lifted tree indistinguishable from a
        # parsed one. Guarded rather than assumed, so a 3.11 interpreter --
        # which rejects the keyword -- still works.
        extra = {"type_params": []} if sys.version_info >= (3, 12) else {}
        node = ast.FunctionDef(name=name, args=args, body=body,
                               decorator_list=[], returns=None,
                               type_comment=None, **extra)
        _place(node, co.firstlineno)
        node.end_lineno = max(co.firstlineno, max(s.end_lineno for s in body))
        return node

    # -- the walk --------------------------------------------------------
    def run(self):
        instrs = list(_instructions(self.co.code))
        names, varnames = self.co.names, self.co.varnames
        for index, (offset, name, arg) in enumerate(instrs):
            if name == "SET_LINENO":
                self.lineno = arg
            elif name == "LOAD_CONST":
                value = self.co.consts[arg]
                self.stack.append(_CodeRef(value) if isinstance(value, Code15)
                                  else _const(value))
            elif name in ("LOAD_NAME", "LOAD_GLOBAL", "LOAD_FAST"):
                ident = varnames[arg] if name == "LOAD_FAST" else names[arg]
                # 1.5 has no None constant: it is a name lookup.
                self.stack.append(ast.Constant(None) if ident == "None"
                                  else ast.Name(ident, ast.Load()))
            elif name == "LOAD_ATTR":
                self.stack.append(ast.Attribute(self.pop_expr(name, offset),
                                                names[arg], ast.Load()))
            elif name in ("STORE_NAME", "STORE_GLOBAL"):
                self.store(names[arg], name == "STORE_GLOBAL", name, offset)
            elif name == "STORE_FAST":
                self.store(varnames[arg], False, name, offset)
            elif name == "STORE_ATTR":
                obj = self.pop_expr(name, offset)
                value = self.pop_expr(name, offset)
                self.emit(ast.Assign(
                    [ast.Attribute(obj, names[arg], ast.Store())], value))
            elif name == "STORE_SUBSCR":
                key = self.pop_expr(name, offset)
                obj = self.stack.pop() if self.stack else None
                value = self.pop_expr(name, offset)
                if isinstance(obj, _DictDup):
                    obj.target.keys.append(key)
                    obj.target.values.append(value)
                elif isinstance(obj, ast.expr):
                    self.emit(ast.Assign(
                        [ast.Subscript(obj, key, ast.Store())], value))
                else:
                    raise Py15Unsupported("subscript store target", name, offset)
            elif name == "BINARY_SUBSCR":
                key = self.pop_expr(name, offset)
                obj = self.pop_expr(name, offset)
                self.stack.append(ast.Subscript(obj, key, ast.Load()))
            elif name in _BINARY:
                right = self.pop_expr(name, offset)
                left = self.pop_expr(name, offset)
                self.stack.append(ast.BinOp(left, _BINARY[name](), right))
            elif name in _UNARY:
                self.stack.append(ast.UnaryOp(_UNARY[name](),
                                              self.pop_expr(name, offset)))
            elif name == "COMPARE_OP":
                if arg >= len(_COMPARE):
                    raise Py15Unsupported("comparison %r" % op.COMPARE[arg],
                                          name, offset)
                right = self.pop_expr(name, offset)
                left = self.pop_expr(name, offset)
                self.stack.append(ast.Compare(left, [_COMPARE[arg]()], [right]))
            elif name == "CALL_FUNCTION":
                keywords = []
                for _ in range(arg >> 8):
                    value = self.pop_expr(name, offset)
                    key = self.pop_expr(name, offset)
                    keywords.insert(0, ast.keyword(key.value, value))
                positional = [self.pop_expr(name, offset)
                              for _ in range(arg & 0xFF)][::-1]
                func = self.pop_expr(name, offset)
                # _fix_py2_syntax's `.has_key(` -> `.__contains__(`.
                if isinstance(func, ast.Attribute) and func.attr == "has_key":
                    func.attr = "__contains__"
                self.stack.append(ast.Call(func, positional, keywords))
            elif name in ("BUILD_TUPLE", "BUILD_LIST"):
                items = [self.pop_expr(name, offset) for _ in range(arg)][::-1]
                node = ast.Tuple if name == "BUILD_TUPLE" else ast.List
                self.stack.append(node(items, ast.Load()))
            elif name == "BUILD_MAP":
                if arg:
                    raise Py15Unsupported("BUILD_MAP with a size", name, offset)
                self.stack.append(ast.Dict([], []))
            elif name == "DUP_TOP":
                following = instrs[index + 1][1] if index + 1 < len(instrs) else ""
                if not (self.stack and isinstance(self.stack[-1], ast.Dict)
                        and not following.startswith("STORE_")):
                    raise Py15Unsupported("DUP_TOP outside a dict literal",
                                          name, offset)
                self.stack.append(_DictDup(self.stack[-1]))
            elif name == "ROT_TWO":
                if len(self.stack) < 2 or not isinstance(self.stack[-2], _DictDup):
                    raise Py15Unsupported("ROT_TWO outside a dict literal",
                                          name, offset)
                self.stack[-1], self.stack[-2] = self.stack[-2], self.stack[-1]
            elif name == "POP_TOP":
                self.emit(ast.Expr(self.pop_expr(name, offset)))
            elif name == "RETURN_VALUE":
                value = self.pop_expr(name, offset)
                if self.in_function:
                    self.emit(ast.Return(value))
                elif not (index == len(instrs) - 1
                          and isinstance(value, ast.Constant)
                          and value.value is None):
                    raise Py15Unsupported("module-level return", name, offset)
            elif name == "IMPORT_NAME":
                self.stack.append(_Import(names[arg]))
            elif name == "MAKE_FUNCTION":
                code = self.stack.pop() if self.stack else None
                if not isinstance(code, _CodeRef):
                    raise Py15Unsupported("MAKE_FUNCTION without code", name, offset)
                defaults = [self.pop_expr(name, offset) for _ in range(arg)][::-1]
                self.stack.append(_Function(code.code, defaults))
            elif name == "PRINT_ITEM":
                item = self.pop_expr(name, offset)
                if self.print_items is None:
                    self.print_items = []
                elif not isinstance(item, (ast.Constant, ast.Name)):
                    # 1.5 writes the earlier items before this one runs.
                    raise Py15Unsupported("print item evaluated after output began",
                                          name, offset)
                self.print_items.append(item)
            elif name == "PRINT_NEWLINE":
                items, self.print_items = self.print_items or [], None
                self.emit(ast.Expr(ast.Call(ast.Name("print", ast.Load()),
                                            items, [])))
            else:
                raise Py15Unsupported("unsupported opcode", name, offset)
        if self.stack:
            raise Py15Unsupported("values left on the stack")
        if self.print_items is not None:
            raise Py15Unsupported("print statement with a trailing comma")
        if self.globals:
            at = 1 if (self.body and isinstance(self.body[0], ast.Expr)
                       and isinstance(self.body[0].value, ast.Constant)) else 0
            self.body.insert(at, _place(ast.Global(self.globals),
                                        self.co.firstlineno))
        return self.body


def lift(data: bytes) -> ast.Module:
    """The Python 3 module AST for a Python 1.5 .pyc file's bytes."""
    try:
        code = load_pyc(data)
    except Py15FormatError as exc:
        raise Py15Unsupported("not a readable Python 1.5 .pyc: %s" % exc) from exc
    try:
        body = _Lifter(code, in_function=False).run()
    except (IndexError, KeyError, AttributeError, TypeError, ValueError,
            RecursionError) as exc:
        # An operand index past its table, or a stack shape no real
        # compiler emits: corrupt or hand-made bytecode, not a new shape.
        raise Py15Unsupported("malformed bytecode: %s: %s"
                              % (type(exc).__name__, exc)) from exc
    tree = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(tree)
    return tree
