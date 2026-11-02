"""Presentation code never draws from a gameplay stream (presentation RNG;
map docs/reference/engine/native-combat/rng-map.md §7.5 test 6).

The gameplay streams are the SDK's ``App.g_kSystemWrapper.GetRandomNumber``
(S1) and Python's process-global ``random`` (S2). A presentation module, or a
presentation function of a mixed module, draws the presentation generator
(``engine.appc.presentation_rng``) instead, or runs SDK code inside its
``scope()``. Parsed, not grepped: a docstring naming GetRandomNumber is fine,
a call is not.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Whole modules that only present.
PRESENTATION_MODULES = (
    "engine/appc/hull_hit_smoke.py",
    "engine/appc/particles.py",
    "engine/appc/viewscreen_static.py",
    "engine/rocks/minor_contact.py",
    "engine/appc/crew_speech.py",
    "engine/bridge_idle_gestures.py",
    "engine/bridge_hit_reactions.py",
    "engine/compat/fx_api/NanoFX_Lib.py",
    "engine/compat/fx_api/NanoFX_ScriptActions.py",
)

# Functions of a presentation module that write physics, so draw gameplay.
GAMEPLAY_FUNCTIONS = {
    "engine/compat/fx_api/NanoFX_Lib.py": ("CreateRotationSeq",),
    "engine/compat/fx_api/NanoFX_ScriptActions.py": ("SetNanoRotation",),
}

# The presentation functions of modules that also hold gameplay draws.
# roll_blast_scale names no stream itself: its caller (_fire) passes S1 for a
# damaging blast and P for one that only shows, and the cascade's S1 pin
# (test_death_cascade) checks that choice.
PRESENTATION_FUNCTIONS = {
    "engine/appc/death_cascade.py": ("roll_blast_scale", "_fire_final",
                                     "_debris_explosion", "_death_sound",
                                     "_light", "_tune"),
    "engine/appc/hit_feedback.py": ("_play_audio", "_pick_sound"),
}

# The cascade's own S1 helper (death_cascade._rand) is a gameplay stream too.
_GAMEPLAY_NAMES = {"_rand"}


def _gameplay_draws(tree):
    """(line, what) for every gameplay-stream reference in `tree`."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "GetRandomNumber":
            found.append((node.lineno, "GetRandomNumber"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "random":
                    found.append((node.lineno, "import random"))
        elif isinstance(node, ast.ImportFrom) and node.module == "random":
            found.append((node.lineno, "from random import"))
        elif isinstance(node, ast.Name) and node.id in _GAMEPLAY_NAMES:
            found.append((node.lineno, node.id))
    return found


def _parse(rel):
    return ast.parse((ROOT / rel).read_text(), filename=rel)


@pytest.mark.parametrize("rel", PRESENTATION_MODULES)
def test_presentation_module_draws_no_gameplay_stream(rel):
    tree = _parse(rel)
    exempt = GAMEPLAY_FUNCTIONS.get(rel, ())
    tree.body = [n for n in tree.body
                 if not (isinstance(n, ast.FunctionDef) and n.name in exempt)]
    assert _gameplay_draws(tree) == [], rel


@pytest.mark.parametrize("rel,name", [
    (rel, name) for rel, names in GAMEPLAY_FUNCTIONS.items()
    for name in names])
def test_physics_writer_draws_the_gameplay_stream(rel, name):
    funcs = [n for n in ast.walk(_parse(rel))
             if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(funcs) == 1, (rel, name)
    assert [w for _l, w in _gameplay_draws(funcs[0])] == ["GetRandomNumber"]


@pytest.mark.parametrize("rel,name", [
    (rel, name) for rel, names in PRESENTATION_FUNCTIONS.items()
    for name in names])
def test_presentation_function_draws_no_gameplay_stream(rel, name):
    funcs = [n for n in ast.walk(_parse(rel))
             if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(funcs) == 1, (rel, name)
    assert _gameplay_draws(funcs[0]) == [], (rel, name)


def test_the_guard_sees_a_gameplay_draw():
    """The guard itself: each form it forbids is found."""
    src = ("import random\n"
           "from random import choice\n"
           "def f():\n"
           "    App.g_kSystemWrapper.GetRandomNumber(3)\n"
           "    return _rand(4)\n")
    assert [w for _l, w in _gameplay_draws(ast.parse(src))] == [
        "import random", "from random import", "GetRandomNumber", "_rand"]
