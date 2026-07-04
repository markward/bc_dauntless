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


def test_impulse_engines_children_then_aggregator_then_empty():
    class _Agg:
        def __init__(self, kids): self._kids = kids
        def GetNumChildSubsystems(self): return len(self._kids)
        def GetChildSubsystem(self, i): return self._kids[i]
    kids = ["port", "star", "center"]
    assert sg.impulse_engines(_Agg(kids)) == kids
    agg = _Agg([])
    assert sg.impulse_engines(agg) == [agg]  # no children -> the parent itself
    assert sg.impulse_engines(None) == []


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
    """Leaf pod. By default carries the standard baked aft-cylinder glow
    region (mirroring the tools/bake_impulse_glow.py section every stock ship
    has) — impulse glow ONLY comes from baked hardpoint data now. Pass
    baked=False for a pod whose hardpoint bakes nothing (=> no impulse glow).
    Warp/sensor paths never consult GetProperty."""
    def __init__(self, pos, radius=2.0, baked=True):
        self._pos, self._radius = pos, radius
        self._baked = baked
        self.disabled = self.destroyed = False
    def GetPosition(self): return self._pos
    def GetRadius(self): return self._radius
    def IsDisabled(self): return self.disabled
    def IsDestroyed(self): return self.destroyed
    def GetNumChildSubsystems(self): return 0  # leaf; impulse_engines -> [self]
    def GetName(self): return "pod"
    def GetProperty(self):
        if not self._baked:
            return None
        from engine.appc.properties import EngineProperty
        prop = EngineProperty("pod")
        prop.SetGlowRegionShape(0, "Cylinder")
        prop.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        prop.SetGlowRegionRadius(0, self._radius)
        prop.SetGlowRegionExtent(0, 0.0, 2.0)
        return prop


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
        self.cylinder_calls = []
        self.dim_calls = []
        self.gain_calls = []
    def compute_capsule_region(self, iid, center, axis, radius):
        self.capsule_calls.append((iid, center, axis, radius))
        return self._results.pop(0)
    def add_sphere_region(self, iid, center, radius):
        self.sphere_calls.append((iid, center, radius))
        return self._results.pop(0)
    def add_cylinder_region(self, iid, center, axis, radius, length):
        self.cylinder_calls.append((iid, center, axis, radius, length))
        return self._results.pop(0)
    def set_glow_region_dim(self, iid, idx, dim_target, edge_time, flicker):
        self.dim_calls.append((iid, idx, dim_target, edge_time, flicker))
    def set_glow_region_gain(self, iid, idx, gain, gate_axis=(0.0, 0.0, 0.0)):
        self.gain_calls.append((iid, idx, gain, gate_axis))


def test_controller_registers_capsule_warp_cylinder_impulse_sphere_sensor():
    warp = _WarpAgg([_Pod(_Point(-3.0, 1.0, 0.0))])
    impulse = _Pod(_Point(0.0, -0.98, -0.45), radius=0.25)
    sensor = _Pod(_Point(0.0, -0.45, -0.5), radius=0.28)
    ship = _Ship(warp, impulse, sensor)
    rend = _FakeRenderer(results=[0, 1, 2])  # capsule, impulse cylinder, sensor sphere

    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)

    assert rend.capsule_calls == [(7, (-3.0, 1.0, 0.0), sg.WARP_AXIS, 2.0)]
    # Impulse -> the pod's BAKED aft-running cylinder; sensor -> plain sphere.
    assert rend.cylinder_calls == [
        (7, (0.0, -0.98, -0.45), sg.IMPULSE_AFT_AXIS, 0.25, 2.0),
    ]
    assert rend.sphere_calls == [(7, (0.0, -0.45, -0.5), 0.28)]
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


# ── impulse power/speed scaling + slow pulse ────────────────────────────────

class _ImpulseSub(_Pod):
    """Impulse sub with a power switch and a max speed (for AI frac)."""
    def __init__(self, pos, radius=0.25, on=True, max_speed=10.0):
        super().__init__(pos, radius)
        self._on, self._max_speed = on, max_speed
    def IsOn(self): return self._on
    def GetMaxSpeed(self): return self._max_speed


class _AIShip(_Ship):
    """Ship exposing an AI speed setpoint (no player throttle override)."""
    def __init__(self, warp, impulse, sensor, setpoint=None):
        super().__init__(warp, impulse, sensor)
        self._setpoint = setpoint
    def GetSpeedSetpoint(self): return self._setpoint


