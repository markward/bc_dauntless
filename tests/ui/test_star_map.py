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
            # TWO nebulae, at different camera distances. One is not enough:
            # star clouds are no longer discs, so a single-element list would
            # make the back-to-front sort assertion pass vacuously.
            {"name": "Belaruz Nebula", "position": [50.0, 0.0, 0.0],
             "radius": 26.0, "color": [0.4, 0.4, 0.6]},
            # Deliberately UNNAMED and nearer than Belaruz: gives the
            # back-to-front sort two elements to order (star clouds are no
            # longer discs, so one would make it vacuous) while also
            # exercising the empty-label skip in project_disc_labels.
            {"name": "", "position": [20.0, 0.0, 0.0],
             "radius": 14.0, "color": [0.6, 0.4, 0.4]},
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


def test_brackets_carry_their_own_colour_and_size():
    """Presentation crosses the boundary as VALUES, not as a mark the pass
    re-interprets. If the renderer chose colours from `mark`, renumbering
    MARK_* here would silently recolour every reticle."""
    scene = sm.build_scene(model=_model(), here_id="vesuvi",
                           course_id="tevron", mission_ids=("albirea",))
    colors = {b["id"]: b["color"] for b in scene["brackets"]}
    assert colors == {"vesuvi": sm.MARK_HERE_COLOR,
                      "tevron": sm.MARK_COURSE_COLOR,
                      "albirea": sm.MARK_MISSION_COLOR}
    assert all(b["size_px"] == sm.BRACKET_SIZE_PX for b in scene["brackets"])


def test_every_mark_has_a_colour():
    """A mark with no colour must fail loudly in build_scene, not render as a
    plausible grey. Guards MARK_* and _MARK_COLORS against drifting apart."""
    live = {sm.MARK_HERE, sm.MARK_COURSE, sm.MARK_MISSION}
    assert set(sm._MARK_COLORS) == live
    assert sm.MARK_NONE not in sm._MARK_COLORS   # never reticled


def test_selected_point_is_bigger_and_sized_in_python():
    """`selected` is this module's semantics; the pixel size it implies is
    resolved here so the renderer never derives size from the flag."""
    scene = sm.build_scene(model=_model(), selected_id="tevron")
    by_id = {p["id"]: p for p in scene["points"]}
    assert by_id["tevron"]["size_px"] == sm.STAR_SELECTED_SIZE_PX
    assert by_id["vesuvi"]["size_px"] == sm.STAR_SIZE_PX
    assert sm.STAR_SELECTED_SIZE_PX > sm.STAR_SIZE_PX


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
    assert len(dists) >= 2, "sort assertion is vacuous with fewer than 2 discs"
    assert dists == sorted(dists, reverse=True)
    # Farthest first: the near nebula must not be drawn before the far one.
    assert dists[0] > dists[-1]


def test_star_clouds_are_screen_scaled_glyphs_not_discs():
    """At their model `size` (up to ~92) star clouds were world-scaled blobs
    that swallowed whole regions. They are decoration: a fixed pixel size,
    carried in their own list so they never sort or scale with the nebulae."""
    scene = sm.build_scene(model=_model())
    assert all(d["kind"] == "nebula" for d in scene["discs"])
    assert scene["starclouds"], "model has a star cloud"
    for g in scene["starclouds"]:
        assert g["size_px"] == sm.STARCLOUD_SIZE_PX
        assert "radius" not in g


def test_multiplayer_scaffolding_nebulae_are_not_charted():
    """MRegion* nebulae belong to the multiplayer maps, like the `multi*`
    systems already dropped. They are not course destinations, so they do not
    belong on the chart — and one of them was the saturated green that
    dominated the map."""
    model = _model()
    model["nebulae"] = model["nebulae"] + [
        {"name": "MRegion5 Nebula", "position": [10.0, 10.0, 0.0],
         "radius": 30.0, "color": [0.12, 0.75, 0.12]},
        {"name": "MRegion6 Nebula", "position": [-10.0, 10.0, 0.0],
         "radius": 30.0, "color": [0.12, 0.12, 0.75]},
    ]
    scene = sm.build_scene(model=model)
    labels = [d["label"] for d in scene["discs"]]
    assert not any("mregion" in l.lower() for l in labels), labels
    # The real ones survive — this must not filter everything.
    assert "Belaruz Nebula" in labels


