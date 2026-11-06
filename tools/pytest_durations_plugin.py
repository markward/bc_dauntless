"""pytest plugin: every test's setup + call + teardown seconds, as JSON at
$GATE_DURATIONS_OUT ({nodeid: seconds}). The full gate loads it
(tools/check_test_baseline.py --tier full) so tools/gate_tiers.py can
regenerate the merge tier from measured times. Loaded with
`-p tools.pytest_durations_plugin` (the gate puts the project root on
PYTHONPATH). Writes nothing when the variable is unset.
"""
import json
import os
from collections import defaultdict

_durations = defaultdict(float)


def pytest_runtest_logreport(report):
    _durations[report.nodeid] += report.duration


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("GATE_DURATIONS_OUT")
    if not out:
        return
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({k: round(v, 4) for k, v in sorted(_durations.items())}, fh)
    os.replace(tmp, out)
