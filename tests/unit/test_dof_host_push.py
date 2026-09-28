"""The host must push DOF params from the same place it sets the camera.

This is the seam where a feature silently dies: the solver can be perfect and
the shader can be perfect, and if nothing calls set_dof_params the effect
simply never happens with every test still green.
"""
import ast
import pathlib

HOST_LOOP = pathlib.Path(__file__).resolve().parents[2] / "engine" / "host_loop.py"


def _block_of_each_call(node, out, block=None):
    """Map every Call in `node` to the innermost statement list containing it.

    Recurses outer-block-first, so a nested block overwrites the provisional
    outer assignment and each call ends up owned by its TIGHTEST block.
    """
    for field in ("body", "orelse", "finalbody"):
        lst = getattr(node, field, None)
        if not isinstance(lst, list):
            continue
        for stmt in lst:
            if not isinstance(stmt, ast.stmt):
                continue
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Call):
                    out[id(sub)] = id(lst)
            _block_of_each_call(stmt, out)
    return out


def _calls_named(tree, name):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if ((isinstance(fn, ast.Attribute) and fn.attr == name)
                    or (isinstance(fn, ast.Name) and fn.id == name)):
                out.append(node)
    return out


# Every SPACE camera reaches the renderer through host_loop._push_space_camera
# (render space: eye/target minus the render origin, system-frames Plan 3
# Task 6), so that is the call the exterior-solve structure is read from.
SPACE_CAMERA = "_push_space_camera"


def test_host_loop_pushes_dof_params():
    tree = ast.parse(HOST_LOOP.read_text())
    assert _calls_named(tree, "set_dof_params"), (
        "host_loop never calls r.set_dof_params -- DOF would be inert"
    )


def test_dof_push_sits_in_the_same_block_as_the_exterior_set_camera():
    """The push must run beside the exterior camera solve, not in some
    unrelated branch: it needs THAT frame's eye position to measure the
    subject, and `eye` is a local of the block they share.

    Asserted STRUCTURALLY -- same innermost statement list -- rather than as a
    line-distance budget. The budget version was a proxy for this, and a bad
    one in both directions: it tripped on a comment added between the two
    calls while nothing moved branch, and it could not tell the exterior
    solve from the bridge one except by accident of spacing. This check can
    tell them apart by construction, and no amount of prose between the calls
    can break it.
    """
    tree = ast.parse(HOST_LOOP.read_text())
    blocks = _block_of_each_call(tree, {})
    cam_blocks = {blocks[id(c)] for c in _calls_named(tree, SPACE_CAMERA)}
    dof_blocks = {blocks[id(c)] for c in _calls_named(tree, "set_dof_params")}
    assert dof_blocks, "no set_dof_params call"
    assert cam_blocks & dof_blocks, (
        "set_dof_params does not share a block with any set_camera call"
    )


def test_the_bridge_camera_solve_is_a_different_block():
    """Guards the test above from degenerating into a tautology. host_loop has
    more than one set_camera; if they all shared one block, the check would
    pass no matter where the DOF push sat. The bridge solve is deliberately
    elsewhere, so the set intersection above is load-bearing."""
    tree = ast.parse(HOST_LOOP.read_text())
    blocks = _block_of_each_call(tree, {})
    cam_blocks = {blocks[id(c)] for c in _calls_named(tree, SPACE_CAMERA)}
    assert len(cam_blocks) > 1, (
        "every set_camera shares one block -- the same-block assertion above "
        "no longer distinguishes the exterior solve from any other"
    )


def test_host_loop_constructs_a_focus_solver():
    src = HOST_LOOP.read_text()
    assert "FocusSolver()" in src, "no FocusSolver constructed"


def test_focus_solver_assignment_is_module_level_not_local():
    """_focus_solver must be a top-level module attribute, not a local built
    inside some function or class -- that is exactly the property the dev
    keybindings depend on. dev_keybindings resolves it via
    getattr(host_loop, "_focus_solver", None); if the assignment moved inside
    def run(...) (or any other function/class body), that getattr would
    silently and permanently return None and the live tuning keys would do
    nothing, with every other test still green.

    Checking `ast.parse(...).body` (not `ast.walk`) is the point: walk finds
    an assignment nested arbitrarily deep, which is exactly what this test
    must reject.
    """
    tree = ast.parse(HOST_LOOP.read_text())
    top_level_assigned_names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    top_level_assigned_names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            top_level_assigned_names.add(node.target.id)

    assert "_focus_solver" in top_level_assigned_names, (
        "_focus_solver is not assigned at module scope -- "
        "dev_keybindings' getattr(host_loop, '_focus_solver', None) "
        "would silently and permanently return None"
    )
