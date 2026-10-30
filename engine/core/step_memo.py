"""Answers that hold for a stretch of the combat step.

Inside `combat_step()`, a module may answer a repeated question from a table
instead of recomputing it -- engine.appc.sensor_detection (can_detect per
observer/target pair) and engine.appc.subsystems (a mount's world position).
In a 64-ship fight those two were asked ~100 times a tick each, a third to
three quarters of the asks repeats within the same step.

A table is only correct while nothing it depends on changes, so `forget()`
drops every table's answers. host_loop._advance_combat opens the block and
forgets around deaths, subsystem damage and tractors; combat.apply_hit
forgets on every hit. Outside a block, `active()` is False and every caller
computes as it always did.
"""
import contextlib

_depth = 0
_tables: list = []


def table() -> dict:
    """A dict this module empties on forget() and when the outermost block
    closes. Callers keep it and read it only while active()."""
    t = {}
    _tables.append(t)
    return t


def active() -> bool:
    return _depth > 0


def forget() -> None:
    """Something an answer may depend on changed: drop them all."""
    for t in _tables:
        t.clear()


@contextlib.contextmanager
def combat_step():
    """Open (or join) a block. The outermost block's exit drops every
    answer, so the objects keyed by id() never outlive it."""
    global _depth
    _depth += 1
    try:
        yield
    finally:
        _depth -= 1
        if _depth == 0:
            forget()
