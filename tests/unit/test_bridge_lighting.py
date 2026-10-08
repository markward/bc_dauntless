import pytest
from engine import bridge_lighting as bl


@pytest.mark.parametrize("level,scale", [(0, 1.5), (1, 1.0), (2, 1.0), (3, 1.0), (-1, 1.0)])
def test_ambient_scale_for_alert(level, scale):
    assert bl.ambient_scale_for_alert(level) == scale


def test_no_player_is_authored_ambient():            # Review Focus #5
    assert bl.player_bridge_ambient_scale(None) == 1.0


def test_alert_probe_raising_is_authored_ambient():  # Review Focus #5
    class Broken:
        def GetAlertLevel(self): raise RuntimeError("mid swap")
    assert bl.player_bridge_ambient_scale(Broken()) == 1.0


def test_green_player():
    class P:
        def GetAlertLevel(self): return 0
    assert bl.player_bridge_ambient_scale(P()) == 1.5


def test_host_loop_uses_the_module():
    import inspect, engine.host_loop as hl
    src = inspect.getsource(hl)
    assert "player_bridge_ambient_scale(" in src
    assert "_bridge_dim = 0.5" not in src
