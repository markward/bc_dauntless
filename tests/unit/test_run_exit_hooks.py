"""run() must not leave the weapons-panel hook installed: it closes over the
HUD registry (and through it the controller and the whole session)."""
import ast
import inspect

from engine import host_loop
from engine.appc import weapon_config


def _finally_source(fn) -> str:
    tree = ast.parse(inspect.getsource(fn))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for stmt in node.finalbody:
                out.append(ast.unparse(stmt))
    return "\n".join(out)


def test_run_finally_clears_weapon_config_hook():
    assert "weapon_config.on_change = None" in _finally_source(host_loop.run)


def test_per_test_reset_leaves_weapon_config_hook_none():
    # The autouse reset in tests/conftest.py ran before this test body.
    weapon_config.on_change = lambda: None
    from tests import conftest  # noqa: F401
    src = inspect.getsource(conftest)
    assert "weapon_config.on_change = None" in src
