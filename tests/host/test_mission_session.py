"""MissionSession + reset_sdk_globals — backend for in-process mission swaps."""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent


def test_reset_sdk_globals_clears_state():
    """After reset, the five SDK globals listed in the spec are empty."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from tools import mission_harness
    mission_harness.setup_sdk()

    import App
    from engine.appc.placement import _waypoint_registry
    from engine.host_loop import reset_sdk_globals

    App.g_kTimerManager._timers["x"] = object()
    App.g_kRealtimeTimerManager._timers["y"] = object()
    App.g_kEventManager._broadcast_handlers["t"] = [object()]
    App.g_kSetManager._sets["s"] = object()
    _waypoint_registry["w"] = object()
    App._next_event_type_id = 999

    reset_sdk_globals()

    assert App.g_kTimerManager._time == 0.0
    assert App.g_kTimerManager._timers == {}
    assert App.g_kRealtimeTimerManager._time == 0.0
    assert App.g_kRealtimeTimerManager._timers == {}
    assert App.g_kEventManager._broadcast_handlers == {}
    assert App.g_kSetManager._sets == {}
    assert _waypoint_registry == {}
    assert App._next_event_type_id == 200


def test_mission_session_teardown_drops_instances():
    """teardown destroys every renderer instance the session created."""
    from engine.host_loop import MissionSession

    destroyed: list[int] = []

    class FakeRenderer:
        def destroy_instance(self, iid):
            destroyed.append(iid)

    sess = MissionSession(mission_name="x",
                          ship_instances={"shipA": 11, "shipB": 12},
                          planet_instances={"planetA": 21},
                          player=None)
    sess.teardown(FakeRenderer())
    assert sorted(destroyed) == [11, 12, 21]
    assert sess.ship_instances == {}
    assert sess.planet_instances == {}


def test_host_controller_swap_is_deferred():
    """swap_mission() must NOT load synchronously — it sets pending_swap."""
    from engine.host_loop import HostController

    h = HostController()
    h.swap_mission("Some.Mission.Name")
    assert h.pending_swap == "Some.Mission.Name"


def test_host_controller_drain_clears_pending():
    """_drain_pending_swap loads then clears the latch."""
    from engine.host_loop import HostController, MissionSession

    loaded: list[str] = []

    class StubLoader:
        def load(self, name):
            loaded.append(name)
            return MissionSession(mission_name=name)

    class FakeRenderer:
        def destroy_instance(self, iid): pass

    h = HostController()
    h.renderer = FakeRenderer()
    h.loader = StubLoader()
    h.session = MissionSession(mission_name="prev")
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()
    assert loaded == ["Next.Mission"]
    assert h.pending_swap is None
    assert h.session is not None
    assert h.session.mission_name == "Next.Mission"
