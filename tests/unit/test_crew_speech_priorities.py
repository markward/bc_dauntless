"""CSP_* speech-priority constants must be real, ordered ints and stable
across repeated App attribute accesses (identity-regression guard for the
_NamedStub footgun)."""
import App
from engine.appc.ai import (
    CSP_SPONTANEOUS, CSP_NORMAL, CSP_MISSION_CRITICAL, CSP_LOW, CSP_HIGH,
)


def test_priorities_are_ordered_ints():
    assert (CSP_SPONTANEOUS, CSP_NORMAL, CSP_MISSION_CRITICAL) == (0, 1, 2)
    assert CSP_SPONTANEOUS < CSP_NORMAL < CSP_MISSION_CRITICAL


def test_legacy_aliases_preserved():
    assert CSP_LOW == CSP_SPONTANEOUS
    assert CSP_HIGH == CSP_MISSION_CRITICAL
    assert len({CSP_LOW, CSP_NORMAL, CSP_HIGH}) == 3


def test_app_exposes_real_ints_with_stable_identity():
    # The bug: App.CSP_SPONTANEOUS used to return a fresh _NamedStub each time.
    assert App.CSP_SPONTANEOUS == 0
    assert App.CSP_MISSION_CRITICAL == 2
    assert App.CSP_NORMAL == 1
    assert App.CSP_SPONTANEOUS == App.CSP_SPONTANEOUS
    assert App.CSP_MISSION_CRITICAL is App.CSP_MISSION_CRITICAL
