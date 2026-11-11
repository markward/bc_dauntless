"""The lifter is right on every stock module it accepts.

Retail BC ships all its game scripts as Python 1.5 .pyc only (1201 on the
GOG install), and the SDK ships each one's .py. For every stock .pyc that
engine.py15 accepts, the lifted AST must equal what the SDK loader parses
from the .py -- ast.parse(fix_source(source)) -- after this CLOSED
normalisation, each item being something 1.5 bytecode cannot carry:

  * `pass` statements;
  * bare string statements other than a docstring (compiled away);
  * a function's trailing `return` / `return None` (the implicit return);
  * `global` names a function never assigns (no bytecode trace); the
    remaining names merge into one sorted declaration after the docstring,
    wherever in the function the source put them (bytecode records no
    position, and the SDK loader's _MoveGlobalsToTop hoists them anyway);
  * a `BoolOp` as the LAST operand of the same operator is flattened:
    `a and (b and c)` compiles to the very bytecode `a and b and c` does;
  * a module- or class-level `global` (compiles to nothing);
  * float constants compare at 12 significant digits: 1.5's marshal writes a
    float as "%.12g" text, so the .pyc holds the value BC actually ran with
    and the SDK source may carry more digits than that.

Each item applies wherever it occurs, at any depth.

_SOURCE_DIFFERS lists stock modules whose retail .pyc was compiled from a
DIFFERENT version of the file than the SDK ships, each with the evidence.
They must still lift; only the comparison is skipped.

Never widen that list to make a mismatch go away: a mismatch is a lifter bug
until proven otherwise.

The floor is a ratchet. Raise ACCEPTED_FLOOR when the subset grows (the
subset only grows when this test proves the new shape); never lower it.
Spec: docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md §7 T2.
"""
import ast
import warnings

import pytest

from engine import paths, py15
from tests.helpers.bc_assets import require_game_dir
from engine.py15.source import fix_source, read_source

ACCEPTED_FLOOR = 1201

_SOURCE_DIFFERS = {
    # The .pyc reads two fields per record (frame, value) where the .py
    # reads four, and lacks the .py's "Show Call Graph" button and its
    # FrameChanged sorting: an older TimingGraph.py. A developer tool.
    "TimingGraph.py": "retail .pyc predates the SDK source",
}


def _is_doc(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str))


_DOC_OWNERS = (ast.Module, ast.FunctionDef, ast.ClassDef)


class _FlattenBoolOps(ast.NodeTransformer):
    def visit_BoolOp(self, node):
        self.generic_visit(node)
        last = node.values[-1]
        if isinstance(last, ast.BoolOp) and type(last.op) is type(node.op):
            node.values[-1:] = last.values
        return node


class _StripBlocks(ast.NodeTransformer):
    """`pass` and non-docstring bare strings, in every block at any depth.
    A body left empty gets one `pass` back; an else/finally left empty goes."""

    def generic_visit(self, node):
        super().generic_visit(node)
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            keep_doc = (field == "body" and isinstance(node, _DOC_OWNERS)
                        and block and _is_doc(block[0]))
            kept = [stmt for i, stmt in enumerate(block)
                    if not isinstance(stmt, ast.Pass)
                    and not (_is_doc(stmt) and not (keep_doc and i == 0))]
            if not kept and field == "body" and not isinstance(node, ast.Module):
                kept = [ast.Pass()]
            setattr(node, field, kept)
        return node


class _RoundFloats(ast.NodeTransformer):
    def visit_Constant(self, node):
        if isinstance(node.value, float):
            node.value = float("%.12g" % node.value)
        return node


class _DropAllGlobals(ast.NodeTransformer):
    def visit_Global(self, node):
        return None


class _DropGlobals(ast.NodeTransformer):
    """Remove `global` statements at any depth inside one function (its
    nested functions keep theirs)."""

    def __init__(self, fn):
        self.fn = fn

    def visit_FunctionDef(self, node):
        return self.generic_visit(node) if node is self.fn else node

    def visit_Global(self, node):
        return None


def _normalise(tree):
    tree = _FlattenBoolOps().visit(tree)
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        inner = {n for f in ast.walk(fn) if isinstance(f, ast.FunctionDef)
                 and f is not fn for n in ast.walk(f)}
        own = [n for n in ast.walk(fn) if n not in inner]
        stored = {n.id for n in own
                  if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        declared = sorted({g for n in own if isinstance(n, ast.Global)
                           for g in n.names} & stored)
        _DropGlobals(fn).visit(fn)
        fn.body = fn.body or [ast.Pass()]
        fn._declared = declared
    tree = _DropAllGlobals().visit(tree)      # module- and class-level ones
    tree = _RoundFloats().visit(tree)
    tree = _StripBlocks().visit(tree)
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        body = [s for s in fn.body if not isinstance(s, ast.Pass)]
        while body and isinstance(body[-1], ast.Return) and (
                body[-1].value is None
                or (isinstance(body[-1].value, ast.Constant)
                    and body[-1].value.value is None)):
            body.pop()
        if fn._declared:
            body.insert(1 if body and _is_doc(body[0]) else 0,
                        ast.Global(fn._declared))
        fn.body = body or [ast.Pass()]
    return ast.dump(tree)


def _sdk_tree(path):
    # Exactly what the SDK loader does to a .py before its AST transforms.
    source = read_source(path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(fix_source(source), filename=str(path))


@pytest.fixture(scope="module")
def oracle():
    game_scripts = require_game_dir("scripts")
    sdk = paths.sdk_scripts()
    accepted, wrong = [], []
    for pyc in sorted(game_scripts.rglob("*.pyc")):
        rel = pyc.relative_to(game_scripts).with_suffix(".py")
        if not (sdk / rel).is_file():
            continue
        try:
            lifted = py15.lift_file(pyc)
        except py15.Py15Unsupported:
            continue
        compile(lifted, str(pyc), "exec")
        accepted.append(rel.as_posix())
        if rel.as_posix() in _SOURCE_DIFFERS:
            continue
        if _normalise(lifted) != _normalise(_sdk_tree(sdk / rel)):
            wrong.append(rel.as_posix())
    return game_scripts, accepted, wrong


def test_no_accepted_stock_module_differs_from_its_source(oracle):
    _, _, wrong = oracle
    assert wrong == []


def test_the_accepted_count_never_drops_below_the_floor(oracle):
    _, accepted, _ = oracle
    assert len(accepted) >= ACCEPTED_FLOOR, (
        "the lifter accepts %d stock modules, below the %d floor"
        % (len(accepted), ACCEPTED_FLOOR))


def test_every_stock_projectile_is_accepted(oracle):
    game_scripts, accepted, _ = oracle
    projectiles = sorted(
        p.relative_to(game_scripts).with_suffix(".py").as_posix()
        for p in (game_scripts / "Tactical" / "Projectiles").glob("*.pyc"))
    assert projectiles, "no stock projectiles found"
    assert set(projectiles) <= set(accepted)


def test_the_normalisation_still_sees_real_differences():
    """Guard against a vacuous pass: a normaliser that flattened everything
    would make the oracle agree with anything."""
    def norm(src):
        return _normalise(ast.parse(src))

    assert norm("x = 1") != norm("x = 2")
    assert norm("def f():\n    return 0") != norm("def f():\n    return 1")
    # A `global` that IS assigned survives normalisation...
    assert norm("def f():\n    global g\n    g = 1") != norm("def f():\n    g = 1")
    # ...one that is only read does not.
    assert norm("def f():\n    global g\n    return g") == norm("def f():\n    return g")
