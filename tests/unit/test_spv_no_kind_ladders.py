"""Guard: per-kind tool dispatch lives only in ``spv_edit_targets.py``.

Every Ship Property Viewer tool is written once against a per-kind
``EditTarget`` adapter. A comparison of a target kind against a kind
literal in the panel modules is a ladder creeping back. Event-prefix
matching (``startswith("select_light:")``) is not a kind comparison.

Flagged shapes (each has a self-test below, so the guard itself is tested):
a kind literal in a comparison -- directly or inside a tuple/list/set
comparator (``x in ("light", "emitter")``); a kind literal as a dict key;
``.startswith(<kind>)`` / ``.startswith("part_")``; ``isinstance(..., <Name
ending in "Target">)``; and any call to ``_decal_target(`` (the decal-only
selection probe -- ask the adapter instead).
"""
import ast
import pathlib

import pytest

KINDS = {"subsystem", "light", "emitter", "part_anchor", "part_pose", "decal"}
KIND_PREFIXES = KINDS | {"part_"}
FILES = ["engine/ui/ship_property_viewer_panel.py",
         "engine/ui/spv_decals_pane.py",
         "engine/ui/ship_property_viewer.py"]


def _is_kind(node, kinds=KINDS):
    return isinstance(node, ast.Constant) and node.value in kinds


def _kind_elts(node, kinds=KINDS):
    """True when `node` is a kind literal, or a tuple/list/set holding one."""
    if _is_kind(node, kinds):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_is_kind(e, kinds) for e in node.elts)
    return False


def _names_target(node):
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_names_target(e) for e in node.elts)
    if isinstance(node, ast.Name):
        return node.id.endswith("Target")
    if isinstance(node, ast.Attribute):
        return node.attr.endswith("Target")
    return False


def _ladder_hits(tree):
    """(lineno, reason) for every per-kind ladder shape in `tree`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            if any(_kind_elts(c) for c in [node.left, *node.comparators]):
                yield node.lineno, "kind compare"
        elif isinstance(node, ast.Dict):
            if any(k is not None and _is_kind(k) for k in node.keys):
                yield node.lineno, "kind dict key"
        elif isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr == "startswith"
                    and node.args and _kind_elts(node.args[0], KIND_PREFIXES)):
                yield node.lineno, "kind startswith"
            elif (isinstance(f, ast.Name) and f.id == "isinstance"
                    and len(node.args) == 2 and _names_target(node.args[1])):
                yield node.lineno, "isinstance Target"
            elif ((isinstance(f, ast.Attribute) and f.attr == "_decal_target")
                    or (isinstance(f, ast.Name) and f.id == "_decal_target")):
                yield node.lineno, "_decal_target call"


def _hits(src):
    return [r for _, r in _ladder_hits(ast.parse(src))]


@pytest.mark.parametrize("src,reason", [
    ('t.kind == "light"', "kind compare"),
    ('t[0] != "emitter"', "kind compare"),
    ('x in ("light", "emitter")', "kind compare"),
    ('x in ["part_pose"]', "kind compare"),
    ('x not in {"decal"}', "kind compare"),
    ('d = {"subsystem": 1}', "kind dict key"),
    ('k.startswith("part_")', "kind startswith"),
    ('k.startswith("emitter")', "kind startswith"),
    ('k.startswith(("light", "decal"))', "kind startswith"),
    ('isinstance(t, DecalTarget)', "isinstance Target"),
    ('isinstance(t, m.LightTarget)', "isinstance Target"),
    ('isinstance(t, (int, EmitterTarget))', "isinstance Target"),
    ('self._decal_target()', "_decal_target call"),
    ('if self._decal_target() is not None: pass', "_decal_target call"),
])
def test_detector_flags_each_ladder_shape(src, reason):
    assert reason in _hits(src), src


@pytest.mark.parametrize("src", [
    'ev.startswith("select_light:")',        # an event prefix, not a kind
    'x in ("transform", "rotate")',          # tool names
    'd = {"kind": t.kind}',                  # a kind VALUE, not a key
    'isinstance(t, dict)',
    'self._decal_by_name(n)',
])
def test_detector_passes_non_ladders(src):
    assert _hits(src) == [], src


def test_no_per_kind_ladders_outside_edit_targets():
    root = pathlib.Path(__file__).resolve().parents[2]
    hits = {f: list(_ladder_hits(ast.parse((root / f).read_text())))
            for f in FILES}
    assert all(not v for v in hits.values()), hits