def test_commanded_impulse_frac_override_wins_and_clamps():
    ship = _Ship(warp=None, impulse=None, sensor=None)
    assert sg.commanded_impulse_frac(ship, 0.5) == 0.5
    assert sg.commanded_impulse_frac(ship, 2.0) == 1.0   # clamped high
    assert sg.commanded_impulse_frac(ship, -1.0) == 0.0  # clamped low


def test_commanded_impulse_frac_from_ai_setpoint():
    impulse = _ImpulseSub(_Point(0.0, 0.0, 0.0), max_speed=10.0)
    # commanded 5 / max 10 -> 0.5; direction/frame slots ignored
    ship = _AIShip(None, impulse, None, setpoint=(5.0, (0, 1, 0), 0))
    assert sg.commanded_impulse_frac(ship) == 0.5
    # over max clamps to 1.0; reverse (negative) uses magnitude
    ship._setpoint = (25.0, (0, 1, 0), 0)
    assert sg.commanded_impulse_frac(ship) == 1.0
    ship._setpoint = (-5.0, (0, -1, 0), 0)
    assert sg.commanded_impulse_frac(ship) == 0.5


def test_commanded_impulse_frac_missing_or_zero_max_is_zero():
    # no setpoint, no override -> 0
    ship = _AIShip(None, _ImpulseSub(_Point(0, 0, 0)), None, setpoint=None)
    assert sg.commanded_impulse_frac(ship) == 0.0
    # zero max speed -> no divide-by-zero, 0
    ship2 = _AIShip(None, _ImpulseSub(_Point(0, 0, 0), max_speed=0.0), None,
                    setpoint=(5.0, (0, 1, 0), 0))
    assert sg.commanded_impulse_frac(ship2) == 0.0


def test_impulse_gain_ramps_idle_to_max_when_powered():
    # now=0 -> sin term is 0, so gain == base (no pulse contribution)
    assert sg.impulse_gain(0.0, 0.0, powered=True) == sg.GAIN_IDLE
    assert sg.impulse_gain(1.0, 0.0, powered=True) == sg.GAIN_MAX
    mid = sg.impulse_gain(0.5, 0.0, powered=True)
    assert sg.GAIN_IDLE < mid < sg.GAIN_MAX


def test_impulse_gain_unpowered_is_exactly_one():
    # unpowered / disabled / destroyed never boost, at any throttle or phase
    for now in (0.0, 1.3, 7.7):
        for frac in (0.0, 0.5, 1.0):
            assert sg.impulse_gain(frac, now, powered=False) == 1.0


def test_impulse_gain_pulse_bounded_and_steady_at_rest():
    # at rest (frac 0) the pulse amplitude is 0 -> perfectly steady
    for now in (0.0, 0.6, 1.25, 3.3):
        assert sg.impulse_gain(0.0, now, powered=True) == sg.GAIN_IDLE
    # under way the gain stays within base*(1 +/- amp) across a phase sweep
    frac = 1.0
    base = sg.GAIN_IDLE + (sg.GAIN_MAX - sg.GAIN_IDLE) * frac
    amp = sg.PULSE_AMP * frac
    lo, hi = base * (1.0 - amp), base * (1.0 + amp)
    for k in range(40):
        now = k * 0.1
        g = sg.impulse_gain(frac, now, powered=True)
        assert lo - 1e-9 <= g <= hi + 1e-9


def test_controller_pushes_gain_only_for_impulse_region():
    warp = _WarpAgg([_Pod(_Point(-3.0, 1.0, 0.0))])
    impulse = _ImpulseSub(_Point(0.0, -0.98, -0.45), on=True, max_speed=10.0)
    sensor = _Pod(_Point(0.0, -0.45, -0.5), radius=0.28)
    ship = _AIShip(warp, impulse, sensor, setpoint=(10.0, (0, 1, 0), 0))
    rend = _FakeRenderer(results=[0, 1, 2])  # capsule, impulse sphere, sensor sphere

    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    ctrl.update(now=0.0)

    # exactly one gain push, on the impulse region index (1), at full throttle,
    # gated to the aft axis so only exhaust faces brighten
    assert len(rend.gain_calls) == 1
    iid, idx, gain, gate = rend.gain_calls[0]
    assert (iid, idx) == (7, 1)
    assert abs(gain - sg.GAIN_MAX) < 1e-9
    assert gate == sg.IMPULSE_AFT_AXIS


