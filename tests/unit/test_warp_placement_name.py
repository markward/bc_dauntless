"""A mission's chosen arrival placement must survive to the warp.

BC lets a mission override where the player drops out of warp:

    # MissionLib.py:2641 -- "Links one of the helm menu buttons to a placement
    # other than the default 'Player Start'."
    def LinkMenuToPlacement(pcSystem, pcRegion, pcPlacementName):
        pMenu = GetSystemOrRegionMenu(pcSystem, pcRegion)
        if (pMenu != None):
            pMenu.SetPlacementName(pcPlacementName)

E1M1.py:673 uses it for the whole endgame:

    MissionLib.LinkMenuToPlacement("Starbase 12", None, "PlayerSpecialStart")

`SortedRegionMenu.SetPlacementName` is real published surface
(sdk/.../App.py:8763), as is the twin on the warp button (:8738) that carries
the chosen placement from the course menu to the warp itself. Neither was
implemented, so LinkMenuToPlacement hit a silent _Stub -- live telemetry has it
at docs/stub_heatmap.md rank 144, 57 hits over 56/233 runs -- and
warp.execute_warp hardcoded "Player Start".

What that cost, measured against the real placement data:

    PlayerSpecialStart -> "Starbase Nav"   1784.6 GU = 312.30 km   (BC)
    Player Start       -> "Starbase Nav"    529.7 GU =  92.70 km   (ours)

So the player arrived a quarter of the way across the system from where E1M1
intends, on the wrong side of Starbase 12. It also silently disabled the
approach BC scripts: Intercept's in-system warp only engages beyond
fInSystemWarpDistance = 295.0 GU (AI/PlainAI/Intercept.py:54), and the whole
"warp in, engage, drop out on approach" beat is built around starting far
outside it.
"""
import App
import pytest

from engine.appc import warp
from engine.appc.tg_ui.st_widgets import (
    SortedRegionMenu_CreateW,
    STWarpButton_CreateW,
)

DEFAULT = "Player Start"


# ── Storage ──────────────────────────────────────────────────────────────────

def test_region_menu_placement_name_defaults_to_player_start():
    """BC's own words for the default, from LinkMenuToPlacement's docstring:
    "a placement other than the default 'Player Start'"."""
    m = SortedRegionMenu_CreateW("Starbase 12", "Systems.Starbase12.Starbase12")
    assert m.GetPlacementName() == DEFAULT


def test_region_menu_placement_name_roundtrips():
    m = SortedRegionMenu_CreateW("Starbase 12", "Systems.Starbase12.Starbase12")
    m.SetPlacementName("PlayerSpecialStart")
    assert m.GetPlacementName() == "PlayerSpecialStart"


def test_warp_button_placement_name_defaults_to_player_start():
    assert STWarpButton_CreateW("Warp").GetPlacementName() == DEFAULT


def test_warp_button_placement_name_roundtrips():
    b = STWarpButton_CreateW("Warp")
    b.SetPlacementName("PlayerSpecialStart")
    assert b.GetPlacementName() == "PlayerSpecialStart"


# ── Lookup: destination module -> the menu that owns it ──────────────────────

def _course_tree():
    """The Set Course subtree shape HelmMenuHandlers builds: a menu of
    per-system SortedRegionMenus, each carrying its destination module."""
    root = SortedRegionMenu_CreateW("Set Course")
    sb12 = SortedRegionMenu_CreateW("Starbase 12", "Systems.Starbase12.Starbase12")
    vesuvi = SortedRegionMenu_CreateW("Vesuvi", "Systems.Vesuvi.Vesuvi")
    root.AddChild(sb12)
    root.AddChild(vesuvi)
    return root, sb12, vesuvi


def test_placement_lookup_finds_the_menu_for_a_destination_module():
    root, sb12, _vesuvi = _course_tree()
    sb12.SetPlacementName("PlayerSpecialStart")
    assert warp.placement_name_for_destination(
        "Systems.Starbase12.Starbase12", root) == "PlayerSpecialStart"


