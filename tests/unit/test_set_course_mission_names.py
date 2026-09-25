"""A Set Course pick carries the region menu's mission/episode onto the warp
button (67 SDK SetMissionName/SetEpisodeName sites); a new pick clears stale
names (Review Focus 4)."""
from engine.appc import warp
from engine.appc.tg_ui.st_widgets import STWarpButton, SortedRegionMenu
from engine.appc.characters import STMenu


def _course_menu():
    root = STMenu("Set Course")
    beol = SortedRegionMenu("Beol", "Systems.Beol.Beol4")
    beol.SetMissionName("Maelstrom.Episode6.E6M2.E6M2")
    sb = SortedRegionMenu("Starbase 12", "Systems.Starbase12.Starbase12")
    sb.SetEpisodeName("Maelstrom.Episode6.Episode6")
    plain = SortedRegionMenu("Vesuvi", "Systems.Vesuvi.Vesuvi4")
    for m in (beol, sb, plain):
        root.AddChild(m)
    return root


def test_mission_name_reaches_the_button(monkeypatch):
    monkeypatch.setattr(warp, "find_set_course_menu", _course_menu)
    b = STWarpButton("Warp")
    b.set_player_destination("Systems.Beol.Beol4")
    warp.set_course_placement(b, "Systems.Beol.Beol4")
    assert b.get_mission_name() == "Maelstrom.Episode6.E6M2.E6M2"
    assert b.get_episode_name() == ""


def test_episode_name_reaches_the_button(monkeypatch):
    monkeypatch.setattr(warp, "find_set_course_menu", _course_menu)
    b = STWarpButton("Warp")
    b.set_player_destination("Systems.Starbase12.Starbase12")
    warp.set_course_placement(b, "Systems.Starbase12.Starbase12")
    assert b.get_episode_name() == "Maelstrom.Episode6.Episode6"


def test_a_plain_pick_clears_stale_names(monkeypatch):
    monkeypatch.setattr(warp, "find_set_course_menu", _course_menu)
    b = STWarpButton("Warp")
    b.SetDestination("Systems.Starbase12.Starbase12",
                     "Maelstrom.Episode7.E7M1.E7M1", "Player Start",
                     "Maelstrom.Episode7.Episode7")
    b.set_player_destination("Systems.Vesuvi.Vesuvi4")
    warp.set_course_placement(b, "Systems.Vesuvi.Vesuvi4")
    assert b.get_mission_name() == "" and b.get_episode_name() == ""
