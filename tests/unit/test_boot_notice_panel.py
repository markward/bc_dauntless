"""The boot notice splash's state machine: wording, fade schedule, clock start.

The SDK licence (SDKLicense.txt, "New Game Materials") requires the opening
screen to carry the creator's name and contact and the exact words "THIS
MATERIAL IS NOT MADE OR SUPPORTED BY ACTIVISION." The pump loop that draws it
is covered in tests/host/test_boot_notice_pump.py; this file is the panel
alone, driven by a fake wall clock.
"""
import json
import re

import pytest

from engine import paths
from engine.ui import boot_notice_panel as bn


class FakeClock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def _payload(script):
    m = re.fullmatch(r"setBootNotice\((.*)\);", script)
    assert m, script
    return json.loads(m.group(1))


def _acked(clock):
    panel = bn.BootNoticePanel(clock=clock)
    panel.render_payload()
    assert panel.dispatch_event("shown")
    return panel


# ── wording ─────────────────────────────────────────────────────────────

def test_the_notice_line_is_the_licence_wording_exactly():
    assert bn.NOTICE_LINE == "THIS MATERIAL IS NOT MADE OR SUPPORTED BY ACTIVISION."


def test_the_wording_matches_the_player_readme():
    readme = (paths.PROJECT_ROOT / "docs" / "packaging" / "README.txt").read_text()
    assert bn.NOTICE_LINE in readme
    assert "Created by Mark Ward" in readme
    assert "github.com/markward/bc_dauntless" in readme
    assert bn.CREDIT_LINE == "Created by Mark Ward - github.com/markward/bc_dauntless"


def test_the_first_payload_carries_both_lines_at_zero_opacity():
    panel = bn.BootNoticePanel(clock=FakeClock())
    p = _payload(panel.render_payload())
    assert p["lines"] == [bn.NOTICE_LINE, bn.CREDIT_LINE]
    assert p["opacity"] == 0.0
    assert p["ack"] is True


# ── schedule ────────────────────────────────────────────────────────────

def test_the_schedule_is_one_second_in_two_hold_two_out():
    assert (bn.FADE_IN_S, bn.HOLD_S, bn.FADE_OUT_S) == (1.0, 2.0, 2.0)
    assert bn.TOTAL_S == 5.0


@pytest.mark.parametrize("t, expected", [
    (-1.0, 0.0),
    (0.0, 0.0),
    (0.5, 0.5),
    (1.0, 1.0),
    (2.0, 1.0),
    (3.0, 1.0),
    (4.0, 0.5),
    (5.0, 0.0),
    (9.0, 0.0),
])
def test_opacity_follows_the_schedule(t, expected):
    assert bn.opacity_at(t) == pytest.approx(expected)


# ── the clock starts when the page shows the notice ─────────────────────

def test_nothing_counts_down_before_the_page_acknowledges():
    """CEF drops every push until the page loads (~340 ms). A clock started
    at construction would spend the fade-in on a page that cannot show it."""
    clock = FakeClock()
    panel = bn.BootNoticePanel(clock=clock)
    panel.render_payload()
    clock.t += 6.0
    assert panel.outcome is None
    assert _payload(panel.render_payload())["opacity"] == 0.0


def test_the_arm_payload_repeats_until_acknowledged():
    """A dropped push cannot be detected, so the panel keeps offering it
    rather than diffing it away after the first (dropped) copy."""
    panel = bn.BootNoticePanel(clock=FakeClock())
    first = panel.render_payload()
    assert panel.render_payload() == first