def test_placement_lookup_is_per_destination_not_global():
    """Overriding one system must not move the arrival point of another."""
    root, sb12, _vesuvi = _course_tree()
    sb12.SetPlacementName("PlayerSpecialStart")
    assert warp.placement_name_for_destination(
        "Systems.Vesuvi.Vesuvi", root) == DEFAULT


def test_placement_lookup_searches_nested_region_menus():
    """LinkMenuToPlacement takes a region as well as a system
    (GetSystemOrRegionMenu), so the owning menu can be one level down."""
    root = SortedRegionMenu_CreateW("Set Course")
    system = SortedRegionMenu_CreateW("Vesuvi", "Systems.Vesuvi.Vesuvi")
    region = SortedRegionMenu_CreateW("Vesuvi 4", "Systems.Vesuvi.Vesuvi4")
    region.SetPlacementName("PlayerEnterVesuvi4")
    system.AddChild(region)
    root.AddChild(system)
    assert warp.placement_name_for_destination(
        "Systems.Vesuvi.Vesuvi4", root) == "PlayerEnterVesuvi4"


def test_placement_lookup_falls_back_to_default_for_unknown_module():
    root, _sb12, _vesuvi = _course_tree()
    assert warp.placement_name_for_destination("Systems.Nowhere.Nowhere",
                                               root) == DEFAULT


def test_placement_lookup_tolerates_no_course_menu():
    """Before the bridge builds its menus there is nothing to search; the warp
    must still work off the default rather than raise."""
    assert warp.placement_name_for_destination("Systems.Vesuvi.Vesuvi",
                                               None) == DEFAULT


# ── execute_warp honours the button ──────────────────────────────────────────

class _RecordingSequence:
    """Captures the placement WarpSequence_Create was built with."""
    last = None

    def Play(self):
        pass


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def _fake_create(ship, dest_module, warp_time=0.0, placement=DEFAULT):
        seen["placement"] = placement
        seen["dest"] = dest_module
        return _RecordingSequence()

    monkeypatch.setattr(warp, "WarpSequence_Create", _fake_create)
    return seen


def _button(dest, placement=None):
    b = STWarpButton_CreateW("Warp")
    b.SetDestination(dest)
    if placement is not None:
        b.SetPlacementName(placement)
    return b


def test_execute_warp_uses_the_buttons_placement_name(captured, monkeypatch):
    """THE E1M1 defect: this argument was the literal "Player Start"."""
    from engine.appc.ships import ShipClass_Create
    player = ShipClass_Create("Galaxy")
    monkeypatch.setattr(warp, "_player_hook", lambda: player)
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: player)

    warp.execute_warp(_button("Systems.Starbase12.Starbase12",
                              "PlayerSpecialStart"))

    assert captured["placement"] == "PlayerSpecialStart"


def test_execute_warp_defaults_to_player_start_when_unset(captured, monkeypatch):
    """Every mission that never calls LinkMenuToPlacement must be unaffected."""
    from engine.appc.ships import ShipClass_Create
    player = ShipClass_Create("Galaxy")
    monkeypatch.setattr(warp, "_player_hook", lambda: player)
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: player)

    warp.execute_warp(_button("Systems.Vesuvi.Vesuvi"))

    assert captured["placement"] == DEFAULT


# ── Setting a course carries the placement onto the button ───────────────────
# The link between the two halves above. In stock BC the SortedRegionMenu's own
# course button did this; our CEF Set Course modal replaced those buttons, so
# the engine has to do it when a course is plotted.


def _bridge_menus_with_set_course():
    """Helm > Set Course > {Starbase 12, Vesuvi}, registered on the real
    TacticalControlWindow — the tree HelmMenuHandlers.CreateMenus builds and
    the one MissionLib.GetSystemOrRegionMenu walks."""
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    helm = App.STMenu_CreateW(db.GetString("Helm"))
    course = SortedRegionMenu_CreateW(db.GetString("Set Course"))
    App.g_kLocalizationManager.Unload(db)
    sb12 = SortedRegionMenu_CreateW("Starbase 12", "Systems.Starbase12.Starbase12")
    vesuvi = SortedRegionMenu_CreateW("Vesuvi", "Systems.Vesuvi.Vesuvi")
    course.AddChild(sb12)
    course.AddChild(vesuvi)
    helm.AddChild(course)
    tcw.AddMenuToList(helm)
    return helm, course, sb12, vesuvi


