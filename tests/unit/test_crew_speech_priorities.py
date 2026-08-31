"""CSP_* speech-priority constants must match BC's measured polarity (LOWER
number = HIGHER priority) and CrewSpeechBus.speak's arbitration must be
written to match -- these two things must never drift apart (see
engine/appc/ai.py CSP_* and engine/appc/crew_speech.py CrewSpeechBus.speak)."""
import sys

import App
from engine.appc.ai import (
    CSP_SPONTANEOUS, CSP_NORMAL, CSP_MISSION_CRITICAL, CSP_LOW, CSP_HIGH,
)
from engine.appc.crew_speech import CrewSpeechBus


def test_priority_constants_are_bcs_measured_values():
    """BC's convention is LOWER number = HIGHER priority."""
    assert App.CSP_MISSION_CRITICAL == 0
    assert App.CSP_NORMAL == 1
    assert App.CSP_SPONTANEOUS == 2
    assert (CSP_MISSION_CRITICAL, CSP_NORMAL, CSP_SPONTANEOUS) == (0, 1, 2)


def test_legacy_aliases_preserved():
    assert CSP_LOW == CSP_SPONTANEOUS
    assert CSP_HIGH == CSP_MISSION_CRITICAL
    assert len({CSP_LOW, CSP_NORMAL, CSP_HIGH}) == 3


def test_app_exposes_real_ints_with_stable_identity():
    # The bug: App.CSP_SPONTANEOUS used to return a fresh _NamedStub each time.
    assert App.CSP_SPONTANEOUS == 2
    assert App.CSP_MISSION_CRITICAL == 0
    assert App.CSP_NORMAL == 1
    assert App.CSP_SPONTANEOUS == App.CSP_SPONTANEOUS
    assert App.CSP_MISSION_CRITICAL is App.CSP_MISSION_CRITICAL


def test_mission_critical_line_interrupts_idle_chatter():
    """The behaviour the polarity protects: scripted narration must win."""
    bus = CrewSpeechBus()
    assert bus.speak("Felix", "idle", None, App.CSP_SPONTANEOUS, now=0.0) > 0.0
    assert bus.speak("Saffi", "critical", None, App.CSP_MISSION_CRITICAL,
                     now=0.1) > 0.0, "mission-critical must interrupt chatter"


def test_idle_chatter_does_not_interrupt_a_mission_critical_line():
    bus = CrewSpeechBus()
    assert bus.speak("Saffi", "critical", None, App.CSP_MISSION_CRITICAL,
                     now=0.0) > 0.0
    assert bus.speak("Felix", "idle", None, App.CSP_SPONTANEOUS,
                     now=0.1) == 0.0, "chatter must lose to mission-critical"


def test_fresh_bus_accepts_its_first_line_regardless_of_priority():
    """A fresh bus (never spoken) must accept its very first line even at
    the lowest priority (largest number). In practice this is already
    guaranteed by the `line_live` gate (a fresh bus has `_active_expiry ==
    0.0`, so `line_live` is False and the sentinel comparison never runs) --
    but confirm the observable behaviour anyway."""
    bus = CrewSpeechBus()
    assert bus.speak("Felix", "first line ever", None, App.CSP_SPONTANEOUS,
                     now=0.0) > 0.0


def test_idle_sentinel_is_unreachable_but_correct_if_it_were_reached():
    """The idle sentinel (`_active_priority` at construction/reset) can never
    actually gate a real `speak()` call: `line_live` requires `_active_expiry`
    to be in the future, and `_active_expiry` is only ever advanced together
    with `_active_priority` inside `speak()` -- so a live line's priority is
    never compared against the sentinel. This test forces that otherwise-
    unreachable branch directly to pin the sentinel's own polarity: it must
    be a value nothing can outrank (`sys.maxsize`), not `-1` (which, under
    BC's polarity, would make the sentinel outrank every real priority and
    silently drop every line, were the branch ever reached)."""
    bus = CrewSpeechBus()
    assert bus._active_priority == sys.maxsize
    bus._active_expiry = 1_000_000.0  # force line_live True without going through speak()
    assert bus.speak("Felix", "should not be dropped", None,
                     App.CSP_MISSION_CRITICAL, now=0.0) > 0.0
