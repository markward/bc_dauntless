"""The binding exists and has the shape first_run expects.

Deliberately never CALLS it: pick_folder shows a modal panel and would
hang the suite forever. What is worth pinning is that the symbol is
present, because engine/first_run.py getattr-guards it -- so a stale .so
degrades to "no picker" in silence, which is the same class of failure
that hid ~73 dark-skipped tests on the path-resolution branch.
"""

import pytest

_h = pytest.importorskip("_dauntless_host")


def test_pick_folder_binding_is_present():
    assert hasattr(_h, "pick_folder"), (
        "_dauntless_host.pick_folder is missing -- rebuild from build/. "
        "engine/first_run.py treats an absent binding as 'no picker', so "
        "without this test a stale .so silently disables the first-run "
        "dialog instead of failing."
    )


def test_pick_folder_requires_both_arguments():
    # pybind11 rejects on overload resolution BEFORE invoking the function,
    # so this genuinely exercises the binding's declared signature without
    # any risk of actually opening the modal panel.
    with pytest.raises(TypeError):
        _h.pick_folder()
