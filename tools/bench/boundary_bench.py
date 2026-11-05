"""Python<->C++ boundary benchmark (phase 6 B0, perf-register SIG-198).

Each variant reads the same three doubles (a ship position) a different way
across the boundary. Prints one row per variant: ``variant  ns/call
allocs/call``. Time is the best of 5 repeats of N calls (perf_counter_ns);
allocs/call is the net Python allocation count per call from tracemalloc over
one extra repeat. Needs a built ``_dauntless_host`` (build/python).

    uv run python tools/bench/boundary_bench.py [--calls N]

Run it on a Release build for numbers worth recording.
"""
from __future__ import annotations

import argparse
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build" / "python"))

import _dauntless_host as _h  # noqa: E402

from engine.appc.math import TGPoint3  # noqa: E402
from engine.appc.transform_store import get_store  # noqa: E402

REPEATS = 5


def _loop_source(body: str) -> str:
    return ("def run(n):\n"
            "    for _ in range(n):\n"
            "        %s\n" % body)


def _make(body: str, env: dict):
    ns = dict(env)
    exec(_loop_source(body), ns)
    return ns["run"]


def _time(run, n: int) -> float:
    best = None
    for _ in range(REPEATS):
        t0 = time.perf_counter_ns()
        run(n)
        dt = time.perf_counter_ns() - t0
        best = dt if best is None else min(best, dt)
    return best / n


def _alloc_blocks(body: str, env: dict, n: int) -> float:
    """Allocation blocks per call, counted by tracemalloc over one repeat.

    tracemalloc only sees live blocks, so the alloc form of each body appends
    every object the call creates (result AND intermediates such as the tuple
    or memoryview) to a list; the count is then the blocks that list holds."""
    m = max(1, min(n, 2000))
    keep: list = []
    env = dict(env, keep=keep)
    run = _make(body, env)
    run(50)
    keep.clear()
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    run(m)
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    blocks = sum(st.count_diff for st in after.compare_to(before, "filename"))
    # The list's own growth is bookkeeping, not part of the call.
    return max(0.0, (blocks - 1) / m)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=1_000_000)
    args = ap.parse_args()
    n = args.calls

    store = get_store()
    if type(store).__name__ != "NativeTransformStore":
        print("boundary_bench: native transform store unavailable", file=sys.stderr)
        return 2
    i, g = store.alloc()
    store.set_position(i, g, 1.5, -2.25, 3.125)

    _h.bench_set_point_class(TGPoint3)
    sink = TGPoint3(0.0, 0.0, 0.0)
    npt = _h.bench_native_point(i, g)
    slot_pt = TGPoint3(1.5, -2.25, 3.125)
    view = _h.bench_position_view(i, g)

    from engine.appc import native_combat
    h = _h.combat_register(native_combat._kind("Object"), i, g, 1, 0)
    fid = native_combat._fid("_radius")
    code = native_combat._push_code("PUSH_FLOAT")

    env = dict(get_store=get_store, TGPoint3=TGPoint3, i=i, g=g, h=h, fid=fid,
               code=code, h_=_h, sink=sink, npt=npt, slot_pt=slot_pt,
               view=view,
               tuple_fn=_h.bench_get_pos_tuple, new_fn=_h.bench_new_point,
               fill_fn=_h.bench_fill_point, nat_fn=_h.bench_native_point,
               view_fn=_h.bench_position_view, noop=_h.bench_noop,
               push=_h.combat_push_scalar)
    env["xform"] = (i, g)

    # (name, timed body, body that also keeps every object it creates)
    variants = [
        ("py_method",
         "x, y, z = get_store().get_position(*xform); TGPoint3(x, y, z)",
         "t = get_store().get_position(*xform); keep.append(t);"
         " keep.append(TGPoint3(*t))"),
        ("bind_tuple", "x, y, z = tuple_fn(i, g); TGPoint3(x, y, z)",
         "t = tuple_fn(i, g); keep.append(t); keep.append(TGPoint3(*t))"),
        ("bind_new_obj", "new_fn(i, g)", "keep.append(new_fn(i, g))"),
        ("bind_fill", "fill_fn(i, g, sink)", "fill_fn(i, g, sink)"),
        ("native_point", "nat_fn(i, g)", "keep.append(nat_fn(i, g))"),
        ("buffer_view",
         "v = view_fn(i, g); TGPoint3(v[0], v[1], v[2])",
         "v = view_fn(i, g); keep.append(v);"
         " keep.append(TGPoint3(v[0], v[1], v[2]))"),
        ("buffer_view_cached", "TGPoint3(view[0], view[1], view[2])",
         "keep.append(TGPoint3(view[0], view[1], view[2]))"),
        ("read_x_native", "npt.x", "keep.append(npt.x)"),
        ("read_x_slots", "slot_pt.x", "keep.append(slot_pt.x)"),
        ("push_scalar", "push(h, fid, code, 2.5)",
         "keep.append(push(h, fid, code, 2.5))"),
        ("noop", "noop()", "keep.append(noop())"),
    ]

    expected = tuple(store.get_position(i, g))
    assert expected == (1.5, -2.25, 3.125), expected
    checks = {
        "py_method": "(lambda p: (p.x, p.y, p.z))(TGPoint3(*get_store().get_position(*xform)))",
        "bind_tuple": "tuple(tuple_fn(i, g))",
        "bind_new_obj": "(lambda p: (p.x, p.y, p.z))(new_fn(i, g))",
        "bind_fill": "(fill_fn(i, g, sink), (sink.x, sink.y, sink.z))[1]",
        "native_point": "(lambda p: (p.x, p.y, p.z))(nat_fn(i, g))",
        "buffer_view": "tuple(view_fn(i, g))",
        "buffer_view_cached": "tuple(view)",
    }
    for name, expr in checks.items():
        got = eval(expr, dict(env))
        if got != expected:
            print("boundary_bench: variant %s read %r, expected %r"
                  % (name, got, expected), file=sys.stderr)
            return 3
    mv = _h.bench_position_view(i, g)
    if mv.format != "d" or len(mv) != 3:
        print("boundary_bench: buffer view is format %r len %d, want 'd' 3"
              % (mv.format, len(mv)), file=sys.stderr)
        return 3
    print("verified: every variant reads %r" % (expected,))

    print("%-20s %10s %12s" % ("variant", "ns/call", "allocs/call"))
    for name, body, alloc_body in variants:
        run = _make(body, env)
        run(1000)
        ns = _time(run, n)
        allocs = _alloc_blocks(alloc_body, env, n)
        print("%-20s %10.1f %12.2f" % (name, ns, allocs))
    _h.combat_unregister(h)
    store.free(i, g)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
