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