def test_controller_boost_ignores_ison_flag():
    # ImpulseEngineSubsystem.IsOn() is always False in practice, so the boost
    # must NOT depend on it: a healthy engine at full throttle still brightens.
    impulse = _ImpulseSub(_Point(0.0, -0.98, -0.45), on=False, max_speed=10.0)
    ship = _AIShip(None, impulse, None, setpoint=(10.0, (0, 1, 0), 0))
    rend = _FakeRenderer(results=[0])
    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    ctrl.update(now=0.0)
    iid, idx, gain, _gate = rend.gain_calls[0]
    assert (iid, idx) == (7, 0)
    assert abs(gain - sg.GAIN_MAX) < 1e-9


def test_controller_registers_boost_region_per_impulse_pod():
    class _ImpAgg:
        # Parent category node: holds max speed; pods are its children.
        def __init__(self, kids): self._kids = kids
        def GetNumChildSubsystems(self): return len(self._kids)
        def GetChildSubsystem(self, i): return self._kids[i]
        def GetMaxSpeed(self): return 10.0
    port = _ImpulseSub(_Point(-1.22, -0.20, 0.32), max_speed=10.0)
    star = _ImpulseSub(_Point(1.22, -0.20, 0.32), max_speed=10.0)
    center = _ImpulseSub(_Point(0.0, -1.10, -0.08), max_speed=10.0)
    impulse = _ImpAgg([port, star, center])
    ship = _AIShip(None, impulse, None, setpoint=(10.0, (0, 1, 0), 0))
    rend = _FakeRenderer(results=[0, 1, 2])  # three impulse cylinders
    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    # one baked aft-running boost cylinder per pod, at each pod position + radius
    ln = 2.0
    ax = sg.IMPULSE_AFT_AXIS
    assert rend.cylinder_calls == [
        (7, (-1.22, -0.20, 0.32), ax, 0.25, ln),
        (7, (1.22, -0.20, 0.32), ax, 0.25, ln),
        (7, (0.0, -1.10, -0.08), ax, 0.25, ln),
    ]
    assert sum(1 for r in ctrl._regions if r["boost"]) == 3
    # driving at full throttle pushes a full-gain call per pod
    ctrl.update(now=0.0)
    assert len(rend.gain_calls) == 3
    assert all(abs(g - sg.GAIN_MAX) < 1e-9 for (_i, _x, g, _ax) in rend.gain_calls)


def test_controller_no_boost_when_impulse_disabled():
    # Disabled/destroyed -> the dim state machine owns it; no brightness boost.
    impulse = _ImpulseSub(_Point(0.0, -0.98, -0.45), max_speed=10.0)
    impulse.disabled = True
    ship = _AIShip(None, impulse, None, setpoint=(10.0, (0, 1, 0), 0))
    rend = _FakeRenderer(results=[0])
    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    ctrl.update(now=0.0)
    assert rend.gain_calls == [(7, 0, 1.0, sg.IMPULSE_AFT_AXIS)]


# ---------------------------------------------------------------------------
# Baked hardpoint glow regions (impulse pods driven by GlowRegion* fields)
# ---------------------------------------------------------------------------

from engine.appc.properties import EngineProperty, read_indexed_setter_args


def _baked_prop(*calls):
    """EngineProperty authored with raw schema calls: (method, *args) tuples."""
    prop = EngineProperty("Center Impulse")
    for method, *args in calls:
        getattr(prop, method)(*args)
    return prop


class _BakedPod(_Pod):
    def __init__(self, pos, radius=2.0, prop=None, name="pod"):
        super().__init__(pos, radius)
        self._prop, self._name = prop, name
    def GetProperty(self): return self._prop
    def GetName(self): return self._name


def test_read_indexed_setter_args_round_trips_schema():
    prop = _baked_prop(
        ("SetGlowRegionShape", 0, "Cylinder"),
        ("SetGlowRegionPosition", 0, 1.0, -2.0, 0.5),
        ("SetGlowRegionAxis", 0, 0.0, -1.0, 0.0),
        ("SetGlowRegionRadius", 0, 0.4),
        ("SetGlowRegionExtent", 0, -1.0, 2.0),
    )
    assert read_indexed_setter_args(prop, "GlowRegionShape", 0) == ("Cylinder",)
    assert read_indexed_setter_args(prop, "GlowRegionPosition", 0) == (1.0, -2.0, 0.5)
    assert read_indexed_setter_args(prop, "GlowRegionAxis", 0) == (0.0, -1.0, 0.0)
    assert read_indexed_setter_args(prop, "GlowRegionRadius", 0) == (0.4,)
    assert read_indexed_setter_args(prop, "GlowRegionExtent", 0) == (-1.0, 2.0)
    assert read_indexed_setter_args(prop, "GlowRegionScale", 0) is None
    assert read_indexed_setter_args(None, "GlowRegionShape", 0) is None


