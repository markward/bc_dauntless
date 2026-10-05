"""Continuity: the window, lost track, scan glimpse and the ONE display answer
`sensor_contacts.shows_identity` (sensor continuity/occlusion spec, Continuity
and Re-identification).

Fixtures follow tests/unit/test_sensor_contacts.py::_world (current-game
player) and use tests/helpers/rocks.make_major_rock for line-of-sight blockers.
A ship is put "in a field" by monkeypatching
engine.rocks.far_tier.field_strength_at (sensor_media looks it up at call
time); a ship is put in the dense nebula core (hidden: `not can_detect`) by
monkeypatching sensor_detection.concealment_at. Rulings 1A/2A (Mark,
2026-10-05): only HIDDEN contacts run the lost-track clock -- cloak and a
medium alone never lose the track (a medium only changes the display).
Bridge.HelmMenuHandlers.ExitedSet is reached through the
`sensor_contacts._helm_exited_set` seam, which these tests replace with a
recorder; the real SDK call is proven in
tests/integration/test_sensor_continuity_science.py.
"""
import App
import pytest

from engine.appc import sensor_contacts, sensor_dials, unknown_labels
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.core.game import Game, _set_current_game
from engine.rocks import far_tier
from tests.helpers.rocks import make_major_rock

_exited_events: list = []


def _on_exited(dest, event):
    _exited_events.append(event.GetDestination())


@pytest.fixture(autouse=True)
def _clean():
    _exited_events.clear()
    yield
    _set_current_game(None)


@pytest.fixture
def helm(monkeypatch):
    calls = []
    monkeypatch.setattr(sensor_contacts, "_helm_exited_set", calls.append)
    return calls


def _world(base_range=2000.0):
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    return s, player, sensors


def _ship(s, name, x):
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    s.AddObjectToSet(ship, name)
    return ship


def _field(monkeypatch, target, strength):
    """Put *target* (only) in a field of the given strength; returns a dict
    whose "v" entry can be changed between ticks."""
    box = {"v": float(strength)}
    monkeypatch.setattr(far_tier, "field_strength_at",
                        lambda obj: box["v"] if obj is target else 0.0)
    return box


def _dense_core(monkeypatch, target):
    """Put *target* (only) in the dense nebula core: concealment 1.0 is above
    LOCK_BREAK_T, so can_detect fails (HIDDEN) and the medium reads Unknown."""
    from engine.appc import sensor_detection as sd
    monkeypatch.setattr(sd, "concealment_at",
                        lambda obj: 1.0 if obj is target else 0.0)


def _known_bird_behind_rock():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    rock = make_major_rock(s, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    return s, player, sensors, bird, rock


# ── the window ──────────────────────────────────────────────────────────────

def test_hidden_under_the_window_keeps_identity(helm):
    s, player, sensors, bird, rock = _known_bird_behind_rock()
    for t in (0.0, 1.0, 2.0, 3.0, 4.0):
        sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(bird) == 1, t
        assert sensor_contacts.is_concealed(player, bird) is True
    assert sensor_contacts.concealed_since(bird) == 0.0
    rock.SetTranslateXYZ(250.0, 500.0, 0.0)          # off the line, t=4.5
    sensor_contacts.tick(player, 5.0)
    assert sensors.IsObjectKnown(bird) == 1
    assert sensor_contacts.concealed_since(bird) is None
    assert helm == []


def test_hidden_for_the_window_loses_track_and_calls_helm_exitedset(helm):
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_EXITED_SET, None, __name__ + "._on_exited")
    s, player, sensors, bird, rock = _known_bird_behind_rock()
    for t in (0.0, 1.0, 2.0, 3.0, 4.0):
        sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(bird) == 1, t
    sensor_contacts.tick(player, 5.0)
    assert sensors.IsObjectKnown(bird) == 0
    assert sensor_contacts.concealed_since(bird) is None
    sensor_contacts.tick(player, 6.0)
    assert helm == [bird]                 # exactly once, with the contact
    assert _exited_events == []           # never a synthetic ET_EXITED_SET
    assert bird.GetContainingSet() is s   # still in the set


