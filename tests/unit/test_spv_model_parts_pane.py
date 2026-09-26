"""The Model Parts pane: collapsed by default, 25% when open.

It lists part CANDIDATES -- the children of Scene Root -- because a real hull's
node list is mostly __NDL_MultiMtl_Node exporter plumbing. A 'show all' toggle
is the escape hatch for a hull whose hierarchy does not fit the rule.
"""
from engine.ui import ship_property_viewer as spv


def _nodes():
    return [
        {"name": "head", "parent": "Scene Root", "candidate": True,
         "bounds_min": (-0.1, 0.13, -0.08), "bounds_max": (0.1, 0.9, 0.07)},
        {"name": "left wing", "parent": "Scene Root", "candidate": True,
         "bounds_min": (-1.02, -0.67, -0.71), "bounds_max": (-0.12, 0.53, 0.18)},
        {"name": "__NDL_MultiMtl_Node", "parent": "left wing", "candidate": False,
         "bounds_min": (-1.02, -0.67, -0.71), "bounds_max": (-0.12, 0.53, 0.18)},
    ]


def test_the_pane_starts_collapsed():
    """Mark's requirement: the header is visible, the list is not."""
    assert spv.model_parts_expanded() is False


def test_only_candidates_are_listed_by_default():
    rows = spv.model_part_rows(_nodes(), show_all=False)
    names = [r["name"] for r in rows]
    assert names == ["head", "left wing"]
    assert "__NDL_MultiMtl_Node" not in names, (
        "exporter plumbing must not reach the author")


def test_show_all_is_the_escape_hatch():
    rows = spv.model_part_rows(_nodes(), show_all=True)
    assert "__NDL_MultiMtl_Node" in [r["name"] for r in rows]


def test_selecting_a_part_exposes_its_derived_box():
    """The box is what severance will actually test against; the author must
    see it before committing to a detach fraction."""
    spv.select_model_part("left wing", _nodes())
    box = spv.selected_part_box()
    assert box == ((-1.02, -0.67, -0.71), (-0.12, 0.53, 0.18))


def test_selection_survives_a_list_refresh():
    spv.select_model_part("left wing", _nodes())
    spv.model_part_rows(_nodes(), show_all=False)
    assert spv.selected_model_part() == "left wing"


def test_selecting_a_vanished_part_clears_rather_than_raises():
    """A mission swap can replace the model under the panel."""
    spv.select_model_part("left wing", _nodes())
    spv.model_part_rows([], show_all=False)
    assert spv.selected_model_part() is None
