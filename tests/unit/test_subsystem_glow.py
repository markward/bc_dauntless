from engine.appc import subsystem_glow as sg


class _Sub:
    def __init__(self, disabled=False, destroyed=False):
        self._disabled, self._destroyed = disabled, destroyed
    def IsDisabled(self):
        return self._disabled
    def IsDestroyed(self):
        return self._destroyed


def test_glow_state_classifies_all_cases():
    assert sg.glow_state(None) == sg.HEALTHY
    assert sg.glow_state(_Sub()) == sg.HEALTHY
    assert sg.glow_state(_Sub(disabled=True)) == sg.DISABLED
    assert sg.glow_state(_Sub(destroyed=True)) == sg.DESTROYED
    # destroyed dominates even if also flagged disabled
    assert sg.glow_state(_Sub(disabled=True, destroyed=True)) == sg.DESTROYED


def test_dim_and_flicker_per_state():
    assert sg.dim_and_flicker(sg.HEALTHY) == (1.0, 0.0)
    assert sg.dim_and_flicker(sg.DISABLED) == (0.0, 1.0)
    assert sg.dim_and_flicker(sg.DESTROYED) == (0.0, 0.0)


def test_glow_edge_tracks_state_changes():
    # healthy -> -1
    assert sg.glow_edge(sg.HEALTHY, sg.HEALTHY, -1.0, 10.0) == -1.0
    # healthy -> disabled stamps now
    assert sg.glow_edge(sg.HEALTHY, sg.DISABLED, -1.0, 10.0) == 10.0
    # still disabled keeps stamp
    assert sg.glow_edge(sg.DISABLED, sg.DISABLED, 10.0, 12.0) == 10.0
    # disabled -> destroyed re-stamps (fresh blow-out)
    assert sg.glow_edge(sg.DISABLED, sg.DESTROYED, 10.0, 15.0) == 15.0
    # still destroyed keeps stamp
    assert sg.glow_edge(sg.DESTROYED, sg.DESTROYED, 15.0, 20.0) == 15.0
    # repaired -> clear
    assert sg.glow_edge(sg.DESTROYED, sg.HEALTHY, 15.0, 25.0) == -1.0


def test_warp_pods_children_then_aggregator_then_empty():
    class _Agg:
        def __init__(self, kids):
            self._kids = kids
        def GetNumChildSubsystems(self):
            return len(self._kids)
        def GetChildSubsystem(self, i):
            return self._kids[i]
    kids = ["port", "star"]
    assert sg.warp_pods(_Agg(kids)) == kids
    agg = _Agg([])
    assert sg.warp_pods(agg) == [agg]
    assert sg.warp_pods(None) == []


class _Point:
    def __init__(self, x, y, z):
        self._x, self._y, self._z = x, y, z
    def GetX(self): return self._x
    def GetY(self): return self._y
    def GetZ(self): return self._z


class _Pod:
    def __init__(self, pos, radius=2.0):
        self._pos, self._radius = pos, radius
        self.disabled = self.destroyed = False
    def GetPosition(self): return self._pos
    def GetRadius(self): return self._radius
    def IsDisabled(self): return self.disabled
    def IsDestroyed(self): return self.destroyed


class _WarpAgg:
    def __init__(self, kids): self._kids = kids
    def GetNumChildSubsystems(self): return len(self._kids)
    def GetChildSubsystem(self, i): return self._kids[i]


class _Ship:
    def __init__(self, warp, impulse, sensor):
        self._warp, self._impulse, self._sensor = warp, impulse, sensor
    def GetWarpEngineSubsystem(self): return self._warp
    def GetImpulseEngineSubsystem(self): return self._impulse
    def GetSensorSubsystem(self): return self._sensor


class _FakeRenderer:
    def __init__(self, results):
        self._results = list(results)
        self.capsule_calls = []
        self.sphere_calls = []
        self.dim_calls = []
    def compute_capsule_region(self, iid, center, axis, radius):
        self.capsule_calls.append((iid, center, axis, radius))
        return self._results.pop(0)
    def add_sphere_region(self, iid, center, radius):
        self.sphere_calls.append((iid, center, radius))
        return self._results.pop(0)
    def set_glow_region_dim(self, iid, idx, dim_target, edge_time, flicker):
        self.dim_calls.append((iid, idx, dim_target, edge_time, flicker))


def test_controller_registers_capsule_for_warp_and_spheres_for_impulse_sensor():
    warp = _WarpAgg([_Pod(_Point(-3.0, 1.0, 0.0))])
    impulse = _Pod(_Point(0.0, -0.98, -0.45), radius=0.25)
    sensor = _Pod(_Point(0.0, -0.45, -0.5), radius=0.28)
    ship = _Ship(warp, impulse, sensor)
    rend = _FakeRenderer(results=[0, 1, 2])  # capsule, impulse sphere, sensor sphere

    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)

    assert rend.capsule_calls == [(7, (-3.0, 1.0, 0.0), sg.WARP_AXIS, 2.0)]
    assert rend.sphere_calls == [
        (7, (0.0, -0.98, -0.45), 0.25),
        (7, (0.0, -0.45, -0.5), 0.28),
    ]
    assert len(ctrl._regions) == 3


def test_controller_drives_three_state_across_edges():
    impulse = _Pod(_Point(0.0, -0.98, -0.45), radius=0.25)
    ship = _Ship(warp=None, impulse=impulse, sensor=None)
    rend = _FakeRenderer(results=[0])  # only the impulse sphere registers
    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    assert len(ctrl._regions) == 1

    # healthy -> full, edge -1, flicker 0
    ctrl.update(now=10.0)
    assert rend.dim_calls[-1] == (7, 0, 1.0, -1.0, 0.0)

    # disabled -> dim 0, edge stamps 20, flicker 1
    impulse.disabled = True
    ctrl.update(now=20.0)
    assert rend.dim_calls[-1] == (7, 0, 0.0, 20.0, 1.0)

    # still disabled -> keep stamp 20
    ctrl.update(now=25.0)
    assert rend.dim_calls[-1] == (7, 0, 0.0, 20.0, 1.0)

    # destroyed -> dim 0, edge re-stamps 30, flicker 0
    impulse.disabled, impulse.destroyed = False, True
    ctrl.update(now=30.0)
    assert rend.dim_calls[-1] == (7, 0, 0.0, 30.0, 0.0)

    # repaired -> full, edge -1, flicker 0
    impulse.destroyed = False
    ctrl.update(now=40.0)
    assert rend.dim_calls[-1] == (7, 0, 1.0, -1.0, 0.0)
