import App
from engine.appc.sets import SetClass_Create


def _obj_at(x, y, z):
    o = App.ShipClass_Create(); o.SetName("o")
    o.SetTranslateXYZ(x, y, z); o.Update(0)
    return o


def _make_nebula():
    n = App.MetaNebula_Create(
        155.0 / 255.0, 90.0 / 255.0, 185.0 / 255.0,
        145.0, 10.5,
        "data/Backgrounds/nebulaoverlay.tga",
        "data/Backgrounds/nebulaexternal.tga",
    )
    n.SetupDamage(150.0, 20.0)
    n.AddNebulaSphere(0.0, 1500.0, 0.0, 1500.0)
    return n


def test_metanebula_getters_return_constructor_values():
    n = _make_nebula()
    r, g, b = n.GetTintRGB()
    assert abs(r - 155.0 / 255.0) < 1e-6
    assert abs(g - 90.0 / 255.0) < 1e-6
    assert abs(b - 185.0 / 255.0) < 1e-6
    assert n.GetVisibility() == 145.0
    assert n.GetSensorDensity() == 10.5
    assert n.GetInternalTexture() == "data/Backgrounds/nebulaoverlay.tga"
    assert n.GetExternalTexture() == "data/Backgrounds/nebulaexternal.tga"
    assert n.GetDamage() == (150.0, 20.0)


def test_metanebula_cast_accepts_nebula_rejects_other():
    n = _make_nebula()
    assert App.MetaNebula_Cast(n) is n
    assert App.MetaNebula_Cast(object()) is None
    assert App.MetaNebula_Cast(None) is None


def test_point_in_sphere_membership():
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "i.tga", "e.tga")
    neb.AddNebulaSphere(0.0, 0.0, 0.0, 100.0)
    assert neb.IsObjectInNebula(_obj_at(10.0, 0.0, 0.0))   # inside
    assert not neb.IsObjectInNebula(_obj_at(200.0, 0.0, 0.0))  # outside


def test_multi_sphere():
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "i.tga", "e.tga")
    neb.AddNebulaSphere(0.0, 0.0, 0.0, 50.0)
    neb.AddNebulaSphere(500.0, 0.0, 0.0, 50.0)
    assert neb.IsObjectInNebula(_obj_at(490.0, 0.0, 0.0))   # inside 2nd
    assert not neb.IsObjectInNebula(_obj_at(250.0, 0.0, 0.0))  # between


def test_get_nebula_and_class_list():
    App.g_kSetManager._sets.clear()
    s = SetClass_Create(); App.g_kSetManager.AddSet(s, "N")
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "i.tga", "e.tga")
    s.AddObjectToSet(neb, "neb")
    assert s.GetNebula() is neb
    assert neb in s.GetClassObjectList(App.CT_NEBULA)


from engine.appc.nebula_runtime import NebulaTracker


class _FakeShip:
    def __init__(self, name, x, y, z):
        self._name = name
        self._x, self._y, self._z = x, y, z

    def GetName(self):
        return self._name

    def move_to(self, x, y, z):
        self._x, self._y, self._z = x, y, z

    def GetWorldLocation(self):
        import App
        return App.TGPoint3(self._x, self._y, self._z)


class _EventSink:
    """Broadcast listener that records (event_type, source_name, dest_name)."""
    def __init__(self):
        self.events = []

    def record_enter(self, evt):
        self.events.append(("enter", evt.GetSource().GetName(),
                            evt.GetDestination().GetName()))

    def record_exit(self, evt):
        self.events.append(("exit", evt.GetSource().GetName(),
                            evt.GetDestination().GetName()))


def _set_with_nebula():
    import App
    s = App.SetClass_Create()
    n = _make_nebula()                       # sphere at (0,1500,0) r=1500
    s.AddObjectToSet(n, "neb")
    return s, n


def test_tracker_fires_enter_then_exit_once_per_transition():
    import App
    s, n = _set_with_nebula()
    sink = _EventSink()
    w = App.TGPythonInstanceWrapper()
    w.SetPyWrapper(sink)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_ENTERED_NEBULA, w, "record_enter")
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_EXITED_NEBULA, w, "record_exit")

    ship = _FakeShip("Player", 0.0, 5000.0, 0.0)   # far outside
    tracker = NebulaTracker()

    tracker.update(s, [ship], 1.0)                 # outside → no event
    assert sink.events == []

    ship.move_to(0.0, 1500.0, 0.0)                 # centre → enter
    tracker.update(s, [ship], 1.0)
    assert sink.events == [("enter", "neb", "Player")]

    tracker.update(s, [ship], 1.0)                 # still inside → no repeat
    assert sink.events == [("enter", "neb", "Player")]

    ship.move_to(0.0, 5000.0, 0.0)                 # leave → exit
    tracker.update(s, [ship], 1.0)
    assert sink.events == [("enter", "neb", "Player"),
                           ("exit", "neb", "Player")]


