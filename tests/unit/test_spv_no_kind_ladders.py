"""Guard: per-kind tool dispatch lives only in ``spv_edit_targets.py``.

Every Ship Property Viewer tool is written once against a per-kind
``EditTarget`` adapter. A comparison of a target kind against a kind
literal in the panel modules is a ladder creeping back. Event-prefix
matching (``startswith("select_light:")``) is not a kind comparison.
"""
import ast
import pathlib

KINDS = {"subsystem", "light", "emitter", "part_anchor", "part_pose", "decal"}
FILES = ["engine/ui/ship_property_viewer_panel.py", "engine/ui/spv_decals_pane.py"]


def _kind_compares(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for c in [node.left, *node.comparators]:
                if isinstance(c, ast.Constant) and c.value in KINDS:
                    yield node.lineno


def test_no_per_kind_ladders_outside_edit_targets():
    root = pathlib.Path(__file__).resolve().parents[2]
    hits = {f: list(_kind_compares(ast.parse((root / f).read_text())))
            for f in FILES}
    assert all(not v for v in hits.values()), hits
