"""What Python does after a kernel applied hits in its compute (native
damage Task 4; engine/appc/native_combat.py _kernel_hits_landed).

combat.apply_hit forgets the step memo on entry and exit -- the Python
tables (engine.core.step_memo) and, through the on_forget hook, the
native memo. A kernel's hit clears the native memo itself, at the hit
(k2_beams.h THE DAMAGE PULSE, DM H13); the Python tables are cleared before
the next Python reader, at the kernel's next record -- and ONLY them: the
native memo the kernel filled since the hit must survive, as it does in the
reference (a memo hit skips a latch write a recompute would make)."""
from engine.appc import hit_feedback
from engine.appc import native_combat as nc
from engine.core import step_memo


def test_forget_tables_empties_the_tables_and_calls_no_hook(monkeypatch):
    called = []
    monkeypatch.setattr(step_memo, "_forget_hooks", [lambda: called.append(1)])
    table = step_memo.table()
    try:
        table["answer"] = 1
        step_memo.forget_tables()
        assert table == {}
        assert called == []
        table["answer"] = 2
        step_memo.forget()
        assert table == {} and called == [1]
    finally:
        step_memo._tables[:] = [t for t in step_memo._tables if t is not table]


def test_hits_landed_forgets_the_tables_and_sets_the_map(monkeypatch):
    called = []
    monkeypatch.setattr(step_memo, "_forget_hooks", [lambda: called.append(1)])
    used = []
    monkeypatch.setattr(hit_feedback, "use_instances", used.append)
    table = step_memo.table()
    try:
        table["answer"] = 1
        instances = object()
        nc._kernel_hits_landed(instances)
        assert table == {} and called == []
        assert used == [instances]
        nc._kernel_hits_landed(None)    # no map: delivery presents none
        assert used == [instances]
    finally:
        step_memo._tables[:] = [t for t in step_memo._tables if t is not table]