def test_tracker_reset_clears_membership():
    import App
    s, n = _set_with_nebula()
    ship = _FakeShip("Player", 0.0, 1500.0, 0.0)
    tracker = NebulaTracker()
    tracker.update(s, [ship], 1.0)                 # now inside
    tracker.reset()
    sink = _EventSink()
    w = App.TGPythonInstanceWrapper()
    w.SetPyWrapper(sink)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_EXITED_NEBULA, w, "record_exit")
    # After reset, an inside ship is treated as "newly seen": staying inside
    # fires a fresh ENTER, never a spurious EXIT.
    tracker.update(s, [ship], 1.0)
    assert all(e[0] != "exit" for e in sink.events)


class _FakeHull:
    def __init__(self, cond):
        self._c = cond

    def GetCondition(self):
        return self._c

    def SetCondition(self, v):
        self._c = v


class _FakeShields:
    NUM_SHIELDS = 6

    def __init__(self, per_face):
        self._f = [per_face] * self.NUM_SHIELDS

    def GetCurrentShields(self, face):
        return self._f[int(face)]

    def SetCurrentShields(self, face, v):
        self._f[int(face)] = v


class _FakeSensor:
    def __init__(self, base):
        self._b = base

    def GetBaseSensorRange(self):
        return self._b

    def SetBaseSensorRange(self, v):
        self._b = v


class _DamageableShip(_FakeShip):
    def __init__(self, name, x, y, z, hull=1000.0, shield=500.0, sensor=2000.0):
        super().__init__(name, x, y, z)
        self._hull = _FakeHull(hull)
        self._shield = _FakeShields(shield)
        self._sensor = _FakeSensor(sensor)
        self._handlers = {}        # event_type -> [qualified_name]

    def GetHull(self):
        return self._hull

    def GetShieldSubsystem(self):
        return self._shield

    def GetSensorSubsystem(self):
        return self._sensor

    def AddPythonFuncHandlerForInstance(self, event_type, qualified_name):
        self._handlers.setdefault(event_type, []).append(qualified_name)


def test_environmental_damage_drains_hull_and_shields():
    import App
    s, n = _set_with_nebula()      # SetupDamage(150, 20)
    ship = _DamageableShip("P", 0.0, 1500.0, 0.0, hull=1000.0, shield=500.0)
    tracker = NebulaTracker()
    tracker.update(s, [ship], 2.0)             # 2 s tick
    assert ship.GetHull().GetCondition() == 1000.0 - 150.0 * 2.0
    # 20/s * 2 s = 40 total, spread across 6 faces.
    assert abs(ship.GetShieldSubsystem().GetCurrentShields(0)
               - (500.0 - 40.0 / 6.0)) < 1e-6


def test_environmental_damage_floors_at_zero():
    import App
    s, n = _set_with_nebula()
    ship = _DamageableShip("P", 0.0, 1500.0, 0.0, hull=100.0, shield=1.0)
    tracker = NebulaTracker()
    tracker.update(s, [ship], 10.0)            # huge tick
    assert ship.GetHull().GetCondition() == 0.0
    assert ship.GetShieldSubsystem().GetCurrentShields(0) == 0.0


def test_ignore_event_opt_out_takes_no_damage():
    import App
    s, n = _set_with_nebula()
    ship = _DamageableShip("Rock", 0.0, 1500.0, 0.0, hull=1000.0)
    ship.AddPythonFuncHandlerForInstance(
        App.ET_ENVIRONMENT_DAMAGE, "MissionLib.IgnoreEvent")
    tracker = NebulaTracker()
    tracker.update(s, [ship], 2.0)
    assert ship.GetHull().GetCondition() == 1000.0
    assert ship.GetShieldSubsystem().GetCurrentShields(0) == 500.0


def test_sensor_range_scaled_on_enter_restored_on_exit():
    import App
    # Build a nebula with sensor_density 0.25 (in range).
    s = App.SetClass_Create()
    n = App.MetaNebula_Create(0.1, 0.1, 0.1, 100.0, 0.25,
                              "i.tga", "e.tga")
    n.SetupDamage(0.0, 0.0)
    n.AddNebulaSphere(0.0, 0.0, 0.0, 100.0)
    s.AddObjectToSet(n, "neb")
    ship = _DamageableShip("P", 0.0, 0.0, 0.0, sensor=2000.0)
    tracker = NebulaTracker()
    tracker.update(s, [ship], 1.0)             # enter
    assert ship.GetSensorSubsystem().GetBaseSensorRange() == 2000.0 * 0.25
    ship.move_to(0.0, 5000.0, 0.0)
    tracker.update(s, [ship], 1.0)             # exit
    assert ship.GetSensorSubsystem().GetBaseSensorRange() == 2000.0


def test_sensor_density_out_of_range_clamps_to_one():
    import App
    s, n = _set_with_nebula()                  # sensor_density 10.5
    ship = _DamageableShip("P", 0.0, 1500.0, 0.0, sensor=2000.0)
    tracker = NebulaTracker()
    tracker.update(s, [ship], 1.0)
    assert ship.GetSensorSubsystem().GetBaseSensorRange() == 2000.0
