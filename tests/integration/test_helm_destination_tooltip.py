"""Kiska's "Destination :" tooltip line, headless, on a real mission.

BC's HelmUpdateToolTip (SDK BridgeHandlers.py:1379-1420) writes status key 3
as "Destination :" + the name of the Set Course row whose region is the warp
button's destination, found by FindCourseButton walking
SortedRegionMenu_GetRoot(). That walk never resolved, so the line never
showed. These drive the whole path the game uses: the host loop's tooltip
dispatch runs the REAL SDK handler, and the crew tooltip panel draws the rows.
"""
import App
from engine.appc.characters import CharacterClass_SetCurrentToolTipOwner
from engine.ui import tooltip_dispatch
from engine.ui.character_tooltip_panel import CharacterTooltipPanel
from tests.helpers import headless_mission as hm


def _helm():
    return App.CharacterClass_GetObject(App.g_kSetManager.GetSet("bridge"), "Helm")


def _tooltip_rows(helm):
    tooltip_dispatch.run_update_tooltip(helm, now=0.0, state={})
    CharacterClass_SetCurrentToolTipOwner(helm)
    try:
        return CharacterTooltipPanel().snapshot()["rows"]
    finally:
        CharacterClass_SetCurrentToolTipOwner(None)


def test_e3m2_plotted_region_shows_as_the_helm_destination():
    hm.load("Maelstrom.Episode3.E3M2.E3M2")
    helm = _helm()
    assert helm is not None

    hm.plot_course(hm.the_warp_button(), "Systems.Vesuvi.Vesuvi4")

    assert "Destination : Vesuvi Dust Cloud" in _tooltip_rows(helm)


def test_e3m2_system_row_course_names_its_default_region():
    """A click on the Vesuvi system row plots its default, Vesuvi6
    (Systems/Utils.py:24); the tooltip names the region row that leads
    there, as FindCourseButton only matches leaves."""
    hm.load("Maelstrom.Episode3.E3M2.E3M2")
    helm = _helm()

    hm.plot_course(hm.the_warp_button(), "Systems.Vesuvi.Vesuvi6")

    assert "Destination : Haven Colony" in _tooltip_rows(helm)


# ── Dauntless fallback: a course no Set Course row lists ─────────────────────
# BC could only set a course from Set Course, so FindCourseButton always found
# a row. Our star map can plot anywhere in its catalog; when the SDK finds no
# row we name the destination the way Systems/Utils.py:82-84 names a region
# row (SetClass_MakeDisplayName of the region module's set name).

def test_e3m2_unlisted_course_is_named_like_a_region_row():
    hm.load("Maelstrom.Episode3.E3M2.E3M2")
    helm = _helm()

    hm.plot_course(hm.the_warp_button(), "Systems.Belaruz.Belaruz1")

    assert "Destination : Belaruz 1" in _tooltip_rows(helm)


def test_e3m2_switching_to_an_unlisted_course_replaces_the_old_line():
    """The SDK leaves key 3 alone when it finds no row, so without the
    fallback the previous course's name would stay on screen."""
    hm.load("Maelstrom.Episode3.E3M2.E3M2")
    helm = _helm()
    button = hm.the_warp_button()
    hm.plot_course(button, "Systems.Vesuvi.Vesuvi4")
    assert "Destination : Vesuvi Dust Cloud" in _tooltip_rows(helm)

    hm.plot_course(button, "Systems.Belaruz.Belaruz1")

    rows = _tooltip_rows(helm)
    assert "Destination : Belaruz 1" in rows
    assert "Destination : Vesuvi Dust Cloud" not in rows


def _boot_quickbattle(monkeypatch):
    from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader
    _hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.session = controller.loader.load_quickbattle()
    return controller


def test_quickbattle_star_map_course_shows_its_destination(monkeypatch):
    """QuickBattle lists no Set Course rows; the star map plots from its
    catalog (star_map_panel._offered_rows -> None)."""
    _boot_quickbattle(monkeypatch)
    helm = _helm()
    assert helm is not None

    hm.plot_course(hm.the_warp_button(), "Systems.Vesuvi.Vesuvi4")

    assert "Destination : Vesuvi Dust Cloud" in _tooltip_rows(helm)


def test_quickbattle_no_course_no_destination_line(monkeypatch):
    _boot_quickbattle(monkeypatch)
    helm = _helm()
    assert not hm.the_warp_button().GetDestination()

    assert not any(r.startswith("Destination") for r in _tooltip_rows(helm))


def test_e3m2_no_course_no_destination_line():
    hm.load("Maelstrom.Episode3.E3M2.E3M2")
    helm = _helm()
    assert not hm.the_warp_button().GetDestination()

    rows = _tooltip_rows(helm)

    assert rows, "the Helm tooltip should still show speed and location"
    assert not any(r.startswith("Destination") for r in rows)
