"""The six F1-F6 cinematic camera handlers, driven end to end.

Task 4 wired F1-F6 through to CinematicInterfaceHandlers, which means these six
functions execute in this engine for the first time. Pressing F3 in-game crashed
immediately:

    File "CinematicInterfaceHandlers.py", line 371, in CameraTarget
        for iCount in range(len(lSources)):
    TypeError: object of type '_RendererStub' has no len()

because SetClass.GetTargetableObjects (:356) was unimplemented and
SetClass.__getattr__ vended a truthy, non-iterable stub past the SDK's
`if lSources:` guard.

These tests call each handler with a real game/player/set/camera. They are
deliberately at the SDK-function boundary rather than the keystroke boundary:
test_cinematic_key_routing.py already owns the keystroke->event half and stops
its chain with a probe, so nothing there ever runs the handler bodies.
"""
import pytest

import App
from engine.appc import top_window
from engine.appc.ships import ShipClass
from engine.core.game import Game, Episode, Mission, _set_current_game

ALL_HANDLERS = (
    "CameraDropAndWatch",
    "CameraChase",
    "CameraTarget",
    "CameraTorpCam",
    "CameraWideTarget",
    "CameraFreeOrbit",
)


@pytest.fixture
def cinematic_world():
    """A live game with a player ship, one other ship, and a focused,
    interactive cinematic window — what the handlers see when the player hits
    F1-F6 in space."""
    mission = Mission()
    mission.SetScript("tests.integration.test_cinematic_camera_handlers")
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)

    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "S")

    player = ShipClass()
    player.SetTranslateXYZ(0.0, 0.0, 0.0)
    pSet.AddObjectToSet(player, "Player")
    other = ShipClass()
    other.SetTranslateXYZ(10.0, 0.0, 0.0)
    pSet.AddObjectToSet(other, "Other")
    game.SetCurrentPlayer(player)

    top_window.reset_for_tests()
    tw = App.TopWindow_GetTopWindow()
    tw.ToggleCinematicWindow()
    cine = tw.FindMainWindow(App.MWT_CINEMATIC)

    yield game, pSet, player, other, cine

    _set_current_game(None)
    App.g_kSetManager._sets.clear()
    top_window.reset_for_tests()


@pytest.mark.parametrize("handler", ALL_HANDLERS)
def test_every_cinematic_camera_handler_runs_without_raising(handler, cinematic_world):
    """F1-F6 must not throw. Anything they touch that we do not implement vends
    a _Stub, and a stub reaching len()/iteration/subscript is a hard crash."""
    import CinematicInterfaceHandlers

    _game, _pSet, _player, _other, cine = cinematic_world
    getattr(CinematicInterfaceHandlers, handler)(cine, App.TGEvent_Create())


def test_camera_target_wires_a_real_source_onto_the_reverse_target_mode(cinematic_world):
    """F3's whole job: pick a targetable object that is not the player and set
    it as the CinematicReverseTarget mode's Source."""
    import CinematicInterfaceHandlers

    game, _pSet, _player, other, cine = cinematic_world
    mode = game.GetPlayerCamera().GetNamedCameraMode("CinematicReverseTarget")
    assert mode is not None
    assert mode.GetAttrIDObject("Source") is None

    CinematicInterfaceHandlers.CameraTarget(cine, App.TGEvent_Create())

    assert mode.GetAttrIDObject("Source") is other


def test_camera_target_cycles_to_the_next_source_on_a_second_press(cinematic_world):
    """The handler's `iStartIndex = (iStartIndex + 1) % len(lSources)` cycle —
    the loop that crashed. Two non-player ships means two presses must land on
    two different sources, which only works if the list is a real ordered
    sequence."""
    import CinematicInterfaceHandlers

    game, pSet, _player, other, cine = cinematic_world
    third = ShipClass()
    third.SetTranslateXYZ(-10.0, 0.0, 0.0)
    pSet.AddObjectToSet(third, "Third")

    mode = game.GetPlayerCamera().GetNamedCameraMode("CinematicReverseTarget")
    CinematicInterfaceHandlers.CameraTarget(cine, App.TGEvent_Create())
    first = mode.GetAttrIDObject("Source")
    CinematicInterfaceHandlers.CameraTarget(cine, App.TGEvent_Create())
    second = mode.GetAttrIDObject("Source")

    assert {first, second} == {other, third}
    assert first is not second


def test_the_camera_mode_caption_updates_when_the_mode_changes(cinematic_world):
    """All six handlers end in UpdateCameraModeText. It builds the caption pane
    ONCE and thereafter only calls TGParagraph.SetString (:255), so a stubbed
    SetString froze the caption on the first mode the player picked."""
    import CinematicInterfaceHandlers as C

    _game, _pSet, _player, _other, cine = cinematic_world
    C.g_idCameraModeText = App.NULL_ID
    C.g_idCameraModeTextTimer = App.NULL_ID

    C.CameraChase(cine, App.TGEvent_Create())
    pane = App.TGPane_Cast(App.TGObject_GetTGObjectPtr(C.g_idCameraModeText))
    assert pane is not None, "first press must create the caption pane"
    text = App.TGParagraph_Cast(pane.GetNthChild(0))
    assert text.GetText() == "Chase View"

    C.CameraFreeOrbit(cine, App.TGEvent_Create())          # else-branch: SetString
    assert App.TGObject_GetTGObjectPtr(C.g_idCameraModeText) is pane
    assert text.GetText() == "Free Orbit View"


def test_camera_target_never_selects_the_player_as_its_own_source(cinematic_world):
    """pSkipObject is the player. With the player as the ONLY object in the set
    there is no valid source, `if lSources:` must be false, and the handler must
    still complete (no Source, no crash)."""
    import CinematicInterfaceHandlers

    game, pSet, player, other, cine = cinematic_world
    pSet.DeleteObjectFromSet("Other")
    mode = game.GetPlayerCamera().GetNamedCameraMode("CinematicReverseTarget")

    CinematicInterfaceHandlers.CameraTarget(cine, App.TGEvent_Create())

    assert mode.GetAttrIDObject("Source") is None


def test_camera_target_never_cycles_onto_a_waypoint_or_placement(cinematic_world):
    """The live defect: waypoints and placements sat in
    SetClass.GetTargetableObjects, so pressing F3 parked the cinematic camera
    on an invisible nav marker. Press it once per object in the set (plus one)
    so every position in the handler's `(iStartIndex + 1) % len(lSources)`
    cycle is visited — a source that is not a ship must never come up."""
    import CinematicInterfaceHandlers
    from engine.appc.placement import PlacementObject, Waypoint

    game, pSet, _player, other, cine = cinematic_world
    wp = Waypoint()
    wp.SetTranslateXYZ(0.0, 50.0, 0.0)
    pSet.AddObjectToSet(wp, "Waypoint1")
    placement = PlacementObject()
    placement.SetTranslateXYZ(0.0, -50.0, 0.0)
    pSet.AddObjectToSet(placement, "Placement1")

    mode = game.GetPlayerCamera().GetNamedCameraMode("CinematicReverseTarget")
    seen = []
    for _ in range(6):
        CinematicInterfaceHandlers.CameraTarget(cine, App.TGEvent_Create())
        seen.append(mode.GetAttrIDObject("Source"))

    assert wp not in seen and placement not in seen
    assert set(seen) == {other}
