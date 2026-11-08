"""The Python AI tree walker is gone from the engine (phase 6 AI part 4,
Task 8).

Mark's rule (2026-11-07): ported code keeps no permanent Python copy in the
engine. The walker lives in native/src/host/aitree.cc; the Python statement-
for-statement reference it was proven against is a frozen TEST ORACLE
(tests/helpers/ai_walker_oracle.py). What remains in ai_driver under the old
walker names are one-statement forwarders into the native binding, kept so a
test or mod can still patch or wrap the name (the native walk runs a name's
body natively only while the module global is the stock forwarder, see
``_STOCK_WALK``).
"""
import ast
import pathlib

from engine.appc import ai_driver

_SRC = pathlib.Path(ai_driver.__file__).read_text()
_TREE = ast.parse(_SRC)

#: Names that were a Python walker body and no longer exist at all.
GONE = (
    "_native_walker", "_tick_ai_python", "_tick_all_ai_python",
    "_tick_all_ai_native", "_refresh_conditional_status_python",
    "_eval_conditional_python", "_condition_statuses_python",
    "_any_condition_python",
)

#: Names that stay (patch targets, `_STOCK_WALK` / `_STOCK_HANDLERS` members,
#: public entry points) but may only forward to the native binding.
FORWARDERS = (
    "tick_all_ai", "tick_ai", "_dispatch_ai", "_tick_plain",
    "_tick_priority_list", "_tick_sequence", "_tick_random",
    "_tick_conditional", "_tick_preprocessing", "_tick_builder",
    "_dispatch_priority_child", "_queue_got_focus", "_focus_instance_of",
    "_retain_subtree_focus", "_reconcile_focus", "_dispatch_lost_focus",
    "_flush_pending_got_focus", "_reconcile_active",
    "_refresh_conditional_status", "_condition_statuses", "_any_condition",
    "_eval_conditional",
)


def _defs():
    return {n.name: n for n in _TREE.body if isinstance(n, ast.FunctionDef)}


def test_no_python_tree_walker_remains():
    defs = _defs()
    for name in GONE:
        assert name not in defs, name + " is still defined"
        assert not hasattr(ai_driver, name), name + " is still an attribute"


def test_the_walker_names_only_forward_to_native():
    defs = _defs()
    for name in FORWARDERS:
        assert name in defs, name + " must keep its name (patch target)"
        body = [s for s in defs[name].body
                if not (isinstance(s, ast.Expr)
                        and isinstance(s.value, ast.Constant))]
        assert len(body) == 1, "%s has %d statements" % (name, len(body))
        calls = [c.func.id for c in ast.walk(body[0])
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
        assert calls and all(c.startswith("_aitree_") for c in calls), (
            "%s calls %r, not a native binding" % (name, calls))


def test_the_native_gate_names_survive():
    for name in ("_DISPATCH_BY_TYPE", "_resolve_dispatch", "_run_script_step",
                 "_activate_builder", "_ensure_select_target_initialized",
                 "_sync_fire_script_target_subsystem", "fire_ai_done",
                 "_dispatch_lost_focus", "_focus_instance_of",
                 "_memoisable_evalfunc", "_MEMO_KEY_TYPES",
                 "AI_MAX_SLEEP_TICKS", "_TICK_SECONDS", "_AI_BREAKDOWN",
                 "_timed_dispatch", "_STOCK_WALK", "_STOCK_HANDLERS",
                 "_STOCK_SET_ACTIVE", "_STOCK_SET_INACTIVE",
                 "_STOCK_CONDITION_GETSTATUS",
                 "_note_due", "_note_due_ret", "_focus_depth", "_ooa_cache",
                 "_reached_this_tick", "_reached_this_tick_all",
                 "_reached_this_tick_all_ids", "_pending_got_focus"):
        assert hasattr(ai_driver, name), name
    for name in FORWARDERS:
        assert name in ai_driver._STOCK_WALK or name in (
            "tick_all_ai", "_tick_plain", "_tick_priority_list",
            "_tick_sequence", "_tick_random", "_tick_conditional",
            "_tick_builder"), name
