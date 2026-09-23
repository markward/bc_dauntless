"""Four alert states, and warp outranks all of them.

Warp wins because wing position is a FLIGHT configuration -- warp entry should
visibly re-configure the ship. NPCs never show 'yellow': BC never takes an NPC
off Red Alert (measured; stbc-oracle bible s13 N2), which is why NPC
articulation keys off 'has a target' rather than off alert level.
"""
import pytest

from engine.appc import articulation


class _Part:
    def __init__(self, angles):
        self._angles = angles
        self.pivot = (0.0, 0.0, 0.0)
        self.axis = (0.0, 1.0, 0.0)

    def GetName(self):
        return "left wing"

    def angle_for(self, state):
        return self._angles.get(state, 0.0)


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


def test_a_part_eases_toward_its_target_angle():
    part = _Part({"cruise": 45.0, "red": 0.0})
    a = articulation.ease_angle(0.0, 45.0, part_range=45.0, dt=1.0)
    assert 0.0 < a < 45.0
    assert articulation.ease_angle(a, 45.0, part_range=45.0, dt=10.0) == 45.0


def test_a_full_swing_takes_TRAVEL_SECONDS():
    """Each part eases at its own range / TRAVEL_SECONDS, so parts moving
    between the same two states stay in sync."""
    a = articulation.ease_angle(0.0, 45.0, part_range=45.0,
                                dt=articulation.TRAVEL_SECONDS)
    assert a == pytest.approx(45.0)


def test_an_interrupted_transition_just_changes_target():
    """No captured start pose, no from/to pair -- the part keeps easing from
    wherever it is. This is the case that makes per-part angles simpler than a
    normalised t."""
    a = articulation.ease_angle(0.0, 45.0, part_range=45.0, dt=1.0)
    back = articulation.ease_angle(a, 0.0, part_range=45.0, dt=1.0)
    assert back < a


def test_rotation_for_takes_DEGREES_not_a_deflection():
    """Signature change. rotation_for(part, 45.0) must mean 45 degrees, not
    45x the authored angle -- the old signature took a 0..1 scalar."""
    import math
    part = _Part({"cruise": 45.0})
    _pivot, _axis, theta = articulation.rotation_for(part, 45.0)
    assert theta == pytest.approx(math.radians(45.0))
