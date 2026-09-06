"""Guard: every `keys.KEY_*` name engine/ reads MUST exist on the real module.

Why this file exists
--------------------
`_dauntless_host.keys` is a hand-maintained wall of `keys.attr("KEY_X") =
GLFW_KEY_X` lines in native/src/host/host_bindings.cc. Nothing linked it to the
Python that reads it, so a `_h.keys.KEY_FOO` with no matching line in the .cc is
not a compile error, not an import error, and not a test failure -- it is an
`AttributeError` raised at the exact moment the feature is first exercised, live.

That has now bitten this project twice:

  * a guest-crew-menu F6 binding was a dead key because `KEY_F6` was never
    exported (see project_guest_crew_menu);
  * the depth-of-field live-tuning keys read `KEY_COMMA` / `KEY_PERIOD`, which
    host_bindings.cc did not export. `register_for_frame()` runs every tick under
    --developer inside a `try` with no `except`, so the first developer-mode tick
    would have terminated the process -- before any live look at DOF, and taking
    the mission picker and Developer Options down with it. The symptom was even
    seen (the test double in test_dev_keybindings.py had to grow the constants)
    and fixed in the DOUBLE rather than chased to the real surface.

`engine/renderer.py`'s `_REQUIRED_BINDINGS` manifest covers the same class of
failure, but its jurisdiction stops at `_h.<name>` and never reaches inside the
`keys` submodule. This is that manifest's missing half.

Ground truth is derived from the source, by AST -- not a hand-kept list that can
drift, and not a regex, which would both over-match (`_h.keys.KEY_X` inside a
docstring or a comment) and under-match (an alias bound to the submodule). This
is the same parse-don't-grep discipline as tests/unit/test_path_indirection.py.

A key that is deliberately OPTIONAL must be reached through
`getattr(keys, "KEY_X", default)` / `hasattr(...)` with a string literal -- the
existing style everywhere in engine/ -- which carries its own fallback and is
therefore invisible to (and out of scope for) this guard.
"""
import ast
import pathlib

import pytest

_ENGINE = pathlib.Path(__file__).resolve().parents[2] / "engine"

# A `keys` submodule reference is spelled either `<expr>.keys.KEY_X` (the
# `_h.keys` / `h.keys` / `host.keys` form) or bare `keys.KEY_X` / `_keys.KEY_X`
# where the submodule has been bound to a local first.
_BARE_ALIASES = ("keys", "_keys")
_PREFIXES = ("KEY_", "MOUSE_BUTTON_")


def _collect_key_refs():
    """{name: [ "path:line", ... ]} for every hard `keys.<KEY_*>` read in engine/."""
    refs: dict[str, list[str]] = {}
    for path in sorted(_ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if not node.attr.startswith(_PREFIXES):
                continue
            base = node.value
            on_keys = (
                (isinstance(base, ast.Attribute) and base.attr == "keys")
                or (isinstance(base, ast.Name) and base.id in _BARE_ALIASES)
            )
            if on_keys:
                refs.setdefault(node.attr, []).append(
                    "%s:%d" % (path.name, node.lineno))
    return refs


def test_the_collector_actually_finds_references():
    """Guard the guard. A walker that matched nothing would make the real test
    below vacuously green, which is precisely the failure mode it exists to
    catch. These three are hard reads in engine/ today."""
    refs = _collect_key_refs()
    assert len(refs) > 10, "AST walk found almost nothing — the walker is broken"
    for sentinel in ("KEY_COMMA", "KEY_F10", "MOUSE_BUTTON_LEFT"):
        assert sentinel in refs, "%s is read in engine/ but was not collected" % sentinel


def test_every_key_engine_reads_exists_on_the_native_module():
    """The one that matters: no `keys.KEY_X` in engine/ may be a dead key."""
    host = pytest.importorskip(
        "_dauntless_host",
        reason="native extension not built — nothing to check the manifest against",
    )
    keys = getattr(host, "keys", None)
    assert keys is not None, "_dauntless_host has no `keys` submodule at all"

    missing = {
        name: sites for name, sites in _collect_key_refs().items()
        if not hasattr(keys, name)
    }
    assert not missing, (
        "engine/ reads key constant(s) that _dauntless_host.keys does NOT "
        "export. Each is a dead key that raises AttributeError the moment the "
        "feature runs. Add them next to the other keys.attr(\"KEY_*\") lines in "
        "native/src/host/host_bindings.cc and rebuild the default target:\n"
        + "\n".join("  %s  <- %s" % (n, ", ".join(s)) for n, s in sorted(missing.items()))
    )
