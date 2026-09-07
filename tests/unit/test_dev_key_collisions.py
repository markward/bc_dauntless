"""No developer keybinding may sit on a key the player already uses.

WHY THIS EXISTS. The DOF live-tuning keys first shipped on `-` and `=`, which
are `camera_zoom_out` / `camera_zoom_in`. Pressing them zoomed the view while
nudging the lens, which made the effect impossible to judge in flight and cost
a live test session.

The check that missed it compared `input_map.ACTIONS` against the names
`"KEY_MINUS"` / `"KEY_EQUAL"` — but that table stores **display** names
(`"-"`, `"="`), so nothing matched and the keys looked free. This test does the
mapping properly, in the one direction that cannot silently return "free".

A key can be claimed in FOUR separate namespaces, and a dev binding must dodge
all of them:
  1. `input_map.ACTIONS`        — rebindable player actions (display names)
  2. the dev keybindings        — each other
  3. direct `key_pressed()`     — throttle 1-9, F12, handled in host_loop
  4. SDK `WC_` routing          — F6/F9 forwarded to the game's own scripts

This test covers 1 and 2 exhaustively and pins 3 and 4 as a named list, since
those are read positionally rather than through any registry.
"""
import ast
import pathlib

from engine import input_map

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEV_KEYBINDINGS = _ROOT / "engine" / "dev_keybindings.py"


def _registered_dev_keys():
    """Every `KEY_*` name passed as the first argument of a
    `register_dev_keybinding(...)` call."""
    tree = ast.parse(_DEV_KEYBINDINGS.read_text())
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "register_dev_keybinding"):
            continue
        assert node.args, "register_dev_keybinding called with no key"
        key = node.args[0]
        # `_h.keys.KEY_X`
        assert isinstance(key, ast.Attribute), ast.dump(key)
        names.append(key.attr)
    return names


def _display_to_key_name():
    """Display name -> KEY_* constant, for every rebindable action."""
    out = dict(input_map._HOST_KEY_ATTR)
    for action in input_map.ACTIONS:
        disp = action[3]
        if disp not in out:
            # Letters, digits and F-keys map by upper-casing.
            out[disp] = "KEY_" + disp.upper()
    return out


def test_no_dev_key_collides_with_a_player_action():
    d2k = _display_to_key_name()
    claimed = {}
    for action in input_map.ACTIONS:
        claimed[d2k[action[3]]] = action[0]

    collisions = [(k, claimed[k]) for k in _registered_dev_keys() if k in claimed]
    assert not collisions, (
        "developer keybinding(s) sit on keys the player already uses: "
        + ", ".join("%s (bound to %s)" % (k, a) for k, a in collisions)
    )


def test_no_two_dev_keybindings_share_a_key():
    """Re-registering a key silently REPLACES the earlier handler, so a
    duplicate is a feature that vanished rather than an error."""
    keys = _registered_dev_keys()
    dupes = {k for k in keys if keys.count(k) > 1}
    assert not dupes, f"two dev keybindings share a key: {sorted(dupes)}"


def test_dev_keys_avoid_the_directly_read_keys():
    """Namespace 3: keys host_loop reads positionally rather than through any
    registry, so no registry lookup can find them."""
    directly_read = {
        "KEY_1", "KEY_2", "KEY_3", "KEY_4", "KEY_5", "KEY_6", "KEY_7",
        "KEY_8", "KEY_9",          # throttle levels in _PlayerControl
        "KEY_F12",                 # read via key_pressed() in the host loop
        "KEY_ESCAPE", "KEY_SPACE",
    }
    clash = sorted(set(_registered_dev_keys()) & directly_read)
    assert not clash, f"dev keybinding on a directly-read key: {clash}"


def test_dev_keys_avoid_the_sdk_routed_function_keys():
    """Namespace 4: F6/F9 are forwarded to the game's own scripts as WC_F6 /
    WC_F9, so binding them here would shadow BC's crew menu and flyby camera.
    """
    sdk_routed = {"KEY_F6", "KEY_F9"}
    clash = sorted(set(_registered_dev_keys()) & sdk_routed)
    assert not clash, f"dev keybinding shadows an SDK-routed key: {clash}"


def test_every_dev_key_is_natively_exported():
    """A dev binding on an unexported constant raises AttributeError on the
    first developer-mode tick and kills the process. Complements
    test_host_key_manifest.py, which covers all of engine/ rather than just
    the registrations."""
    import pytest
    h = pytest.importorskip("_dauntless_host")
    missing = [k for k in _registered_dev_keys() if not hasattr(h.keys, k)]
    assert not missing, f"dev keybinding on unexported key(s): {missing}"
