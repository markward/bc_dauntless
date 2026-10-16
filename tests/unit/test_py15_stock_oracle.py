"""The lifter is right on every stock module it accepts.

Retail BC ships all its game scripts as Python 1.5 .pyc only (1201 on the
GOG install), and the SDK ships each one's .py. For every stock .pyc that
engine.py15 accepts, the lifted AST must equal what the SDK loader parses
from the .py -- ast.parse(_fix_py2_syntax(source)) -- after this CLOSED
normalisation, each item being something 1.5 bytecode cannot carry:

  * `pass` statements;
  * bare string statements other than a docstring (compiled away);
  * a function's trailing `return` / `return None` (the implicit return);
  * `global` names a function never assigns (no bytecode trace); the
    remaining names merge into one sorted declaration after the docstring.

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
from tools.mission_harness import _fix_py2_syntax

ACCEPTED_FLOOR = 514


def _is_doc(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str))


def _norm_body(body, is_function):
    body = [s for s in body if not isinstance(s, ast.Pass)]
    doc = []
    if body and _is_doc(body[0]):
        doc, body = [body[0]], body[1:]
    body = [s for s in body if not _is_doc(s)]
    if is_function:
        while body and isinstance(body[-1], ast.Return) and (
                body[-1].value is None
                or (isinstance(body[-1].value, ast.Constant)
                    and body[-1].value.value is None)):
            body.pop()
    return doc + body


def _normalise(tree):
    tree.body = _norm_body(tree.body, False)
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        stored = {n.id for n in ast.walk(fn)
                  if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        declared = sorted({g for n in ast.walk(fn) if isinstance(n, ast.Global)
                           for g in n.names} & stored)
        body = _norm_body([s for s in fn.body if not isinstance(s, ast.Global)],
                          True)
        if declared:
            body.insert(1 if body and _is_doc(body[0]) else 0,
                        ast.Global(declared))
        fn.body = body or [ast.Pass()]
    return ast.dump(tree)


def _sdk_tree(path):
    # Exactly what the SDK loader does to a .py before its AST transforms.
    source = path.read_text(encoding="utf-8", errors="replace").expandtabs(4)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(_fix_py2_syntax(source), filename=str(path))


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
