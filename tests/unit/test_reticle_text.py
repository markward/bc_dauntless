import math
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.subsystems import ShipSubsystem
from engine.ui.reticle_text import build_reticle_text, _ReticleCam


def _identity():
    R = TGMatrix3(); R.MakeIdentity(); return R


def _ship(loc, vel=(0.0, 0.0, 0.0), name="Target", radius=5.0, display_name=""):
    class _Ship:
        def __init__(self):
            self._t = None; self._sub = None
        def GetWorldLocation(self): return loc
        def GetWorldRotation(self): return _identity()
        def GetRadius(self): return radius
        def GetVelocity(self, space=0): return TGPoint3(*vel)
        def GetName(self): return name
        # Mirrors ObjectClass.GetDisplayName: localized label, falling back
        # to the internal name when none is set.
        def GetDisplayName(self): return display_name if display_name else name
        def GetTarget(self): return self._t
        def GetTargetSubsystem(self): return self._sub
    return _Ship()


def _cam_facing_target():
    # Eye at (0,-50,0) looking down +Y; a target at +Y is on-screen.
    return _ReticleCam(eye=(0.0, -50.0, 0.0), target=(0.0, 0.0, 0.0),
                       up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(60.0),
                       near=1.0, far=5000.0)


def test_text_hidden_without_target():
    p = _ship(TGPoint3(0, 0, 0))
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["visible"] is False


def test_text_name_and_line2_from_ship():
    # Target 205 GU ahead with radius 5 → surface distance 200 GU (BC's
    # readout is to the bounding sphere). 200*0.175 = 35.00 km; 1*630 = 630 kph.
    tgt = _ship(TGPoint3(0, 0, 0), vel=(1.0, 0.0, 0.0), name="Warbird")
    p = _ship(TGPoint3(0, -205, 0)); p._t = tgt
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["visible"] is True
    assert out["name"] == "Warbird"
    assert out["line2"] == "35.00 km / 630 kph"
    assert 0 <= out["name_xy"][0] <= 1280 and 0 <= out["name_xy"][1] <= 720


def test_range_is_surface_distance_for_planet():
    """BC's readout convention, confirmed live: orbiting Haven (radius
    90 GU) at the authored radius+150 GU CircleObject band, the original
    game reads ~25 km — the SURFACE distance (150 GU = 26.25 km), while a
    centre-distance readout would claim 42 km."""
    haven = _ship(TGPoint3(0, 0, 0), name="Haven", radius=90.0)
    p = _ship(TGPoint3(0, -240, 0)); p._t = haven   # orbit: 240 GU centres
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["line2"].startswith("26.25 km")


def test_text_name_is_subsystem_when_locked():
    tgt = _ship(TGPoint3(0, 0, 0), name="Warbird")
    sub = ShipSubsystem("Port Nacelle"); sub.SetParentShip(tgt)
    p = _ship(TGPoint3(0, -200, 0)); p._t = tgt; p._sub = sub
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["name"] == "Port Nacelle"


def test_text_name_is_target_display_name():
    # The reticle label must match the rest of the UI (Hail menu, target
    # list), which reads GetDisplayName — Haven's internal name is "Haven"
    # but its localized label is "Vesuvi 6 - Haven".
    tgt = _ship(TGPoint3(0, 0, 0), name="Haven", display_name="Vesuvi 6 - Haven")
    p = _ship(TGPoint3(0, -200, 0)); p._t = tgt
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["name"] == "Vesuvi 6 - Haven"


def test_text_name_is_subsystem_display_name():
    # The subsystem branch also reads GetDisplayName. A stock ShipSubsystem's
    # display name equals its internal name, so distinguish them via an
    # in-test subclass.
    class _LocalizedSub(ShipSubsystem):
        def GetDisplayName(self):
            return "Port Nacelle"
    tgt = _ship(TGPoint3(0, 0, 0), name="Warbird")
    sub = _LocalizedSub("sub_key"); sub.SetParentShip(tgt)
    p = _ship(TGPoint3(0, -200, 0)); p._t = tgt; p._sub = sub
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["name"] == "Port Nacelle"


