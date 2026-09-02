from engine.appc.tg_ui.st_widgets import (
    STWarpButton,
    SortedRegionMenu_CreateW,
)


def test_region_module_retained():
    m = SortedRegionMenu_CreateW("Vesuvi Dust Cloud", "Systems.Vesuvi.Vesuvi4")
    assert m.GetRegionModule() == "Systems.Vesuvi.Vesuvi4"
    assert m._region == "Systems.Vesuvi.Vesuvi4"


def test_region_module_defaults_none():
    m = SortedRegionMenu_CreateW("Some System")
    assert m.GetRegionModule() is None


def test_warp_event_constant_exists():
    import App
    assert isinstance(App.ET_WARP_BUTTON_PRESSED, int)


# --- mission name: BC's own "this destination starts mission X" marker -----
# Real published surface (sdk/.../App.py:8762/:8768). E3M2.py:258 marks Vesuvi
# for the current mission; E3M2.py:254 clears Starbase 12 with a no-arg call.

def test_region_mission_name_defaults_to_a_falsy_empty_string():
    """Unimplemented this was a truthy _Stub (heatmap rank 143), which reads
    as 'every destination is a mission target' — the exact inversion."""
    m = SortedRegionMenu_CreateW("Vesuvi")
    assert m.GetMissionName() == ""
    assert not m.GetMissionName()


def test_region_mission_name_round_trips():
    m = SortedRegionMenu_CreateW("Vesuvi")
    m.SetMissionName("Maelstrom.Episode3.E3M2.E3M2")
    assert m.GetMissionName() == "Maelstrom.Episode3.E3M2.E3M2"


def test_region_mission_name_clears_when_called_with_no_argument():
    """E3M2.py:254, E4M4.py:2034 and E3M4.py:258 all clear this way."""
    m = SortedRegionMenu_CreateW("Starbase 12")
    m.SetMissionName("Maelstrom.Episode3.E3M2.E3M2")
    m.SetMissionName()
    assert m.GetMissionName() == ""


def test_region_episode_name_round_trips_and_defaults_falsy():
    m = SortedRegionMenu_CreateW("Nepenthe")
    assert m.GetEpisodeName() == ""
    m.SetEpisodeName("Maelstrom.Episode5.Episode5")   # Episode4.py:202
    assert m.GetEpisodeName() == "Maelstrom.Episode5.Episode5"


# --- warp button: SetDestination's real four-argument form -----------------

def test_warp_button_set_destination_accepts_the_sdk_four_arg_form():
    """E6M5.py:2666 and E7M6.py:996 pass all four; E7M1.py:2792 passes two.
    A one-arg signature raises TypeError inside a broadcast handler, which
    swallows it — the episode transition then silently half-runs."""
    b = STWarpButton()
    b.SetDestination("Systems.Starbase12.Starbase12",
                     "Maelstrom.Episode7.E7M1.E7M1",
                     "Player Start", "Maelstrom.Episode7.Episode7")
    assert b.GetDestination() == "Systems.Starbase12.Starbase12"
    assert b.GetPlacementName() == "Player Start"


def test_warp_button_script_destination_is_latched_as_the_mission_target():
    b = STWarpButton()
    b.SetDestination("Systems.Vesuvi.Vesuvi4")       # E3M2.py:2124
    assert b.get_mission_destination() == "Systems.Vesuvi.Vesuvi4"


def test_player_course_selection_does_not_overwrite_the_mission_target():
    """Browsing the star map must not destroy the mission's own hint — the
    whole point of latching it separately from the live destination."""
    b = STWarpButton()
    b.SetDestination("Systems.Vesuvi.Vesuvi4")
    b.set_player_destination("Systems.Vesuvi.Vesuvi5")
    assert b.GetDestination() == "Systems.Vesuvi.Vesuvi5"
    assert b.get_mission_destination() == "Systems.Vesuvi.Vesuvi4"
