"""The run loop must drive the viewscreen bars from the selected source.

drive_viewscreen_bars is called after _select_viewscreen_source, with the
target only when the source is "scene" -- a comm or off feed gets None, so
no bars are drawn over a hail.
"""
import ast
import inspect
import textwrap

import engine.host_loop as host_loop


def _run_tree():
    return ast.parse(textwrap.dedent(inspect.getsource(host_loop.run)))


def _calls(tree, name):
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == name]


def test_drive_called_after_select_with_scene_gated_target():
    tree = _run_tree()
    drives = _calls(tree, "drive_viewscreen_bars")
    assert len(drives) == 1
    drive = drives[0]

    selects = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
               and isinstance(n.value, ast.Call)
               and isinstance(n.value.func, ast.Name)
               and n.value.func.id == "_select_viewscreen_source"]
    assert len(selects) == 1
    assert [t.id for t in selects[0].targets] == ["_vs_src"]
    assert selects[0].lineno < drive.lineno

    assert len(drive.args) == 3
    target = drive.args[2]
    assert isinstance(target, ast.IfExp)
    cond = target.test
    assert isinstance(cond, ast.Compare) and isinstance(cond.ops[0], ast.Eq)
    assert isinstance(cond.left, ast.Name) and cond.left.id == "_vs_src"
    assert isinstance(cond.comparators[0], ast.Constant)
    assert cond.comparators[0].value == "scene"
    assert isinstance(target.body, ast.Call)
    assert target.body.func.id == "_viewscreen_feed_target"
    assert isinstance(target.orelse, ast.Constant) and target.orelse.value is None
