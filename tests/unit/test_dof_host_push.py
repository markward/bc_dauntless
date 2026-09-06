"""The host must push DOF params from the same place it sets the camera.

This is the seam where a feature silently dies: the solver can be perfect and
the shader can be perfect, and if nothing calls set_dof_params the effect
simply never happens with every test still green.
"""
import ast
import pathlib

HOST_LOOP = pathlib.Path(__file__).resolve().parents[2] / "engine" / "host_loop.py"


def _calls_named(tree, name):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == name:
                out.append(node)
    return out


def test_host_loop_pushes_dof_params():
    tree = ast.parse(HOST_LOOP.read_text())
    assert _calls_named(tree, "set_dof_params"), (
        "host_loop never calls r.set_dof_params -- DOF would be inert"
    )


def test_dof_push_sits_next_to_the_exterior_set_camera():
    """The push must be near the exterior camera solve, not in some unrelated
    branch: it needs that frame's eye position to measure the subject."""
    tree = ast.parse(HOST_LOOP.read_text())
    cam_lines = [c.lineno for c in _calls_named(tree, "set_camera")]
    dof_lines = [c.lineno for c in _calls_named(tree, "set_dof_params")]
    assert dof_lines, "no set_dof_params call"
    assert any(abs(d - c) < 40 for d in dof_lines for c in cam_lines), (
        "set_dof_params is not adjacent to any set_camera call"
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
