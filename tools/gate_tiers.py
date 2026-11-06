"""Maintain the two test-gate tiers (docs/superpowers/specs/
2026-11-06-two-tier-test-gate-design.md).

  uv run python tools/gate_tiers.py generate <artefact dir>   # rewrite the deep lists
  uv run python tools/gate_tiers.py project  <artefact dir>   # merge-tier cost, gaps

<artefact dir> is what scripts/gate_full.sh writes (it prints the path):
pytest_durations.json (per-test seconds) and inproc_<binary>.log (each gtest
binary's own output, per-case ms). After `generate`, commit
tests/gate_tiers/deep_pytest.txt and deep_gtest.txt.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import gate_tiers as gt  # noqa: E402


def _project(artefact_dir):
    durations, case_ms = gt.load_artefacts(artefact_dir)
    py = gt.project_pytest(durations, gt.load_deep_pytest())
    cc = gt.project_gtest(case_ms, gt.load_deep_gtest())
    gaps = gt.coverage_gaps(gt.load_deep_pytest())
    return py, cc, gaps


def main(argv):
    if len(argv) != 2 or argv[0] not in ("generate", "project"):
        print(__doc__)
        return 2
    cmd, art = argv
    if cmd == "generate":
        durations, case_ms = gt.load_artefacts(art)
        entries, py = gt.generate_pytest(durations)
        chosen, cc = gt.generate_gtest(case_ms)
        gt.write_pytest(entries, py)
        gt.write_gtest(chosen, cc)
        print("deep_pytest.txt: %d entries; merge tier %.0f s of %.0f s measured"
              % (len(entries), py, sum(durations.values())))
        print("deep_gtest.txt: %d cases; merge tier %.0f s"
              % (sum(len(v) for v in chosen.values()), cc))
    py, cc, gaps = _project(art)
    print("projected merge tier: pytest %.0f s (fail over %.0f), gtest %.0f s (fail over %.0f)"
          % (py, gt.PYTEST_FAIL_S, cc, gt.GTEST_FAIL_S))
    if gaps:
        print("areas without merge-tier coverage: " + ", ".join(gaps))
    return 1 if gaps or py > gt.PYTEST_FAIL_S or cc > gt.GTEST_FAIL_S else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
