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


def test_the_selected_star_keeps_its_emphasis_over_the_base_size():
    """Both star sizes are tuned by hand. Raising only the base would flatten
    the selected star's emphasis to nothing without failing anything else, so
    pin the RATIO rather than the two literals."""
    assert sm.STAR_SELECTED_SIZE_PX / sm.STAR_SIZE_PX == pytest.approx(1.8)


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


def test_star_clouds_share_the_nebula_colour():
    """Star clouds are terrain, like nebulae — same layer, same colour, so
    they do not read as a third thing competing with the amber systems.

    Asserted against NEBULA_COLOR rather than a literal: the point is that
    they track it, so retuning the nebulae must not silently leave the
    clusters behind."""
    scene = sm.build_scene(model=_model())
    assert scene["starclouds"]
    assert all(g["color"] == sm.NEBULA_COLOR for g in scene["starclouds"])
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


# --- one system, several states -------------------------------------------

def _one_system_marks(**kw):
    """The mark a single system ends up with when several states collide."""
    model = {"systems": [{"id": "vesuvi", "position": [0.0, 0.0, 0.0],
                          "module": "m"}],
             "nebulae": [], "starclouds": []}
    brackets = sm.build_scene(model=model, **kw)["brackets"]
    assert len(brackets) <= 1
    return brackets[0]["mark"] if brackets else None


def test_mark_precedence_is_course_then_mission_then_here():
    """A system can hold several states at once — you can set a course inside
    the system you are already in, and most systems have several regions — but
    it gets one bracket. COURSE > MISSION > HERE.

    Every pair is pinned, not just the end result: the precedence lives in the
    ORDER three lines are applied, which a later edit could reshuffle without
    changing anything else.
    """
    HERE, COURSE, MISSION = sm.MARK_HERE, sm.MARK_COURSE, sm.MARK_MISSION

    # Singles.
    assert _one_system_marks(here_id="vesuvi") == HERE
    assert _one_system_marks(course_id="vesuvi") == COURSE
    assert _one_system_marks(mission_ids=("vesuvi",)) == MISSION

    # Pairs.
    assert _one_system_marks(here_id="vesuvi",
                             mission_ids=("vesuvi",)) == MISSION
    assert _one_system_marks(here_id="vesuvi", course_id="vesuvi") == COURSE
    assert _one_system_marks(course_id="vesuvi",
                             mission_ids=("vesuvi",)) == COURSE

    # All three.
    assert _one_system_marks(here_id="vesuvi", course_id="vesuvi",
                             mission_ids=("vesuvi",)) == COURSE


def test_colliding_states_still_produce_exactly_one_drop_line():
    """The drop-line follows the bracket, so a system holding several states
    must not stack three of them."""
    model = {"systems": [{"id": "vesuvi", "position": [0.0, 0.0, 0.0],
                          "module": "m"}],
             "nebulae": [], "starclouds": []}
    scene = sm.build_scene(model=model, here_id="vesuvi", course_id="vesuvi",
                           mission_ids=("vesuvi",))
    drops = [ln for ln in scene["lines"] if ln["kind"] == "drop"]
    assert len(drops) == 1


def test_the_bracket_encloses_the_star_it_marks():
    """A reticle must surround its star, not sit on it. The two sizes are
    tuned independently, so nothing else would notice them converging — at
    one point both were 20.0 and the corners landed on the star's edge.

    Compared against the SELECTED size, the largest a star ever draws.
    """
    assert sm.BRACKET_SIZE_PX > sm.STAR_SELECTED_SIZE_PX > sm.STAR_SIZE_PX
    # Deliberately no minimum margin beyond that. An earlier version demanded
    # 1.2x, which was a number invented here rather than derived from
    # anything — it then blocked a size Mark had chosen on the screen. How
    # much air looks right is a live judgement; that the reticle encloses what
    # it marks is the part code can hold.


# --- the reference plane sits under the chart ------------------------------

def test_the_grid_is_framed_on_the_systems_not_the_world_origin():
    """The sector layout comes from a force-directed relaxation with no reason
    to settle on the origin, and it did not: the real systems centre near
    (150, 32). A plane fixed at (0, 0) sat off to one side of the chart.
    """
    model = {
        "systems": [
            {"id": "a", "position": [1000.0, 500.0, 10.0], "module": "m"},
            {"id": "b", "position": [1100.0, 700.0, 30.0], "module": "m"},
        ],
        "nebulae": [], "starclouds": [],
    }
    cx, cy, half, _z = sm.grid_bounds(sm._real_systems(model))
    assert (cx, cy) == (1050.0, 600.0)          # bbox centre, not the origin
    # Every system inside the plane, with margin.
    assert cx - half <= 1000.0 and 1100.0 <= cx + half
    assert cy - half <= 500.0 and 700.0 <= cy + half