def test_every_nebula_takes_the_one_map_colour():
    """The model's per-nebula tints are in-scene backdrop colours and several
    are saturated primaries, which read as alarm states on a chart. The map
    overrides them all with one muted colour. The fixture's two nebulae carry
    DIFFERENT model colours, so this fails if either is passed through."""
    scene = sm.build_scene(model=_model())
    assert len({d["color"] for d in scene["discs"]}) == 1
    assert all(d["color"] == sm.NEBULA_COLOR for d in scene["discs"])


def test_nebulae_carry_a_separate_border_opacity():
    """A charted region is a faint fill inside a CRISP boundary — the fill
    and the border are independent, and the border is the stronger of the
    two. Collapsing them back to one alpha returns the soft-cloud look."""
    scene = sm.build_scene(model=_model())
    neb = scene["discs"][0]
    assert neb["opacity"] == sm.NEBULA_OPACITY
    assert neb["border_opacity"] == sm.NEBULA_BORDER_OPACITY
    assert sm.NEBULA_BORDER_OPACITY > sm.NEBULA_OPACITY


def test_points_carry_display_labels():
    scene = sm.build_scene(model=_model())
    vesuvi = next(p for p in scene["points"] if p["id"] == "vesuvi")
    assert vesuvi["label"]  # display_label, never empty


# --- disc labels ----------------------------------------------------------
#
# The baked `name` on every nebula existed with no consumer at all: build_scene
# copied it to disc["label"], project_points iterated scene["points"] only, and
# the payload's labels list was systems-only. A producer spanning four task
# boundaries with nothing reading it.

def test_disc_labels_are_projected_for_named_discs_only():
    """Star clouds carry no name and must not emit an empty label div."""
    scene = sm.build_scene(model=_model())
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    labels = sm.project_disc_labels(scene, cam, (0, 0, 640, 478))
    assert [d["label"] for d in labels] == ["Belaruz Nebula"]


def test_a_nameless_nebula_emits_no_label():
    """`name` can be absent or null in the source map; the scene must skip it
    rather than let the JS render the string 'null' over the map."""
    model = _model()
    model["nebulae"] = [{"name": None, "position": [10.0, 0.0, 0.0],
                         "radius": 5.0, "color": [0.4, 0.4, 0.6]},
                        {"position": [20.0, 0.0, 0.0],
                         "radius": 5.0, "color": [0.4, 0.4, 0.6]}]
    scene = sm.build_scene(model=model)
    assert [d["label"] for d in scene["discs"] if d["kind"] == "nebula"] == ["", ""]
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    assert sm.project_disc_labels(scene, cam, (0, 0, 640, 478)) == []


def test_disc_labels_use_the_same_rect_local_shape_as_system_labels():
    """Both lists are positioned inside #star-map-viewport by the same CSS, so
    they must be in the same rect-local coordinate space."""
    scene = sm.build_scene(model=_model())
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    rect = (200, 108, 640, 478)
    entry = sm.project_disc_labels(scene, cam, rect)[0]
    assert set(entry) == {"label", "x", "y", "visible"}
    assert 0.0 <= entry["x"] <= 640.0 and 0.0 <= entry["y"] <= 478.0
    assert entry["visible"] is True


def test_quickbattle_anchors_on_deep_space_with_a_here_reticle():
    """The two symptoms Mark reported — orbit not centred on the player, and
    no bracket on the current system — were ONE root cause: an unresolved set
    returns (None, centroid), which anchors on the centroid and deliberately
    omits the reticle. QuickBattle's set is Deep Space on the map."""
    model = {
        "systems": [
            {"id": "deepspace", "position": [10.0, 20.0, 30.0], "module": "m"},
            {"id": "vesuvi", "position": [-100.0, 0.0, 0.0], "module": "m"},
        ],
        "nebulae": [], "starclouds": [],
    }
    sid, pos = sm.resolve_anchor("QuickBattleRegion", model=model)
    assert sid == "deepspace"
    assert pos == (10.0, 20.0, 30.0)          # the system, not the centroid

    scene = sm.build_scene(model=model, here_id=sid)
    here = [b for b in scene["brackets"] if b["mark"] == sm.MARK_HERE]
    assert len(here) == 1
    assert here[0]["id"] == "deepspace"
