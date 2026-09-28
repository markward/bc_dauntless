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


def _multi_region_menu():
    """Systems/Utils.CreateSystemMenuInternal's shape: the SYSTEM menu is a
    SortedRegionMenu on sSystemRegion with one SortedRegionMenu child per
    region; missions name the SYSTEM menu (E3M2 on Vesuvi), not a region."""
    root = STMenu("Set Course")
    system = SortedRegionMenu("Vesuvi", "Systems.Vesuvi.Vesuvi6")
    system.SetMissionName("Maelstrom.Episode3.E3M2.E3M2")
    system.SetEpisodeName("Maelstrom.Episode3.Episode3")
    for region in ("Systems.Vesuvi.Vesuvi4", "Systems.Vesuvi.Vesuvi5",
                   "Systems.Vesuvi.Vesuvi6"):
        system.AddChild(SortedRegionMenu(region.rsplit(".", 1)[1], region))
    own = SortedRegionMenu("Tevron 2", "Systems.Tevron.Tevron2")
    own.SetMissionName("Maelstrom.Episode2.E2M0.E2M0")
    tevron = SortedRegionMenu("Tevron", "Systems.Tevron.Tevron1")
    tevron.SetMissionName("Maelstrom.Episode1.E1M2.E1M2")
    tevron.SetEpisodeName("Maelstrom.Episode2.Episode2")
    tevron.AddChild(own)
    root.AddChild(system)
    root.AddChild(tevron)
    return root


def test_every_region_of_a_named_system_carries_its_names(monkeypatch):
    monkeypatch.setattr(warp, "find_set_course_menu", _multi_region_menu)
    for region in ("Systems.Vesuvi.Vesuvi4", "Systems.Vesuvi.Vesuvi5",
                   "Systems.Vesuvi.Vesuvi6"):
        b = STWarpButton("Warp")
        b.set_player_destination(region)
        warp.set_course_placement(b, region)
        assert b.get_mission_name() == "Maelstrom.Episode3.E3M2.E3M2", region
        assert b.get_episode_name() == "Maelstrom.Episode3.Episode3", region


def test_a_regions_own_name_wins_over_its_systems(monkeypatch):
    monkeypatch.setattr(warp, "find_set_course_menu", _multi_region_menu)
    b = STWarpButton("Warp")
    b.set_player_destination("Systems.Tevron.Tevron2")
    warp.set_course_placement(b, "Systems.Tevron.Tevron2")
    assert b.get_mission_name() == "Maelstrom.Episode2.E2M0.E2M0"
    # No episode of its own: the system's is inherited, name by name.
    assert b.get_episode_name() == "Maelstrom.Episode2.Episode2"