def test_baked_glow_regions_stop_at_first_unset_index():
    prop = _baked_prop(
        ("SetGlowRegionShape", 0, "Sphere"),
        ("SetGlowRegionRadius", 0, 0.3),
        ("SetGlowRegionShape", 2, "Sphere"),  # index 1 missing -> 2 unreachable
        ("SetGlowRegionRadius", 2, 0.3),
    )
    assert [r["index"] for r in sg.baked_glow_regions(prop)] == [0]
    assert sg.baked_glow_regions(None) == []


def test_resolve_baked_cylinder_shifts_centre_by_aft_extent():
    raw = {"shape": "Cylinder", "position": (1.0, -2.0, 0.5),
           "axis": (0.0, -2.0, 0.0),  # non-unit on purpose
           "radius": (0.4,), "extent": (-1.0, 2.0), "scale": None}
    op = sg.resolve_baked_region(raw, None)
    # unit axis (0,-1,0); centre = pos + axis*aft = (1, -2, 0.5) + (0, 1, 0)
    assert op == ("cylinder", (1.0, -1.0, 0.5), (0.0, -1.0, 0.0), 0.4, 3.0)


def test_resolve_baked_position_defaults_to_hardpoint():
    raw = {"shape": "Sphere", "position": None, "radius": (0.3,),
           "axis": None, "extent": None, "scale": None}
    assert sg.resolve_baked_region(raw, (4.0, 5.0, 6.0)) == \
        ("sphere", (4.0, 5.0, 6.0), 0.3)
    assert sg.resolve_baked_region(raw, None) is None  # nowhere to anchor


def test_resolve_baked_rejects_malformed_and_unsupported():
    base = {"position": (0.0, 0.0, 0.0), "axis": (0.0, -1.0, 0.0),
            "radius": (0.4,), "extent": (0.0, 2.0), "scale": None}
    assert sg.resolve_baked_region({**base, "shape": "Cylinder", "extent": None}, None) is None
    assert sg.resolve_baked_region({**base, "shape": "Cylinder", "extent": (2.0, 2.0)}, None) is None
    assert sg.resolve_baked_region({**base, "shape": "Cylinder", "axis": (0.0, 0.0, 0.0)}, None) is None
    assert sg.resolve_baked_region({**base, "shape": "Sphere", "radius": (0.0,)}, None) is None
    assert sg.resolve_baked_region({**base, "shape": "Warble"}, None) is None
    # Box is schema-valid but has no renderer shape yet -> unusable for now.
    assert sg.resolve_baked_region(
        {**base, "shape": "Box", "scale": (0.3, 1.0, 0.12)}, None) is None


def test_controller_uses_baked_cylinder_over_legacy_derivation():
    prop = _baked_prop(
        ("SetGlowRegionShape", 0, "Cylinder"),
        ("SetGlowRegionAxis", 0, 0.0, -1.0, 0.0),
        ("SetGlowRegionRadius", 0, 0.5),        # != pod radius 0.25
        ("SetGlowRegionExtent", 0, -1.0, 3.0),  # != legacy (0, 2)
    )
    impulse = _BakedPod(_Point(0.0, -1.0, -0.45), radius=0.25, prop=prop)
    ship = _Ship(None, impulse, None)
    rend = _FakeRenderer(results=[0])
    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    # centre shifted forward by aft=-1 along (0,-1,0) => +1 on Y; length 4.
    assert rend.cylinder_calls == [(7, (0.0, 0.0, -0.45), (0.0, -1.0, 0.0), 0.5, 4.0)]
    assert ctrl._regions[0]["boost"] is True


