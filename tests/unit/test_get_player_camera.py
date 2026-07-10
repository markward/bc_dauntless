from engine.core.game import Game
from engine.appc.bridge_set import CameraObjectClass


def test_get_player_camera_is_lazy_and_stable():
    g = Game()
    assert g._player_camera is None
    cam = g.GetPlayerCamera()
    assert isinstance(cam, CameraObjectClass)
    assert g.GetPlayerCamera() is cam          # identity-stable
    assert g._player_camera is cam


def test_get_player_camera_name():
    cam = Game().GetPlayerCamera()
    assert cam._name == "MainPlayerCamera"
