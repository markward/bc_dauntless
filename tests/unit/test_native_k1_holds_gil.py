"""K1 holds the GIL (native combat phase 1b, controller ruling J).

Spec §3.3 has the kernel release the GIL while it computes. Phase 1b does
not: each combat_k1_* call takes microseconds, and with the GIL released
another Python thread (the packaged build's log tee) could run cyclic GC,
whose weakref finalizers free mirror rows (native_combat.unregister_handle)
while the kernel is reading them. The release belongs to the later
worker-thread phase, which must bring its own row-lifetime guarantee.

A released GIL cannot be caught by a behavioural test (the race needs a
second thread to collect at the wrong microsecond), so this guards the
source: no ``gil_scoped_release`` anywhere in the K1 bindings.
"""
import re
from pathlib import Path

BINDINGS = (Path(__file__).resolve().parents[2] / "native" / "src" / "host"
            / "host_bindings.cc")


def _k1_block(text):
    """From the first combat_k1_ definition to the end of the last one's
    statement."""
    names = [m.start() for m in re.finditer(r'm\.def\("combat_k1_', text)]
    assert names, "no combat_k1_ bindings found"
    end = text.index(");", names[-1])
    return text[names[0]:end]


def test_k1_bindings_never_release_the_gil():
    block = _k1_block(BINDINGS.read_text())
    assert "combat_k1_next" in block
    assert "gil_scoped_release" not in block
    assert "Py_BEGIN_ALLOW_THREADS" not in block
    assert "call_guard" not in block