def test_controller_baked_sphere_still_boosts_with_gain():
    prop = _baked_prop(
        ("SetGlowRegionShape", 0, "Sphere"),
        ("SetGlowRegionRadius", 0, 0.6),
    )
    impulse = _BakedPod(_Point(1.0, 2.0, 3.0), prop=prop)
    ship = _Ship(None, impulse, None)
    rend = _FakeRenderer(results=[4])
    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    assert rend.sphere_calls == [(7, (1.0, 2.0, 3.0), 0.6)]
    assert rend.cylinder_calls == []
    ctrl.update(now=0.0)
    assert rend.gain_calls == [(7, 4, 1.0, sg.IMPULSE_AFT_AXIS)]


def test_controller_multiple_baked_regions_all_boost():
    prop = _baked_prop(
        ("SetGlowRegionShape", 0, "Cylinder"),
        ("SetGlowRegionAxis", 0, 0.0, -1.0, 0.0),
        ("SetGlowRegionRadius", 0, 0.25),
        ("SetGlowRegionExtent", 0, 0.0, 2.0),
        ("SetGlowRegionShape", 1, "Sphere"),
        ("SetGlowRegionRadius", 1, 0.3),
    )
    impulse = _BakedPod(_Point(0.0, 0.0, 0.0), prop=prop)
    ship = _Ship(None, impulse, None)
    rend = _FakeRenderer(results=[0, 1])
    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    assert len(ctrl._regions) == 2
    assert all(r["boost"] for r in ctrl._regions)
    ctrl.update(now=0.0)
    assert [c[1] for c in rend.gain_calls] == [0, 1]


def test_controller_box_only_pod_warns_and_registers_nothing(caplog):
    """Box has no renderer shape yet: warn, and the pod gets NO glow region
    (no in-engine derivation exists anymore)."""
    prop = _baked_prop(
        ("SetGlowRegionShape", 0, "Box"),
        ("SetGlowRegionScale", 0, 0.3, 1.0, 0.12),
    )
    impulse = _BakedPod(_Point(0.0, -0.98, -0.45), radius=0.25, prop=prop,
                        name="Center Impulse")
    ship = _Ship(None, impulse, None)
    rend = _FakeRenderer(results=[])
    with caplog.at_level("WARNING", logger="engine.appc.subsystem_glow"):
        ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    assert "Center Impulse" in caplog.text and "skipped" in caplog.text
    assert rend.cylinder_calls == [] and rend.sphere_calls == []
    assert ctrl._regions == []


def test_controller_unbaked_pod_gets_no_glow_vfx():
    """The hardpoint is the single source of truth — a pod whose property
    bakes nothing gets no impulse glow region at all; a baked sibling on the
    same ship is unaffected."""
    prop = _baked_prop(
        ("SetGlowRegionShape", 0, "Cylinder"),
        ("SetGlowRegionAxis", 0, 0.0, -1.0, 0.0),
        ("SetGlowRegionRadius", 0, 0.5),
        ("SetGlowRegionExtent", 0, 0.0, 2.0),
    )
    baked = _BakedPod(_Point(-1.0, 0.0, 0.0), prop=prop)
    unbaked = _Pod(_Point(1.0, 0.0, 0.0), radius=0.25, baked=False)
    agg = _WarpAgg([baked, unbaked])  # generic children container
    ship = _Ship(None, agg, None)
    rend = _FakeRenderer(results=[0])
    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    assert rend.cylinder_calls == [
        (7, (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), 0.5, 2.0),
    ]
    assert len(ctrl._regions) == 1


def test_controller_survives_garbage_baked_values(caplog):
    """Modder-supplied hardpoints must never crash ship spawn: non-numeric
    baked values drop that region with a warning; a valid sibling region on
    the same pod still registers."""
    prop = _baked_prop(
        ("SetGlowRegionShape", 0, "Sphere"),
        ("SetGlowRegionRadius", 0, "big"),      # garbage -> skipped
        ("SetGlowRegionShape", 1, "Sphere"),
        ("SetGlowRegionRadius", 1, 0.3),        # valid -> registers
    )
    impulse = _BakedPod(_Point(0.0, 0.0, 0.0), prop=prop, name="Center Impulse")
    ship = _Ship(None, impulse, None)
    rend = _FakeRenderer(results=[0])
    with caplog.at_level("WARNING", logger="engine.appc.subsystem_glow"):
        ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    assert "Center Impulse" in caplog.text and "skipped" in caplog.text
    assert rend.sphere_calls == [(7, (0.0, 0.0, 0.0), 0.3)]
    assert len(ctrl._regions) == 1