def test_find_set_course_menu_locates_the_live_menu():
    _helm, course, _sb12, _vesuvi = _bridge_menus_with_set_course()
    assert warp.find_set_course_menu() is course


def test_find_set_course_menu_is_none_before_the_bridge_builds_menus():
    """Must be None, not a truthy _Stub — the lookup falls back on it."""
    assert warp.find_set_course_menu() is None


def test_setting_a_course_records_the_missions_placement_on_the_button():
    """THE missing link: E1M1 calls LinkMenuToPlacement at mission load, long
    before the player plots the course. The override has to survive that gap,
    which it does by living on the menu until the course is set."""
    _helm, _course, sb12, _vesuvi = _bridge_menus_with_set_course()
    sb12.SetPlacementName("PlayerSpecialStart")   # what E1M1.py:673 does

    button = STWarpButton_CreateW("Warp")
    warp.set_course_placement(button, "Systems.Starbase12.Starbase12")

    assert button.GetPlacementName() == "PlayerSpecialStart"


def test_setting_a_course_to_an_unlinked_system_resets_to_the_default():
    """The button is reused for every course. Plotting Vesuvi after Starbase 12
    must not inherit Starbase 12's override."""
    _helm, _course, sb12, _vesuvi = _bridge_menus_with_set_course()
    sb12.SetPlacementName("PlayerSpecialStart")

    button = STWarpButton_CreateW("Warp")
    warp.set_course_placement(button, "Systems.Starbase12.Starbase12")
    warp.set_course_placement(button, "Systems.Vesuvi.Vesuvi")

    assert button.GetPlacementName() == DEFAULT


# ── The geometry this is all for ─────────────────────────────────────────────

def test_e1m1_arrival_is_far_enough_out_for_the_scripted_approach():
    """Against E1M1's REAL placement data, not a fixture.

    The number is the point. E1M1 stages its ending as a long approach: warp
    in, let the nav-point intercept engage in-system warp, drop out of it near
    the starbase. Intercept only engages that beyond fInSystemWarpDistance =
    295.0 GU (AI/PlainAI/Intercept.py:54), so the arrival distance is not
    cosmetic — under it, the entire beat silently does not happen.

        PlayerSpecialStart -> Starbase Nav   1784.6 GU = 312.30 km   6.0x over
        Player Start       -> Starbase Nav    529.7 GU =  92.70 km   1.8x over

    Both clear the threshold, which is why the symptom read as "the nav point
    loads far too close" rather than an outright failure.
    """
    import math
    from engine.units import GU_TO_KM

    s = App.SetClass()
    s.SetName("Starbase12")
    App.g_kSetManager.AddSet(s, "Starbase12")
    try:
        import Systems.Starbase12.Starbase12 as system
        system.LoadPlacements("Starbase12")
        import sys as _sys
        _sys.path.insert(0, "sdk/Build/scripts/Maelstrom/Episode1/E1M1")
        try:
            import E1M1_Starbase12_P as mission
        finally:
            _sys.path.remove("sdk/Build/scripts/Maelstrom/Episode1/E1M1")
        mission.LoadPlacements("Starbase12")

        def gap(placement):
            a = s.GetObject(placement).GetWorldLocation()
            b = s.GetObject("Starbase Nav").GetWorldLocation()
            return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2
                             + (a.z - b.z) ** 2)

        scripted = gap("PlayerSpecialStart")
        default = gap(DEFAULT)

        # E1M1.py:673 links Starbase 12 to PlayerSpecialStart, and that is
        # measurably a different, much longer approach than the default.
        assert scripted == pytest.approx(1784.6, abs=1.0)
        assert scripted * GU_TO_KM == pytest.approx(312.3, abs=0.5)
        assert default == pytest.approx(529.7, abs=1.0)
        assert scripted > default * 3

        # Both clear Intercept's in-system-warp threshold, so this test pins
        # the approach LENGTH, which is what actually regressed.
        assert scripted > 295.0
    finally:
        App.g_kSetManager.RemoveSet("Starbase12")
