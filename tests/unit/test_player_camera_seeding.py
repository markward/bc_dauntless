"""GetPlayerCamera seeds what Camera.MakePlayerCamera would have: the four
always-invalid Invalid* markers (Camera.py:624-628) and the default hierarchy
edges (Camera.py:630-646). Game.SetPlayer applies the player-attr table
(Camera.py:685-703) so Chase/Target/... anchor on the player."""
import App
from engine.appc.camera_modes import ChaseMode


def _game():
    from engine.core.game import Game
    return Game()


def test_player_camera_has_the_four_invalid_markers():
    cam = _game().GetPlayerCamera()
    for name in ("InvalidViewscreen", "InvalidSpace",
                 "InvalidCinematic", "InvalidMap"):
        m = cam.GetNamedCameraMode(name)
        assert isinstance(m, ChaseMode), name
        assert not m.IsValid(), name          # never given a Target


def test_player_camera_has_bc_default_edges():
    cam = _game().GetPlayerCamera()
    e = cam._mode_hierarchy
    assert e["InvalidCinematic"] == "DropAndWatch"
    assert e["InvalidSpace"] == "Target"
    assert e["Target"] == "Chase"
    assert e["ZoomTarget"] == "Chase"
    assert e["TorpCam"] == "Chase"
    assert e["CinematicReverseTarget"] == "Chase"
    assert e["InvalidMap"] == "Map"
    assert e["InvalidViewscreen"] == "ViewscreenZoomTarget"
    assert e["ViewscreenZoomTarget"] == "ViewscreenForward"


def test_set_player_puts_the_player_on_the_mode_table():
    from engine.appc.ships import ShipClass_Create
    g = _game()
    cam = g.GetPlayerCamera()
    ship = ShipClass_Create("SeedPlayer")
    g.SetPlayer(ship)
    chase = cam.GetNamedCameraMode("Chase")
    assert chase.GetAttrIDObject("Target") is ship
    assert chase.IsValid()
    tgt = cam.GetNamedCameraMode("Target")
    assert tgt.GetAttrIDObject("Source") is ship
    rev = cam.GetNamedCameraMode("CinematicReverseTarget")
    assert rev.GetAttrIDObject("Target") is ship


def test_set_player_none_is_safe():
    g = _game()
    g.GetPlayerCamera()
    g.SetPlayer(None)                        # must not raise