def test_fade_in_hold_and_fade_out_are_measured_from_the_acknowledgement():
    clock = FakeClock()
    panel = bn.BootNoticePanel(clock=clock)
    panel.render_payload()
    clock.t += 0.34            # the page took a while to load
    panel.dispatch_event("shown")

    seen = {}
    for t in (0.0, 0.5, 1.0, 2.0, 2.9, 4.0, 4.9):
        clock.t = 100.34 + t
        assert panel.outcome is None, t
        script = panel.render_payload()
        if script is not None:
            seen[t] = _payload(script)["opacity"]
    assert seen[0.0] == pytest.approx(0.0)
    assert seen[0.5] == pytest.approx(0.5)
    assert seen[1.0] == pytest.approx(1.0)
    assert 2.0 not in seen and 2.9 not in seen   # hold: nothing changes
    assert seen[4.0] == pytest.approx(0.5)
    assert seen[4.9] == pytest.approx(0.05)

    clock.t = 100.34 + 5.0
    assert panel.outcome == "shown"


def test_a_second_acknowledgement_does_not_restart_the_clock():
    clock = FakeClock()
    panel = _acked(clock)
    clock.t += 4.0
    panel.dispatch_event("shown")
    clock.t += 1.0
    assert panel.outcome == "shown"


def test_unknown_events_are_not_handled():
    panel = bn.BootNoticePanel(clock=FakeClock())
    assert panel.dispatch_event("skip") is False
    assert panel.outcome is None


def test_escape_cannot_skip_the_notice():
    """The pump loop offers Escape to any panel with handle_key_esc. The
    notice is a licence requirement, so it has none."""
    assert not hasattr(bn.BootNoticePanel, "handle_key_esc")


# ── a page that never loads must not hang boot ──────────────────────────

def test_no_acknowledgement_gives_up_after_the_timeout():
    clock = FakeClock()
    panel = bn.BootNoticePanel(clock=clock)
    panel.render_payload()
    clock.t += bn.ACK_TIMEOUT_S - 0.01
    assert panel.outcome is None
    clock.t += 0.02
    assert panel.outcome == "unshown"


def test_the_teardown_hides_the_notice():
    clock = FakeClock()
    panel = _acked(clock)
    clock.t += 5.0
    assert panel.teardown_script == "setBootNotice(null);"


# ── held: the game loads behind the notice ──────────────────────────────

def _held(clock):
    panel = bn.BootNoticePanel(clock=clock, hold=True)
    panel.render_payload()
    panel.dispatch_event("shown")
    return panel


def test_a_held_notice_hands_back_at_full_opacity_and_stays_up():
    clock = FakeClock()
    panel = _held(clock)
    clock.t += bn.FADE_IN_S
    assert panel.outcome is None          # still settling at full opacity
    assert _payload(panel.render_payload())["opacity"] == 1.0
    clock.t += bn.HOLD_SETTLE_S
    assert panel.outcome == "holding"
    assert panel.teardown_script is None  # the notice is not hidden


def test_an_unreleased_notice_never_fades():
    clock = FakeClock()
    panel = _held(clock)
    clock.t += 60.0
    assert panel.outcome == "holding"
    assert _payload(panel.render_payload())["opacity"] == 1.0


def test_a_quick_load_still_gets_the_full_two_second_hold():
    clock = FakeClock()
    panel = _held(clock)
    clock.t += 1.5
    panel.release()                       # loaded in half a second
    clock.t = 100.0 + 2.9
    assert panel.outcome is None
    assert _payload(panel.render_payload())["opacity"] == 1.0
    clock.t = 100.0 + 4.0
    assert _payload(panel.render_payload())["opacity"] == pytest.approx(0.5)
    clock.t = 100.0 + 5.0
    assert panel.outcome == "shown"


def test_a_long_load_lengthens_the_hold_then_fades_for_two_seconds():
    clock = FakeClock()
    panel = _held(clock)
    clock.t = 100.0 + 7.0
    panel.release()                       # the load took six seconds
    assert panel.outcome is None
    assert _payload(panel.render_payload())["opacity"] == 1.0
    clock.t = 100.0 + 8.0
    assert _payload(panel.render_payload())["opacity"] == pytest.approx(0.5)
    clock.t = 100.0 + 8.99
    assert panel.outcome is None
    clock.t = 100.0 + 9.0
    assert panel.outcome == "shown"
    assert panel.teardown_script == "setBootNotice(null);"
