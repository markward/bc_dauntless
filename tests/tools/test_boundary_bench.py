"""tools/bench/boundary_bench.py prints a row for every boundary variant."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VARIANTS = ("py_method", "bind_tuple", "bind_new_obj", "bind_fill",
            "native_point", "buffer_view", "push_scalar", "noop")


def test_boundary_bench_runs_every_variant():
    out = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "bench" /
                             "boundary_bench.py"), "--calls", "1000"],
        capture_output=True, text=True, cwd=PROJECT_ROOT, check=True).stdout
    assert "verified: every variant reads (1.5, -2.25, 3.125)" in out, out
    rows = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] in VARIANTS:
            rows[parts[0]] = (float(parts[1]), float(parts[2]))
    for name in VARIANTS:
        assert name in rows, "missing %s in:\n%s" % (name, out)
        assert rows[name][0] > 0, name