def test_window_is_a_dial(monkeypatch, helm):
    monkeypatch.setitem(sensor_dials._dials, "continuity_window_s", 2.0)
    s, player, sensors, bird, rock = _known_bird_behind_rock()
    sensor_contacts.tick(player, 0.0)
    sensor_contacts.tick(player, 1.0)
    assert sensors.IsObjectKnown(bird) == 1
    sensor_contacts.tick(player, 2.0)
    assert sensors.IsObjectKnown(bird) == 0
    assert helm == [bird]


def test_leaving_range_while_hidden_stops_the_clock(helm):
    s, player, sensors, bird, rock = _known_bird_behind_rock()
    sensor_contacts.tick(player, 0.0)
    sensor_contacts.tick(player, 1.0)
    assert sensor_contacts.concealed_since(bird) == 0.0
    bird.SetTranslateXYZ(9000.0, 0.0, 0.0)            # beyond 2000 GU range
    for t in (2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0):
        sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(bird) == 1, t
        assert sensor_contacts.concealed_since(bird) is None, t
    assert sensor_contacts.is_concealed(player, bird) is False
    assert helm == []


# ── unknown by medium ───────────────────────────────────────────────────────

def test_in_field_identified_ship_reads_unknown_then_named_again(monkeypatch, helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    field = _field(monkeypatch, bird, 1.0)
    sensor_contacts.tick(player, 0.0)
    assert sensor_contacts.shows_identity(bird, 0.0) is False
    assert sensors.IsObjectKnown(bird) == 1
    for t in (1.0, 2.0):
        sensor_contacts.tick(player, t)
        assert sensor_contacts.shows_identity(bird, t) is False
    field["v"] = 0.0
    sensor_contacts.tick(player, 3.0)
    assert sensor_contacts.shows_identity(bird, 3.0) is True
    assert sensors.IsObjectKnown(bird) == 1
    assert sensor_contacts.concealed_since(bird) is None
    assert helm == []


def test_in_field_for_20s_stays_known_and_displays_unknown(monkeypatch, helm):
    """Ruling 2A (Mark, 2026-10-05): a medium alone never loses the track --
    it only changes the display to Unknown. (Was: in a field for the window
    loses track.)"""
    from engine.appc import contact_index
    from engine.appc.perception import perceived_by
    contact_index.reset()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    _field(monkeypatch, bird, 1.0)
    for t in range(0, 21):
        sensor_contacts.tick(player, float(t))
        assert sensors.IsObjectKnown(bird) == 1, t
        assert sensor_contacts.shows_identity(bird, float(t)) is False, t
        assert sensor_contacts.concealed_since(bird) is None, t
    assert sensor_contacts.is_concealed(player, bird) is False
    assert helm == []
    # Listed, displays Unknown with no subsystems, identity kept.
    (c,) = [c for c in perceived_by(player) if c.ship is bird]
    assert c.perceivable is True and c.targetable is True
    assert c.identified is False
    assert c.subsystems_targetable is False


def test_in_dense_nebula_core_for_the_window_loses_track(monkeypatch, helm):
    """The dense core HIDES (not can_detect), so it still runs the clock."""
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    _dense_core(monkeypatch, bird)
    for t in (0.0, 1.0, 2.0, 3.0, 4.0):
        sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(bird) == 1, t
        assert sensor_contacts.is_concealed(player, bird) is True, t
    sensor_contacts.tick(player, 5.0)
    assert sensors.IsObjectKnown(bird) == 0
    assert helm == [bird]


# ── ruling 1A: cloak never starts the clock ─────────────────────────────────

def _cloaker(s, name, x):
    from engine.appc.subsystems import CloakingSubsystem
    ship = _ship(s, name, x)
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    return ship


def test_known_ship_cloaked_for_20s_stays_known_and_names_on_decloak(helm):
    from engine.appc import sensor_detection as sd
    s, player, sensors = _world()
    bird = _cloaker(s, "Bird", 1500.0)
    sensors.AddKnownObject(bird)
    bird.GetCloakingSubsystem().InstantCloak()
    assert sd.is_hidden_by_cloak(bird) is True
    assert sd.can_detect(player, bird) is False      # outside the cloak bubble
    for t in range(0, 21):
        sensor_contacts.tick(player, float(t))
        assert sensors.IsObjectKnown(bird) == 1, t
        assert sensor_contacts.concealed_since(bird) is None, t
    assert sensor_contacts.is_concealed(player, bird) is False
    assert helm == []
    bird.GetCloakingSubsystem().InstantDecloak()
    assert sensor_contacts.shows_identity(bird, 20.0) is True   # immediately
    sensor_contacts.tick(player, 20.5)
    assert sensor_contacts.shows_identity(bird, 20.5) is True
    assert helm == []


def test_no_passive_identification_inside_a_field(monkeypatch, helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)                   # near band (< 1000)
    _field(monkeypatch, bird, 1.0)
    for t in range(0, 11):
        sensor_contacts.tick(player, float(t))
        assert sensors.IsObjectKnown(bird) == 0, t
        assert sensor_contacts.is_pending(bird) is False, t


def test_no_passive_identification_behind_a_rock(helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    make_major_rock(s, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    for t in range(0, 11):
        sensor_contacts.tick(player, float(t))
    assert sensors.IsObjectKnown(bird) == 0


def test_passive_commit_drops_when_concealed_by_the_time_it_falls_due(monkeypatch, helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    field = _field(monkeypatch, bird, 0.0)
    sensor_contacts.tick(player, 0.0)
    assert sensor_contacts.is_pending(bird) is True   # armed in clear space
    field["v"] = 1.0                                  # drifts into a field
    sensor_contacts.tick(player, 4.0)
    assert sensors.IsObjectKnown(bird) == 0


# ── scans ───────────────────────────────────────────────────────────────────

def test_scan_in_field_gives_exactly_one_window_then_display_reverts(monkeypatch, helm):
    """Ruling 2A: after the glimpse the DISPLAY reverts to Unknown and the
    ship stays known (was: the track was lost at the window's end)."""
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    _field(monkeypatch, bird, 1.0)
    monkeypatch.setattr(sensor_contacts, "_now", lambda: 0.0)
    sensors.IdentifyObject(bird)                     # dwell 4.0 from t=0
    assert sensor_contacts.is_pending(bird) is True
    for t in (0.0, 1.0, 2.0, 3.0):
        sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(bird) == 0, t
    sensor_contacts.tick(player, 4.0)
    assert sensors.IsObjectKnown(bird) == 1
    assert sensor_contacts.shows_identity(bird, 4.0) is True
    assert sensor_contacts.concealed_since(bird) is None  # a medium runs no clock
    for t in (5.0, 6.0, 7.0, 8.0, 8.9):
        sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(bird) == 1, t
        assert sensor_contacts.shows_identity(bird, t) is True, t
    for t in (9.0, 10.0, 15.0, 30.0):                # scan time 4 + window 5
        sensor_contacts.tick(player, t)
        assert sensor_contacts.shows_identity(bird, t) is False, t
        assert sensors.IsObjectKnown(bird) == 1, t
    assert helm == []


def test_scan_glimpse_is_exactly_one_window_from_the_scan(monkeypatch, helm):
    """shows_identity's own window is measured from the scan commit to the
    instant asked about -- not rounded to a sweep (only lost track is)."""
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    _field(monkeypatch, bird, 1.0)
    sensor_contacts.tick(player, 0.0)
    sensor_contacts.schedule_scan(bird, 0.0, now_gt=0.5)
    sensor_contacts.tick(player, 0.5)                # commit, no sweep (next 1.0)
    assert sensors.IsObjectKnown(bird) == 1
    assert sensor_contacts.concealed_since(bird) is None  # a medium runs no clock
    assert sensor_contacts.shows_identity(bird, 5.4) is True
    assert sensor_contacts.shows_identity(bird, 5.5) is False
    sensor_contacts.tick(player, 6.0)
    assert sensors.IsObjectKnown(bird) == 1               # display only, ruling 2A
    assert helm == []


def test_scan_in_dense_core_gives_one_window_then_loses_track(monkeypatch, helm):
    """A HIDDEN contact's clock restarts from the scan: one window, then
    the track is lost (scans see through nebulae, only rocks block them)."""
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    _dense_core(monkeypatch, bird)
    sensor_contacts.tick(player, 0.0)
    sensor_contacts.schedule_scan(bird, 0.0, now_gt=0.5)
    sensor_contacts.tick(player, 0.5)
    assert sensors.IsObjectKnown(bird) == 1
    assert sensor_contacts.concealed_since(bird) == 0.5   # restarted AT the scan
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(bird) == 1, t
    sensor_contacts.tick(player, 6.0)                     # 0.5 + 5 elapsed
    assert sensors.IsObjectKnown(bird) == 0
    assert helm == [bird]


def test_scan_of_a_rock_blocked_target_does_nothing(monkeypatch, helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    make_major_rock(s, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    monkeypatch.setattr(sensor_contacts, "_now", lambda: 0.0)
    sensors.IdentifyObject(bird)
    assert sensor_contacts.is_pending(bird) is True
    for t in range(0, 8):
        sensor_contacts.tick(player, float(t))
    assert sensors.IsObjectKnown(bird) == 0
    assert sensor_contacts.is_pending(bird) is False      # dropped, not deferred
    assert sensor_contacts.shows_identity(bird, 7.0) is False


def test_scan_ignores_rocks_when_the_enhanced_contest_is_off(monkeypatch, helm):
    from engine.appc import sensor_detection
    monkeypatch.setattr(sensor_detection, "ENHANCED_SENSOR_CONTEST", False)
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 1500.0)                  # far band: no passive id
    make_major_rock(s, "Rock", at=(750.0, 0.0, 0.0), radius_gu=3.0)
    sensor_contacts.schedule_scan(bird, 4.0, now_gt=0.0)
    sensor_contacts.tick(player, 4.0)
    assert sensors.IsObjectKnown(bird) == 1


# ── one display answer, three readers ───────────────────────────────────────

def test_shows_identity_reads_the_passed_sensors_when_given(monkeypatch):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    other = SensorSubsystem("Other")
    other.AddKnownObject(bird)
    assert sensor_contacts.shows_identity(bird) is False            # player's
    assert sensor_contacts.shows_identity(bird, sensors=other) is True
    _field(monkeypatch, bird, 1.0)
    assert sensor_contacts.shows_identity(bird, sensors=other) is False


def test_list_reticle_and_science_agree_in_field(monkeypatch, helm):
    from engine.appc import contact_index, science_scan_labels
    from engine.appc.perception import perceived_by
    from engine.ui.reticle_text import build_reticle_text
    from tests.unit.test_reticle_text import _cam_facing_target

    contact_index.reset()
    unknown_labels.reset()
    s, player, sensors = _world()
    player.SetTranslateXYZ(0.0, -205.0, 0.0)         # reticle camera framing
    bird = _ship(s, "Bird", 0.0)
    bird.SetTranslateXYZ(0.0, 0.0, 0.0)
    sensors.AddKnownObject(bird)
    player.SetTarget(bird)

    # Clear space: every reader shows the real name.
    sensor_contacts.tick(player, 0.0)
    (c,) = [c for c in perceived_by(player) if c.ship is bird]
    assert c.identified is True
    assert build_reticle_text(player, _cam_facing_target(), (1280, 720))["name"] \
        == bird.GetDisplayName()
    assert science_scan_labels._unknown_label(bird) is None

    # Known bird enters a field: every reader shows the SAME placeholder.
    _field(monkeypatch, bird, 1.0)
    sensor_contacts.tick(player, 1.0)
    placeholder = unknown_labels.placeholder(bird)
    (c,) = [c for c in perceived_by(player) if c.ship is bird]
    assert c.identified is False
    assert c.subsystems_targetable is False
    out = build_reticle_text(player, _cam_facing_target(), (1280, 720))
    assert out["visible"] is True
    assert out["name"] == placeholder
    assert science_scan_labels._unknown_label(bird) == placeholder
    assert sensors.IsObjectKnown(bird) == 1          # identity kept, not shown


# ── state hygiene ───────────────────────────────────────────────────────────

def test_reset_and_exit_clear_continuity_state(monkeypatch, helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    _dense_core(monkeypatch, bird)
    sensor_contacts.schedule_scan(bird, 0.0, now_gt=0.0)
    sensor_contacts.tick(player, 0.0)
    assert sensor_contacts.concealed_since(bird) == 0.0
    assert bird in sensor_contacts._scanned_at
    assert bird in sensor_contacts._shown_real
    s.RemoveObjectFromSet("Bird")
    assert sensor_contacts.concealed_since(bird) is None
    assert bird not in sensor_contacts._scanned_at
    assert bird not in sensor_contacts._shown_real

    bird2 = _ship(s, "Bird2", 500.0)
    _dense_core(monkeypatch, bird2)
    sensor_contacts.schedule_scan(bird2, 0.0, now_gt=1.0)
    sensor_contacts.tick(player, 1.0)
    assert sensor_contacts.concealed_since(bird2) == 1.0
    sensor_contacts.reset()
    assert sensor_contacts.concealed_since(bird2) is None
    assert len(sensor_contacts._scanned_at) == 0
    assert len(sensor_contacts._shown_real) == 0


def test_player_swap_clears_continuity_state(monkeypatch, helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    _dense_core(monkeypatch, bird)
    sensor_contacts.schedule_scan(bird, 0.0, now_gt=0.0)
    sensor_contacts.tick(player, 0.0)
    assert sensor_contacts.concealed_since(bird) == 0.0
    other = ShipClass_Create("Galaxy")
    sensor_contacts.tick(other, 1.0)
    assert sensor_contacts.concealed_since(bird) is None
    assert len(sensor_contacts._scanned_at) == 0
    assert len(sensor_contacts._shown_real) == 0


# ── fix round 1, ruling 1: planets never lose track, never read Unknown ─────

def _planet(s, name, x):
    from engine.appc.planet import Planet_Create
    p = Planet_Create(90.0, "data/models/environment/planet.nif")
    p.SetTranslateXYZ(float(x), 0.0, 0.0)
    s.AddObjectToSet(p, name)
    return p


def test_known_planet_behind_a_rock_never_loses_track(monkeypatch, helm):
    from engine.appc import sensor_occlusion
    s, player, sensors = _world()
    haven = _planet(s, "Haven", 500.0)
    sensors.AddKnownObject(haven)
    make_major_rock(s, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(player, haven) is True   # really behind it
    for t in range(0, 11):
        sensor_contacts.tick(player, float(t))
        assert sensors.IsObjectKnown(haven) == 1, t
        assert sensor_contacts.concealed_since(haven) is None, t
    assert sensor_contacts.is_concealed(player, haven) is False
    assert helm == []                                        # Hail path untouched


def test_known_planet_in_a_medium_shows_identity_and_its_label_never_flips(monkeypatch, helm):
    from engine.appc import sensor_detection as sd
    s, player, sensors = _world()
    haven = _planet(s, "Haven", 500.0)
    sensors.AddKnownObject(haven)
    _field(monkeypatch, haven, 1.0)
    monkeypatch.setattr(sd, "concealment_at",
                        lambda obj: 0.2 if obj is haven else 0.0)   # moderate nebula
    renames = []
    monkeypatch.setattr(sensor_contacts, "_scan_menu", lambda: _RecordingMenu(renames))
    for t in range(0, 11):
        sensor_contacts.tick(player, float(t))
        assert sensor_contacts.shows_identity(haven, float(t)) is True, t
        assert sensors.IsObjectKnown(haven) == 1, t
    assert sensor_contacts._shown_real.get(haven) is True
    assert renames == []
    assert helm == []


class _RecordingMenu:
    def __init__(self, log):
        self._log = log

    def GetButtonW(self, label):
        return object()          # every label "has" a button: any flip would rename

    def RenameButton(self, old, new):
        self._log.append((old, new))


# ── fix round 1, ruling 2: rescanning a known ship in a medium ──────────────

_identified: list = []


def _on_identified(dest, event):
    _identified.append(event.GetDestination())


def test_rescan_armed_while_known_still_commits_after_the_track_is_lost(monkeypatch, helm):
    """Ruling 2A moved this from a field (which no longer loses the track) to
    the dense nebula core, which HIDES and so still runs the clock."""
    _identified.clear()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_SENSORS_SHIP_IDENTIFIED, None, __name__ + "._on_identified")
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    _dense_core(monkeypatch, bird)
    sensor_contacts.tick(player, 0.0)
    assert sensor_contacts.shows_identity(bird, 0.0) is False
    sensor_contacts.tick(player, 1.0)
    monkeypatch.setattr(sensor_contacts, "_now", lambda: 2.0)
    sensors.IdentifyObject(bird)                     # dwell 4.0 -> due t=6
    assert sensor_contacts.is_pending(bird) is True
    sensor_contacts.tick(player, 2.0)
    for t in (3.0, 4.0):
        sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(bird) == 1, t
        assert sensor_contacts.shows_identity(bird, t) is False, t
    # The clock from t=0 loses the track at t=5 -- a pending scan does not
    # stop it -- and the scan committing at t=6 then re-identifies the ship
    # through the ordinary path (one IDENTIFIED, for the re-identification).
    sensor_contacts.tick(player, 5.0)
    assert sensors.IsObjectKnown(bird) == 0
    sensor_contacts.tick(player, 6.0)
    assert sensors.IsObjectKnown(bird) == 1
    assert _identified == [bird]
    assert sensor_contacts.shows_identity(bird, 6.0) is True
    assert sensor_contacts.concealed_since(bird) == 6.0


def test_rescan_of_a_known_ship_restarts_the_glimpse_without_a_second_identified(monkeypatch, helm):
    """The ruling-2 timeline under ruling 2A: known in a field at t=0 reads
    Unknown and runs NO clock; scan at t=2 commits at t=6 with NO second
    IDENTIFIED; glimpse t=6..10.9; at t=11 the display reverts to Unknown
    and the ship stays known (was: lost at t=11)."""
    _identified.clear()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_SENSORS_SHIP_IDENTIFIED, None, __name__ + "._on_identified")
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    _field(monkeypatch, bird, 1.0)
    sensor_contacts.tick(player, 0.0)
    assert sensor_contacts.shows_identity(bird, 0.0) is False
    assert sensor_contacts.concealed_since(bird) is None
    monkeypatch.setattr(sensor_contacts, "_now", lambda: 2.0)
    sensors.IdentifyObject(bird)
    assert sensor_contacts.is_pending(bird) is True
    for t in (2.0, 3.0, 4.0, 5.0):
        sensor_contacts.tick(player, t)
        assert sensor_contacts.shows_identity(bird, t) is False, t
        assert sensors.IsObjectKnown(bird) == 1, t
    sensor_contacts.tick(player, 6.0)
    assert sensor_contacts._scanned_at.get(bird) == 6.0      # glimpse restarted
    for t in (6.0, 7.0, 8.0, 9.0, 10.0, 10.9):
        if t != 6.0:
            sensor_contacts.tick(player, t)
        assert sensors.IsObjectKnown(bird) == 1, t
        assert sensor_contacts.shows_identity(bird, t) is True, t
    assert _identified == []                                 # no re-fire
    sensor_contacts.tick(player, 11.0)
    assert sensor_contacts.shows_identity(bird, 11.0) is False
    assert sensors.IsObjectKnown(bird) == 1                  # display only
    assert helm == []


def test_scan_of_a_known_ship_that_shows_identity_stays_a_noop(helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    sensors.IdentifyObject(bird)
    assert sensor_contacts.is_pending(bird) is False


def test_rescan_of_a_known_ship_behind_a_rock_is_dropped(monkeypatch, helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    _field(monkeypatch, bird, 1.0)
    make_major_rock(s, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    sensor_contacts.schedule_scan(bird, 1.0, now_gt=0.0)
    assert sensor_contacts.is_pending(bird) is True
    sensor_contacts.tick(player, 1.0)
    assert bird not in sensor_contacts._scanned_at
    assert sensor_contacts.shows_identity(bird, 1.0) is False


def test_scan_in_clear_space_keeps_its_glimpse_into_a_medium(monkeypatch, helm):
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 1500.0)                  # far band: scan only
    field = _field(monkeypatch, bird, 0.0)
    sensor_contacts.schedule_scan(bird, 0.0, now_gt=0.0)
    sensor_contacts.tick(player, 0.0)
    assert sensors.IsObjectKnown(bird) == 1
    assert sensor_contacts.concealed_since(bird) is None
    field["v"] = 1.0                                 # drifts into a field at t=2
    sensor_contacts.tick(player, 2.0)
    assert sensor_contacts.shows_identity(bird, 2.0) is True
    assert sensor_contacts.shows_identity(bird, 4.9) is True
    assert sensor_contacts.shows_identity(bird, 5.0) is False   # window from the scan