def test_text_name_falls_back_to_internal_name():
    # A target with no display name set still labels with _name — never blank.
    tgt = _ship(TGPoint3(0, 0, 0), name="Warbird")
    p = _ship(TGPoint3(0, -200, 0)); p._t = tgt
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["name"] == "Warbird"


def test_text_hidden_when_target_behind_camera():
    tgt = _ship(TGPoint3(0, -500, 0), name="Warbird")
    p = _ship(TGPoint3(0, -400, 0)); p._t = tgt
    cam = _ReticleCam(eye=(0.0, 0.0, 0.0), target=(0.0, 100.0, 0.0),
                      up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(60.0),
                      near=1.0, far=5000.0)
    out = build_reticle_text(p, cam, (1280, 720))
    assert out["visible"] is False


# ── Roadmap decision 5 (no name leaks): an unidentified ship-level target
# must read the same "Unknown N" placeholder the target list shows, not its
# real name, until the player's sensors identify it. Uses the REAL
# sensor_contacts/unknown_labels machinery (not the bare `_ship()` stand-in
# above, which is not a ShipClass and so is deliberately unaffected). ──

def _identified_world():
    from engine.appc.ships import ShipClass_Create
    from engine.appc.subsystems import SensorSubsystem
    from engine.core.game import Game, _set_current_game
    from engine.appc import unknown_labels
    unknown_labels.reset()
    player = ShipClass_Create("Galaxy")
    player.SetTranslateXYZ(0.0, -205.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(2000.0)
    player.SetSensorSubsystem(sensors)
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    target = ShipClass_Create("BirdOfPrey")
    target.SetName("Warbird")
    target.SetTranslateXYZ(0.0, 0.0, 0.0)
    player.SetTarget(target)
    return player, sensors, target


def test_unknown_ship_target_shows_the_list_placeholder():
    from engine.core.game import _set_current_game
    from engine.appc import unknown_labels
    player, sensors, target = _identified_world()
    try:
        expected = unknown_labels.placeholder(target)   # same number the list would show
        out = build_reticle_text(player, _cam_facing_target(), (1280, 720))
        assert out["visible"] is True
        assert out["name"] == expected
        assert out["name"].startswith("Unknown ")
        assert out["name"] != target.GetDisplayName()
    finally:
        _set_current_game(None)
        unknown_labels.reset()


def test_identified_ship_target_shows_its_real_name():
    from engine.core.game import _set_current_game
    from engine.appc import unknown_labels
    player, sensors, target = _identified_world()
    try:
        sensors.AddKnownObject(target)
        out = build_reticle_text(player, _cam_facing_target(), (1280, 720))
        assert out["visible"] is True
        assert out["name"] == target.GetDisplayName()
    finally:
        _set_current_game(None)
        unknown_labels.reset()


def test_planet_target_is_unaffected_and_shows_its_real_name():
    from engine.appc.planet import Planet_Create
    from engine.appc.ships import ShipClass_Create
    from engine.core.game import _set_current_game
    from engine.appc import unknown_labels
    unknown_labels.reset()
    player = ShipClass_Create("Galaxy")
    player.SetTranslateXYZ(0.0, -240.0, 0.0)
    haven = Planet_Create(90.0, "data/models/environment/planet.nif")
    haven.SetTranslateXYZ(0.0, 0.0, 0.0)
    player.SetTarget(haven)
    # Deliberately NOT a current-game player with sensors: planets/placements
    # have no Unknown row (set_contacts only allocates one for ShipClass
    # contacts), so this must never call into sensor_contacts at all.
    try:
        out = build_reticle_text(player, _cam_facing_target(), (1280, 720))
        assert out["visible"] is True
        assert out["name"] == haven.GetDisplayName()
    finally:
        _set_current_game(None)