def test_grid_cells_stay_square():
    """One half-extent drives both axes. Fitting each axis separately would
    stretch the cells into rectangles and misread as perspective."""
    model = {
        "systems": [
            {"id": "a", "position": [0.0, 0.0, 0.0], "module": "m"},
            {"id": "b", "position": [10.0, 400.0, 0.0], "module": "m"},
        ],
        "nebulae": [], "starclouds": [],
    }
    lines = sm._grid_lines(sm._real_systems(model))
    spans = {round(abs(l["a"][0] - l["b"][0]) + abs(l["a"][1] - l["b"][1]), 6)
             for l in lines}
    assert len(spans) == 1, "grid lines differ in length between axes"


def test_the_grid_floor_is_below_every_system():
    """Drop-lines fall from a star to the plane, so the plane must be under
    all of them. At a fixed z=0 the real model left systems down to z=-61
    hanging below the floor their own drop-lines fell to."""
    model = {
        "systems": [
            {"id": "a", "position": [0.0, 0.0, -61.0], "module": "m"},
            {"id": "b", "position": [10.0, 10.0, 148.0], "module": "m"},
        ],
        "nebulae": [], "starclouds": [],
    }
    systems = sm._real_systems(model)
    floor = sm.grid_bounds(systems)[3]
    assert floor < -61.0

    # ...and the drop-line lands ON that plane, not on a stale constant.
    scene = sm.build_scene(model=model, here_id="a")
    drop = next(l for l in scene["lines"] if l["kind"] == "drop")
    assert drop["b"][2] == floor
    assert drop["a"][2] == -61.0          # from the star, down to the floor


def test_grid_survives_a_model_with_no_systems():
    """The empty model must not divide by zero on its way to a degenerate
    grid."""
    scene = sm.build_scene(model={"systems": [], "nebulae": [],
                                  "starclouds": []})
    assert [l for l in scene["lines"] if l["kind"] == "grid"]


# --- offered systems: the mission's actual reach ---------------------------
# BC's Set Course menu lists only the systems the mission built (E3M2 creates
# two of the 34 charted). The map keeps drawing the whole sector for context,
# but must not present 32 stars that behave like destinations and aren't.

def _offered_scene(offered):
    return sm.build_scene(offered_ids=offered)


def test_every_system_is_offered_when_no_menu_constrains_the_map():
    """No Set Course menu (QuickBattle) means no constraint — not 'nothing
    is reachable'. Passing None must leave the map exactly as it was."""
    scene = sm.build_scene(offered_ids=None)
    assert scene["points"]
    assert all(p["offered"] for p in scene["points"])


def test_a_system_outside_the_offer_is_dimmed():
    scene = _offered_scene({"vesuvi"})
    by_id = {p["id"]: p for p in scene["points"]}
    assert by_id["vesuvi"]["offered"] is True
    other = next(p for p in scene["points"] if p["id"] != "vesuvi")
    assert other["offered"] is False
    # Dimmed to half brightness. StarMapPoint carries no alpha channel, so
    # 50% is expressed as colour against the map's dark backdrop rather than
    # as true transparency — same result, no native change.
    assert other["color"] == tuple(c * sm.INERT_DIM
                                   for c in sm.STAR_COLOR)


def test_an_unoffered_star_cannot_be_picked():
    """The dimming is the cue; this is the behaviour behind it. Without this
    a player learns the offer by clicking 32 dead stars."""
    scene = _offered_scene({"vesuvi"})
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    rect = (0, 0, 880, 478)
    target = next(p for p in sm.project_points(scene, cam, rect)
                  if p["visible"] and p["id"] != "vesuvi")
    assert sm.pick_system(target["x"], target["y"],
                                scene, cam, rect) != target["id"]


def test_a_system_you_are_in_is_never_dimmed_even_if_unoffered():
    """You can be sitting in a system this mission plots no course back to.
    Dimming the you-are-here star to say 'not a destination' costs the player
    the one marker they always need — a live relationship outranks the offer.
    """
    scene = sm.build_scene(model=_model(), here_id="tevron",
                           offered_ids={"vesuvi"})
    by_id = {p["id"]: p for p in scene["points"]}
    assert by_id["tevron"]["color"] == sm.STAR_COLOR
    assert by_id["albirea"]["color"] != sm.STAR_COLOR   # genuinely inert
