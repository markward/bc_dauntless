"""_SDKFinder.find_spec exists TWICE, and the two copies must not diverge.

tests/conftest.py owns the copy the pytest suite imports through;
tools/mission_harness.py owns the copy the game imports through
(engine/host_loop._setup_sdk() calls its setup_sdk()). Every resolution rule
-- project-root shims first, then mod overrides, then stock, then the two
Python-1.5 fallbacks -- has to hold in both, or a mod resolves one way under
test and another way in the game. That is the worst failure shape available
to this feature: green tests, wrong game.

The two copies differ only in how they spell the project root:

    tests/conftest.py         tools/mission_harness.py
    PROJECT_ROOT              _PROJECT_ROOT

The stock scripts root is NOT an alias: both find_spec bodies open with the
same `stock_scripts = _stock.root()`, resolved at use, and that line is
compared like every other. (conftest used to capture it as a module-level
STOCK_SCRIPTS, which silently ignored a root a test injected.)

Both load stock modules lifted from the install through engine.stock_scripts
(spec 2026-11-11-no-sdk-runtime §4.2). The test loader's one extra -- the
SDK's Custom/Tutorial sample served as a fixture (decision 8) -- is a
registration in engine.stock_scripts made by tests/conftest.py at import,
NOT a difference in the finder code: the bodies compared here stay equal.

Comparison is on the parsed AST after normalising exactly those names, so
comments, docstrings and line wrapping stay free to differ (they do) while
any change to the actual logic is caught.
"""
import ast
import inspect
import sys
import textwrap
from pathlib import Path

import pytest

import tools.mission_harness as harness

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The per-file naming differences, and nothing else. Note "_PROJECT_ROOT"
# contains "PROJECT_ROOT", so this must be an exact-name mapping, never a
# substring replacement over source text.
_NAME_ALIASES = {
    "_PROJECT_ROOT": "PROJECT_ROOT",
}


class _NormaliseNames(ast.NodeTransformer):
    def visit_Name(self, node):
        node.id = _NAME_ALIASES.get(node.id, node.id)
        return node


def _conftest_module():
    """The ALREADY-IMPORTED tests/conftest.py.

    Found by __file__ rather than re-imported: executing conftest a second
    time under a different module name would give the suite a second set of
    module-level objects."""
    target = str(PROJECT_ROOT / "tests" / "conftest.py")
    for mod in list(sys.modules.values()):
        if getattr(mod, "__file__", None) == target:
            return mod
    raise AssertionError(f"tests/conftest.py is not in sys.modules as {target}")


def _strip_docstring(body):
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        return body[1:]
    return body


def _normalised_body(func_or_method):
    """A function's body as a normalised AST dump, docstring dropped."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(func_or_method)))
    body = _strip_docstring(tree.body[0].body)
    return "\n".join(ast.dump(_NormaliseNames().visit(stmt)) for stmt in body)


def test_the_two_sdk_finder_find_spec_bodies_are_identical():
    a = _normalised_body(_conftest_module()._SDKFinder.find_spec)
    b = _normalised_body(harness._SDKFinder.find_spec)
    assert a == b, (
        "tests/conftest.py and tools/mission_harness.py _SDKFinder.find_spec "
        "have diverged. Both copies must be edited identically -- one is what "
        "the test suite resolves through, the other is what the game does."
    )


@pytest.mark.parametrize("helper", ["_mods_may_override", "_mod_override_spec",
                                    "_module_tree", "_stock_dotted_name",
                                    "_implicit_relative_fixer"])
def test_the_shared_mod_helpers_are_identical_too(helper):
    """find_spec delegates to these, so drift here is drift there.

    _stock_dotted_name and _implicit_relative_fixer used to be exempt: they
    read the SDK root (a constant in one file, a call in the other). They
    now ask engine.stock_scripts instead, so they are compared too."""
    a = _normalised_body(getattr(_conftest_module(), helper))
    b = _normalised_body(getattr(harness, helper))
    assert a == b, f"{helper} has diverged between the two _SDKFinder copies"


@pytest.mark.parametrize("name", ["_FixImplicitRelativeImport",
                                  "_EmptyPackageLoader"])
def test_the_shared_loader_classes_are_identical(name):
    """The sibling rule and the synthetic-package loader, method by method."""
    def methods(cls):
        return {k: _normalised_body(v) for k, v in vars(cls).items()
                if inspect.isfunction(v)}
    a = methods(getattr(_conftest_module(), name))
    b = methods(getattr(harness, name))
    assert a == b, f"{name} has diverged between the two _SDKFinder copies"


def test_the_comparison_would_actually_notice_a_divergence():
    """A guard against a vacuous pass.

    If the normaliser flattened everything, the assertions above would hold
    forever no matter what the two files said."""
    def _dump(src):
        tree = ast.parse(textwrap.dedent(src))
        return "\n".join(ast.dump(_NormaliseNames().visit(s))
                         for s in _strip_docstring(tree.body[0].body))

    # A real logic difference is visible...
    assert _dump("def f(self, n):\n    return stock_scripts / n\n") != \
        _dump("def f(self, n):\n    return stock_scripts / n.lower()\n")
    # ...a stock root captured at import is not the one read at use...
    assert _dump("def f(self):\n    return STOCK_SCRIPTS\n") != \
        _dump("def f(self):\n    return stock_scripts\n")
    # ...and the two spellings of the project root are the same.
    assert _dump("def f(self):\n    return _PROJECT_ROOT\n") == \
        _dump("def f(self):\n    return PROJECT_ROOT\n")
