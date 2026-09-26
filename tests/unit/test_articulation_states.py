"""Four alert states, and warp outranks all of them.

Warp wins because wing position is a FLIGHT configuration -- warp entry should
visibly re-configure the ship. NPCs never show 'yellow': BC never takes an NPC
off Red Alert (measured; stbc-oracle bible s13 N2), which is why NPC
articulation keys off 'has a target' rather than off alert level.
"""
import pytest

from engine.appc import articulation, part_pose


class _Ship:
    def __init__(self, *, player=False, alert=0, warping=False, target=None):
        self._player = player
        self._alert = alert
        self._warping = warping
        self._target = target

    def GetAlertLevel(self):
        return self._alert

    def GetTarget(self):
        return self._target


def test_warp_beats_red_alert(monkeypatch):
    """THE precedence rule. A ship running under fire is still in its travel
    shape."""
    import App
    ship = _Ship(player=True, alert=App.ShipClass.RED_ALERT, warping=True)
    monkeypatch.setattr(articulation, "_is_player", lambda s: True)
    monkeypatch.setattr(articulation, "_is_warping", lambda s: s._warping)
    assert articulation.state_for(ship) == "warp"


def test_player_states_follow_alert_level(monkeypatch):
    import App
    monkeypatch.setattr(articulation, "_is_player", lambda s: True)
    monkeypatch.setattr(articulation, "_is_warping", lambda s: False)
    assert articulation.state_for(
        _Ship(alert=App.ShipClass.RED_ALERT)) == "red"
    assert articulation.state_for(
        _Ship(alert=App.ShipClass.YELLOW_ALERT)) == "yellow"
    assert articulation.state_for(_Ship(alert=0)) == "cruise"


def test_an_npc_uses_red_when_it_has_a_target(monkeypatch):
    """NPCs never leave Red Alert in BC, so alert level carries no signal for
    them. 'Has a target' is the measured proxy."""
    monkeypatch.setattr(articulation, "_is_player", lambda s: False)
    monkeypatch.setattr(articulation, "_is_warping", lambda s: False)
    assert articulation.state_for(_Ship(target=object())) == "red"
    assert articulation.state_for(_Ship(target=None)) == "cruise"


def test_an_npc_NEVER_shows_yellow(monkeypatch):
    """Pinned deliberately. Inventing NPC alert levels was rejected."""
    import App
    monkeypatch.setattr(articulation, "_is_player", lambda s: False)
    monkeypatch.setattr(articulation, "_is_warping", lambda s: False)
    for target in (object(), None):
        assert articulation.state_for(
            _Ship(alert=App.ShipClass.YELLOW_ALERT, target=target)) != "yellow"


# The easing tests that lived here (ease_angle / TRAVEL_SECONDS /
# rotation_for) moved with the pose runtime: see
# tests/unit/test_articulation_transitions.py for the transition timing and
# the interrupted-transition rule.


class _Rigged:
    """A Bird of Prey for the transition tests: a leaf, nothing else."""
    _articulation_leaf = "birdofprey"


def _tip(ship, part, x):
    return part_pose.apply(articulation.pose_for_part(ship, part), x)


def test_mirrored_parts_stay_in_sync(monkeypatch):
    """The real BoP case: the wing pair is authored mirrored (+45 / -45 about
    the fore-aft axis, mirrored anchors) with one transition time, so both
    reach their target -- and every point in between -- on the same tick,
    as mirror images."""
    monkeypatch.setattr(articulation, "state_for", lambda ship: "cruise")
    port, starboard = articulation.rig_for("birdofprey")
    ship = _Rigged()
    articulation.tick_ship(ship, 0.7)
    a = _tip(ship, port, (-1.0, 0.45, -0.7))
    b = _tip(ship, starboard, (1.0, 0.45, -0.7))
    assert a != pytest.approx((-1.0, 0.45, -0.7)), "mid-swing, not at rest"
    assert (a[0], a[1], a[2]) == pytest.approx((-b[0], b[1], b[2]), abs=1e-12)

    # And at completion:
    articulation.tick_ship(ship, port.transition_seconds)
    for part, x in ((port, (-1.0, 0.45, -0.7)), (starboard, (1.0, 0.45, -0.7))):
        assert _tip(ship, part, x) == pytest.approx(
            part_pose.apply(part.pose_for("cruise"), x), abs=1e-12)
    assert not ship._articulation_transitions
