"""Star map scene assembly and anchor resolution (pure Python, no GL)."""
import pytest

from engine.ui import star_map as sm


def _model():
    return {
        "systems": [
            {"id": "vesuvi",  "position": [0.0, 0.0, 0.0],   "module": "Systems.Vesuvi.Vesuvi1"},
            {"id": "tevron",  "position": [100.0, 0.0, 0.0],  "module": "Systems.Tevron.Tevron1"},
            {"id": "albirea", "position": [0.0, 200.0, 0.0],  "module": "Systems.Albirea.Albirea1"},
            {"id": "multi1",  "position": [999.0, 999.0, 0.0], "module": "Systems.Multi.Multi1"},
        ],
        "nebulae": [
            {"name": "Belaruz Nebula", "position": [50.0, 0.0, 0.0],
             "radius": 26.0, "color": [0.4, 0.4, 0.6]},
        ],
        "starclouds": [
            {"position": [0.0, 0.0, 300.0], "size": 90.0, "color": [0.3, 0.3, 0.3]},
        ],
    }


# --- anchor ---------------------------------------------------------------

def test_anchor_resolves_the_players_system():
    sid, pos = sm.resolve_anchor("Vesuvi6", model=_model())
    assert sid == "vesuvi"
    assert pos == (0.0, 0.0, 0.0)


def test_anchor_falls_back_to_centroid_when_unresolved():
    """Deep Space / unmapped sets have no system. A misplaced 'you are here'
    is worse than none, so the id must be None — not a guess."""
    sid, pos = sm.resolve_anchor("SomewhereUnmapped", model=_model())
    assert sid is None
    # centroid of the three real systems (multi* excluded)
    assert pos == pytest.approx((100.0 / 3.0, 200.0 / 3.0, 0.0))


def test_anchor_handles_an_empty_model():
    sid, pos = sm.resolve_anchor("Vesuvi6", model={"systems": [], "nebulae": [], "starclouds": []})
    assert sid is None
    assert pos == (0.0, 0.0, 0.0)


# --- scene ----------------------------------------------------------------

def test_scene_excludes_multiplayer_systems():
    scene = sm.build_scene(model=_model())
    ids = [p["id"] for p in scene["points"]]
    assert "multi1" not in ids
    assert set(ids) == {"vesuvi", "tevron", "albirea"}


def test_brackets_only_for_live_relationships():
    """The reticle means 'a live relationship to the player right now'.
    Everything else is a bare dot."""
    scene = sm.build_scene(model=_model(), here_id="vesuvi",
                           course_id="tevron", mission_ids=("albirea",))
    marks = {b["id"]: b["mark"] for b in scene["brackets"]}
    assert marks == {"vesuvi": sm.MARK_HERE,
                     "tevron": sm.MARK_COURSE,
                     "albirea": sm.MARK_MISSION}


def test_no_brackets_when_nothing_is_live():
    scene = sm.build_scene(model=_model())
    assert scene["brackets"] == []


def test_course_line_runs_from_here_to_destination():
    """Lines are reserved for the plotted course."""
    scene = sm.build_scene(model=_model(), here_id="vesuvi", course_id="tevron")
    course = [ln for ln in scene["lines"] if ln["kind"] == "course"]
    assert len(course) == 1
    assert course[0]["a"] == (0.0, 0.0, 0.0)
    assert course[0]["b"] == (100.0, 0.0, 0.0)


def test_no_course_line_without_a_known_origin():
    """Course set but position unknown must not draw a line from the origin."""
    scene = sm.build_scene(model=_model(), here_id=None, course_id="tevron")
    assert [ln for ln in scene["lines"] if ln["kind"] == "course"] == []


def test_drop_lines_only_for_reticled_systems():
    scene = sm.build_scene(model=_model(), here_id="vesuvi", course_id="tevron")
    drops = {ln["id"] for ln in scene["lines"] if ln["kind"] == "drop"}
    assert drops == {"vesuvi", "tevron"}


def test_nebulae_are_subdued():
    scene = sm.build_scene(model=_model())
    neb = next(d for d in scene["discs"] if d["kind"] == "nebula")
    assert neb["opacity"] == pytest.approx(sm.NEBULA_OPACITY)
    assert sm.NEBULA_OPACITY <= 0.5
    assert neb["label"] == "Belaruz Nebula"


def test_discs_sort_back_to_front_by_camera_distance():
    """Ordering is decided here, not in C++ — so it is testable."""
    scene = sm.build_scene(model=_model(), eye=(0.0, 0.0, 0.0))
    dists = [d["_camera_distance"] for d in scene["discs"]]
    assert dists == sorted(dists, reverse=True)


def test_points_carry_display_labels():
    scene = sm.build_scene(model=_model())
    vesuvi = next(p for p in scene["points"] if p["id"] == "vesuvi")
    assert vesuvi["label"]  # display_label, never empty
