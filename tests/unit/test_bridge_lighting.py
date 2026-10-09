import pytest
from engine import bridge_lighting as bl


@pytest.mark.parametrize("level,scale", [(0, 1.5), (1, 1.0), (2, 1.0), (3, 1.0), (-1, 1.0)])
def test_ambient_scale_for_alert(level, scale):
    assert bl.ambient_scale_for_alert(level) == scale


def test_no_player_is_authored_ambient():            # Review Focus #5
    assert bl.player_bridge_ambient_scale(None) == 1.0


def test_alert_probe_raising_is_authored_ambient():  # Review Focus #5
    class Broken:
        def GetAlertLevel(self): raise RuntimeError("mid swap")
    assert bl.player_bridge_ambient_scale(Broken()) == 1.0


def test_green_player():
    class P:
        def GetAlertLevel(self): return 0
    assert bl.player_bridge_ambient_scale(P()) == 1.5


def test_host_loop_uses_the_module():
    import inspect, engine.host_loop as hl
    src = inspect.getsource(hl)
    assert "player_bridge_ambient_scale(" in src
    assert "_bridge_dim = 0.5" not in src


def test_probe_blend_starts_at_its_target_and_fades():
    b = bl.ProbeBlend(fade_s=0.5)
    assert b.update(0, 0.016) == 0.0
    assert b.update(2, 0.25) == pytest.approx(0.5)
    assert b.update(2, 0.5) == 1.0
    assert b.update(1, 1.0) == 1.0          # yellow and red share a probe


def test_probe_blend_first_call_has_no_fade():
    assert bl.ProbeBlend().update(2, 0.016) == 1.0


def test_probe_blend_holds_with_zero_dt():
    b = bl.ProbeBlend()
    b.update(0, 0.0)
    assert b.update(2, 0.0) == 0.0


def test_probe_scales_are_the_green_and_yellow_ambient():
    assert bl.probe_scales() == (bl.ambient_scale_for_alert(0), bl.ambient_scale_for_alert(1))


# ── Review fix round 1, item 1 (second bullet): a structural check that the
# per-frame block in host_loop.run() feeds ProbeBlend.update(level, dt) into
# set_bridge_probe_mix, and calls bridge_runtime.on_alert(...) only inside an
# `if` gated on a level-changed comparison -- never unconditionally every
# frame. A full behavioural test would need a live renderer/CEF/mission
# loop (host_loop.run() itself), so this inspects run()'s AST instead of
# grepping strings, which a pure source-inspection check could satisfy by
# accident (e.g. the call present but never reached, or reached every
# frame regardless of level).
#
# Round 2: round 1's test only checked update()'s arg COUNT, not its
# identity -- a reviewer swapped the dt argument for TICK_DT (the
# non-paused clock, which silently breaks "frozen under pause") and the
# test stayed green. Now the second argument is pinned to the Name
# `_player_dt`. The on_alert guard check is also less brittle: instead of
# string-matching the literal name `_bridge_probe_alert_last` in the `If`'s
# dumped AST, it checks structurally that the `If`'s test is a `Compare`
# with a `NotEq` op that mentions the SAME level variable passed to
# `ProbeBlend.update` -- tied to the real data dependency, not a name that
# happens to appear in the source. ──

def test_host_loop_feeds_probe_blend_and_gates_on_alert_on_change():
    import ast
    import inspect

    import engine.host_loop as hl

    tree = ast.parse(inspect.getsource(hl))
    run_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "run")

    update_call = None
    mix_call = None
    on_alert_calls_with_guard = []

    def _is_guard(test, level_name):
        if level_name is None or not isinstance(test, ast.Compare):
            return False
        if not any(isinstance(op, ast.NotEq) for op in test.ops):
            return False
        return any(isinstance(n, ast.Name) and n.id == level_name
                   for n in ast.walk(test))

    class Visitor(ast.NodeVisitor):
        def visit_If(self, node):
            level_name = (update_call.args[0].id
                          if update_call is not None and isinstance(update_call.args[0], ast.Name)
                          else None)
            guarded = _is_guard(node.test, level_name)
            for stmt in ast.walk(node):
                if (isinstance(stmt, ast.Call)
                        and isinstance(stmt.func, ast.Attribute)
                        and stmt.func.attr == "on_alert"):
                    on_alert_calls_with_guard.append(guarded)
            self.generic_visit(node)

        def visit_Call(self, node):
            nonlocal update_call, mix_call
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "update"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "_bridge_probe_blend"):
                update_call = node
            if isinstance(node.func, ast.Attribute) and node.func.attr == "set_bridge_probe_mix":
                mix_call = node
            self.generic_visit(node)

    Visitor().visit(run_fn)

    assert update_call is not None, "no _bridge_probe_blend.update(level, dt) call found"
    assert len(update_call.args) == 2
    dt_arg = update_call.args[1]
    assert isinstance(dt_arg, ast.Name) and dt_arg.id == "_player_dt", (
        "ProbeBlend.update's second argument must be the Name _player_dt "
        "(the paused-aware dt) -- TICK_DT or any other clock breaks "
        f"'frozen under pause'; got {ast.dump(dt_arg)!r}")

    assert mix_call is not None, "no host_io.set_bridge_probe_mix(...) call found"
    # The mix call's sole argument must BE the update call (fed straight
    # through), not a separately-computed value.
    assert len(mix_call.args) == 1 and mix_call.args[0] is update_call

    assert on_alert_calls_with_guard, "on_alert(...) is never called from run()"
    assert all(on_alert_calls_with_guard), (
        "every on_alert(...) call must be inside an `if <level> != "
        "<something>:` guard comparing the SAME level variable fed to "
        "ProbeBlend.update, never unconditional")
