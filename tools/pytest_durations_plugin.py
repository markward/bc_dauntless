"""pytest plugin: every test's setup + call + teardown seconds, as JSON at
$GATE_DURATIONS_OUT ({nodeid: seconds}); and beside it, <that>.rss.json,
the tests during which the process's peak RSS (ru_maxrss) rose, with the
rise in MB -- where the memory high-water was set. The full gate loads it
(tools/check_test_baseline.py --tier full) so tools/gate_tiers.py can
regenerate the merge tier from measured times. Loaded with
`-p tools.pytest_durations_plugin` (the gate puts the project root on
PYTHONPATH). Writes nothing when the variable is unset.
"""
import json
import os
import resource
import sys
from collections import defaultdict

import pytest

_durations = defaultdict(float)
_rss_steps = {}
# ru_maxrss is bytes on macOS, KB elsewhere.
_RSS_UNIT_MB = 1.0 / (1024 * 1024) if sys.platform == "darwin" else 1.0 / 1024


def _maxrss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * _RSS_UNIT_MB


def pytest_runtest_logreport(report):
    _durations[report.nodeid] += report.duration


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    before = _maxrss_mb()
    yield
    rise = _maxrss_mb() - before
    if rise >= 1.0:
        _rss_steps[item.nodeid] = round(rise, 1)


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("GATE_DURATIONS_OUT")
    if not out:
        return
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({k: round(v, 4) for k, v in sorted(_durations.items())}, fh)
    os.replace(tmp, out)
    with open(out + ".rss.json", "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(_rss_steps.items(), key=lambda kv: -kv[1])), fh)
