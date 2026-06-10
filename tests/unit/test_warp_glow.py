from engine.appc import warp_glow


def test_dim_target_healthy_is_full():
    assert warp_glow.dim_target(disabled=False) == 1.0


def test_dim_target_disabled_is_residual():
    assert warp_glow.dim_target(disabled=True) == warp_glow.DISABLED_RESIDUAL


def test_disable_time_tracks_falling_edge():
    # healthy -> no edge
    t = warp_glow.disable_edge(prev_disabled=False, now_disabled=False,
                               prev_time=-1.0, now=10.0)
    assert t == -1.0
    # falling edge stamps now
    t = warp_glow.disable_edge(prev_disabled=False, now_disabled=True,
                               prev_time=-1.0, now=10.0)
    assert t == 10.0
    # still disabled -> keep original stamp
    t = warp_glow.disable_edge(prev_disabled=True, now_disabled=True,
                               prev_time=10.0, now=12.0)
    assert t == 10.0
    # repair -> clear
    t = warp_glow.disable_edge(prev_disabled=True, now_disabled=False,
                               prev_time=10.0, now=13.0)
    assert t == -1.0


def test_warp_pods_enumerates_children_then_falls_back_to_aggregator():
    class _Pod:
        def __init__(self, name):
            self._n = name
        def GetName(self):
            return self._n

    class _Agg:
        def __init__(self, kids):
            self._kids = kids
        def GetNumChildSubsystems(self):
            return len(self._kids)
        def GetChildSubsystem(self, i):
            return self._kids[i]

    kids = [_Pod("Port Warp"), _Pod("Star Warp")]
    assert warp_glow.warp_pods(_Agg(kids)) == kids
    # no children -> the aggregator itself is the single "pod"
    agg = _Agg([])
    assert warp_glow.warp_pods(agg) == [agg]
    # None aggregator -> empty
    assert warp_glow.warp_pods(None) == []


class _FakePoint:
    def __init__(self, x, y, z):
        self._x, self._y, self._z = x, y, z
    def GetX(self):
        return self._x
    def GetY(self):
        return self._y
    def GetZ(self):
        return self._z


class _FakePod:
    def __init__(self, pos, radius=2.0, disabled=False, destroyed=False):
        self._pos = pos
        self._radius = radius
        self.disabled = disabled
        self.destroyed = destroyed
    def GetPosition(self):
        return self._pos
    def GetRadius(self):
        return self._radius
    def IsDisabled(self):
        return self.disabled
    def IsDestroyed(self):
        return self.destroyed


class _FakeAgg:
    def __init__(self, kids):
        self._kids = kids
    def GetNumChildSubsystems(self):
        return len(self._kids)
    def GetChildSubsystem(self, i):
        return self._kids[i]


class _FakeRenderer:
    def __init__(self, region_results):
        # region_results: list of idx values returned per compute call (in order)
        self._region_results = list(region_results)
        self.compute_calls = []
        self.dim_calls = []
    def compute_capsule_region(self, instance_id, center, axis, radius):
        self.compute_calls.append((instance_id, center, axis, radius))
        return self._region_results.pop(0)
    def set_glow_region_dim(self, instance_id, region_index, dim_target, disable_time):
        self.dim_calls.append((instance_id, region_index, dim_target, disable_time))


def test_controller_registers_and_drives_dim_state_across_edges():
    port = _FakePod(_FakePoint(-3.0, 1.0, 0.0), radius=2.0)
    star = _FakePod(_FakePoint(3.0, 1.0, 0.0), radius=2.0)
    skipped = _FakePod(_FakePoint(0.0, 5.0, 0.0), radius=2.0)
    agg = _FakeAgg([port, star, skipped])

    # First two pods register (idx 0, 1); third returns -1 and is skipped.
    rend = _FakeRenderer(region_results=[0, 1, -1])
    ctrl = warp_glow.WarpGlowController(rend, instance_id=42, warp_subsystem=agg)

    # (a) compute_capsule_region called once per pod with valid position + axis.
    assert len(rend.compute_calls) == 3
    assert rend.compute_calls[0] == (42, (-3.0, 1.0, 0.0),
                                     warp_glow.NACELLE_AXIS, 2.0)
    assert rend.compute_calls[1] == (42, (3.0, 1.0, 0.0),
                                     warp_glow.NACELLE_AXIS, 2.0)
    # Only the two valid regions retained (idx<0 skipped).
    assert len(ctrl._regions) == 2

    # (b) healthy frame -> full dim, no disable edge.
    ctrl.update(now=10.0)
    assert rend.dim_calls == [
        (42, 0, 1.0, -1.0),
        (42, 1, 1.0, -1.0),
    ]
    rend.dim_calls.clear()

    # Disable the port pod -> residual + stamps disable_time=now.
    port.disabled = True
    ctrl.update(now=20.0)
    assert rend.dim_calls == [
        (42, 0, warp_glow.DISABLED_RESIDUAL, 20.0),
        (42, 1, 1.0, -1.0),
    ]
    rend.dim_calls.clear()

    # Still disabled at a later time -> keep the original 20.0 stamp.
    ctrl.update(now=25.0)
    assert rend.dim_calls == [
        (42, 0, warp_glow.DISABLED_RESIDUAL, 20.0),
        (42, 1, 1.0, -1.0),
    ]
    rend.dim_calls.clear()

    # Repaired -> back to full, disable_time cleared to -1.0.
    port.disabled = False
    ctrl.update(now=30.0)
    assert rend.dim_calls == [
        (42, 0, 1.0, -1.0),
        (42, 1, 1.0, -1.0),
    ]
