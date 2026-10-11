import pytest
from engine import bridge_lighting as bl


@pytest.mark.parametrize("level,scale", [(0, 1.5), (1, 1.0), (2, 1.0), (3, 0.4), (4, 1.0), (9, 1.0), (-1, 1.0)])
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
    # Spec §12.2: the dt is `_bridge_dt`, which _bridge_clock_dt derives from
    # the paused-aware `_player_dt` -- the Bridge Editor's preview clock
    # replaces it ONLY while the editor is open. Pin both links, so swapping
    # in TICK_DT (or wall time) for production still fails.
    assert isinstance(dt_arg, ast.Name) and dt_arg.id == "_bridge_dt", (
        "ProbeBlend.update's second argument must be the Name _bridge_dt "
        f"(the bridge clock dt); got {ast.dump(dt_arg)!r}")
    clock_calls = [
        n for n in ast.walk(run_fn)
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_bridge_dt" for t in n.targets)
        and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "_bridge_clock_dt"]
    assert len(clock_calls) == 1, "_bridge_dt must be assigned once from _bridge_clock_dt(...)"
    args = clock_calls[0].value.args
    assert len(args) == 3 and isinstance(args[1], ast.Name) and args[1].id == "_player_dt", (
        "_bridge_clock_dt's player-dt argument must be the paused-aware _player_dt")
    # The preview clock's frame dt must be the UNFROZEN wall delta: the
    # editor runs under the (hidden) pause menu, which zeroes _frame_dt, so a
    # _frame_dt-derived argument leaves the preview clock stuck at 0
    # (review C1: no pulses, tab fades never progress).
    third = {n.id for n in ast.walk(args[2]) if isinstance(n, ast.Name)}
    assert "_wall_dt" in third and "_frame_dt" not in third, (
        f"_bridge_clock_dt's frame-dt argument must come from _wall_dt; got {sorted(third)}")
    wall = [n for n in ast.walk(run_fn) if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "_wall_dt" for t in n.targets)]
    assert len(wall) == 1, "_wall_dt must be assigned once (the raw wall delta)"
    assert not any(isinstance(n, ast.Name) and n.id == "_frame_dt"
                   for n in ast.walk(wall[0].value)), "_wall_dt must not read the frozen _frame_dt"

    assert mix_call is not None, "no host_io.set_bridge_probe_mix(...) call found"
    # The mix call's sole argument must BE the update call (fed straight
    # through), not a separately-computed value.
    assert len(mix_call.args) == 1 and mix_call.args[0] is update_call

    assert on_alert_calls_with_guard, "on_alert(...) is never called from run()"
    assert all(on_alert_calls_with_guard), (
        "every on_alert(...) call must be inside an `if <level> != "
        "<something>:` guard comparing the SAME level variable fed to "
        "ProbeBlend.update, never unconditional")


# Task 17: the per-frame block also pushes the alert level for the emissive
# variants -- the SAME level variable ProbeBlend.update reads, every frame
# (never gated on a level change: a fresh BridgePass after a re-init must
# pick it up on the next frame).
def test_host_loop_pushes_the_alert_level_every_frame():
    import ast
    import inspect

    import engine.host_loop as hl

    tree = ast.parse(inspect.getsource(hl))
    run_fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "run")
    calls = [n for n in ast.walk(run_fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    update = next(c for c in calls if c.func.attr == "update"
                  and isinstance(c.func.value, ast.Name)
                  and c.func.value.id == "_bridge_probe_blend")
    pushes = [c for c in calls if c.func.attr == "set_bridge_alert_level"]
    assert len(pushes) == 1, "exactly one set_bridge_alert_level(...) push in run()"
    push = pushes[0]
    assert isinstance(push.func.value, ast.Name) and push.func.value.id == "host_io"
    assert len(push.args) == 1 and isinstance(push.args[0], ast.Name)
    assert push.args[0].id == update.args[0].id
    for node in ast.walk(run_fn):
        if isinstance(node, ast.If) and push in list(ast.walk(node)):
            for cmp in ast.walk(node.test):
                assert not (isinstance(cmp, ast.Compare)
                            and any(isinstance(op, ast.NotEq) for op in cmp.ops)), (
                    "the alert-level push must not be gated on a level change")


class _Power:
    def __init__(self, disabled=False, destroyed=False):
        self._d, self._x = disabled, destroyed

    def IsDisabled(self):
        return self._d

    def IsDestroyed(self):
        return self._x


class _Player:
    def __init__(self, alert=0, power=None):
        self._a, self._p = alert, power

    def GetAlertLevel(self):
        return self._a

    def GetPowerSubsystem(self):
        return self._p


@pytest.fixture
def no_special():
    bl.set_special_alert(False)
    yield
    bl.set_special_alert(False)


def test_bridge_state_follows_the_alert_level(no_special):
    assert [bl.bridge_state_of(_Player(a, _Power())) for a in (0, 1, 2)] == [0, 1, 2]
    assert bl.bridge_state_of(None) == bl.GREEN


def test_a_dead_power_plant_is_offline_over_any_alert(no_special):
    assert bl.bridge_state_of(_Player(2, _Power(disabled=True))) == bl.OFFLINE
    assert bl.bridge_state_of(_Player(0, _Power(destroyed=True))) == bl.OFFLINE
    bl.set_special_alert(True)
    assert bl.bridge_state_of(_Player(0, _Power(disabled=True))) == bl.OFFLINE


def test_special_overrides_the_alert_levels(no_special):
    bl.set_special_alert(True)
    assert bl.special_alert() is True
    assert bl.bridge_state_of(_Player(2, _Power())) == bl.SPECIAL


def test_no_power_subsystem_reads_as_powered(no_special):
    assert bl.bridge_state_of(_Player(1, None)) == bl.YELLOW


def test_ambient_scales_cover_the_five_states():
    assert bl.ambient_scale_for_alert(bl.OFFLINE) == bl.OFFLINE_AMBIENT_SCALE
    assert bl.OFFLINE_AMBIENT_SCALE < bl.ambient_scale_for_alert(bl.RED)
    assert bl.ambient_scale_for_alert(bl.SPECIAL) == bl.ambient_scale_for_alert(bl.RED)
