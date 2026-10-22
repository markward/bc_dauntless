"""The old voxel carve is gone from the Python side, and stays gone.

Layered hull damage (HullDamageStore records -> plating -> interior rooms;
severance by structure part) replaced it. Phase 4 deletes the native carve
next, so a Python caller left behind would be a crash the moment its path ran.

The guard parses rather than greps, like tests/unit/test_path_indirection.py:
a grep for "carve" flags every comment that tells the history, while the
names below can only come back as CODE -- an identifier, an attribute, an
import, a keyword argument, a def, or a string constant that IS the name
(a binding manifest entry, an env var). Prose that mentions one is fine.
"""
import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

REMOVED_NAMES = frozenset({
    # The carve modules and their entry points.
    "hull_carve", "core_breach_carve", "after_carve",
    # host_io's carve wrappers, the A/B switch and its env var.
    "hull_carve_add", "hull_split_detached", "hull_carve_capsule",
    "hull_carving_enabled", "DAUNTLESS_HULL_CARVING",
    # The death cascade's capsule cut.
    "queue_world_capsule", "kCascadeCapsuleRadiusGu",
    # The per-instance hull-volume field pipeline.
    "prewarm_field", "push_resolution", "prebake_all",
    "hull_volume_set_resolution", "hull_volume_prewarm",
    "hull_volume_prewarm_model", "hull_volume_bake_to_disk",
    "hull_volume_set_cache_root",
    # The light-phaser gate's old name (now allow_structural_wear).
    "allow_hull_carve",
    # hit_feedback's carve throttle.
    "_last_carve_time", "_pending_carve_strength",
})

REMOVED_FILES = ("engine/appc/hull_carve.py", "engine/appc/core_breach_carve.py")


def _sources():
    for root in ("engine", "tools"):
        yield from sorted((PROJECT_ROOT / root).rglob("*.py"))


def _offences(tree):
    """(lineno, name) for every code use of a removed name in `tree`."""
    out = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.append(node.arg)
        elif isinstance(node, ast.alias):
            names.extend(node.name.split("."))
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.extend(node.module.split("."))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.append(node.value)
        for n in names:
            if n in REMOVED_NAMES:
                out.append((getattr(node, "lineno", 0), n))
    return out


def test_no_carve_symbols_remain():
    hits = []
    for path in _sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue   # tools/probes: Python 1.5, never engine code
        for lineno, name in _offences(tree):
            hits.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {name}")
    assert not hits, "carve code is back:\n  " + "\n  ".join(hits)


def test_the_carve_modules_are_deleted():
    present = [p for p in REMOVED_FILES if (PROJECT_ROOT / p).exists()]
    assert not present, present


def test_the_guard_sees_a_planted_use():
    """Discriminator: each code shape the guard claims to catch is caught,
    and prose is not."""
    src = (
        "from engine.appc import hull_carve\n"
        "import engine.appc.core_breach_carve\n"
        "host_io.hull_carve_add(1)\n"
        "dispatch(allow_hull_carve=True)\n"
        "def after_carve(): pass\n"
        "X = {'hull_split_detached'}\n"
        "os.environ.get('DAUNTLESS_HULL_CARVING')\n"
        "'''the old hull_carve_add path is gone'''\n"
    )
    found = {n for _l, n in _offences(ast.parse(src))}
    assert found == {"hull_carve", "core_breach_carve", "hull_carve_add",
                     "allow_hull_carve", "after_carve", "hull_split_detached",
                     "DAUNTLESS_HULL_CARVING"}
