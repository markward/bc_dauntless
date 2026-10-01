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
# Every module that calls register_dev_keybinding(...) at its own call sites.
# dev_keybindings.py re-registers every tick (register_for_frame);
# dev_dial_groups.py registers once at boot (register_keys(), called by
# dev_nebula_dials.register() and any later dial group) -- both share the
# same dev_mode._dev_keybindings table, so a collision between the two files
# is exactly as real as a collision within one of them.
_DEV_KEYBINDING_FILES = (
    _ROOT / "engine" / "dev_keybindings.py",
    _ROOT / "engine" / "dev_dial_groups.py",
)


def _registered_dev_keys_in(paths):
    """Every `KEY_*` name passed as the first argument of a
    `register_dev_keybinding(...)` call, across the given files."""
    names = []
    for path in paths:
        tree = ast.parse(path.read_text())
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


def _registered_dev_keys():
    """Every `KEY_*` name passed as the first argument of a
    `register_dev_keybinding(...)` call, across every dev-keybinding module."""
    return _registered_dev_keys_in(_DEV_KEYBINDING_FILES)


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


# ── Namespace 5: BC's own SDK keyboard bindings ─────────────────────────────
#
# A dev key that also fires one of BC's own `App.WC_*` bindings double-fires:
# dev-key dispatch never consumes the key, so both the dev handler and
# whatever `DefaultKeyboardBinding.Initialize()` bound to that physical key
# run on the same press. This bit us for real: the first cut of
# `dev_nebula_dials.py` used J/L/N/M/U/O/B/P, which collide with BC's
# WC_J (target attacker), WC_N (next navpoint), WC_P (next planet), WC_M
# (map mode), WC_U (target nearest) and WC_B (first person) -- L and O were
# the only two of those eight that happened to be free.
#
# A dev `KEY_*` constant's bare-key identity is translated to BC's `WC_*`
# name below; most letters/digits/F-keys share a suffix (`KEY_L` -> `WC_L`),
# but punctuation and the numpad diverge and need an explicit table.
_KEY_TO_WC_NAME: dict = {
    "KEY_COMMA": "WC_COMMA",
    "KEY_PERIOD": "WC_PERIOD",
    "KEY_SEMICOLON": "WC_SEMICOLON",
    "KEY_APOSTROPHE": "WC_QUOTE",
    "KEY_SLASH": "WC_SLASH",
    "KEY_BACKSLASH": "WC_BACKSLASH",
    "KEY_LEFT_BRACKET": "WC_OPEN_BRACKET",
    "KEY_RIGHT_BRACKET": "WC_CLOSE_BRACKET",
    "KEY_GRAVE_ACCENT": "WC_BACKQUOTE",
    "KEY_EQUAL": "WC_EQUALS",
    "KEY_MINUS": "WC_MINUS",
    "KEY_KP_0": "WC_NUMPAD0",
    "KEY_KP_DECIMAL": "WC_DECIMAL",
    "KEY_KP_MULTIPLY": "WC_MULTIPLY",
    "KEY_KP_DIVIDE": "WC_DIVIDE",
    "KEY_PAUSE": "WC_PAUSE",
}


def _key_to_wc_name(key: str) -> str:
    """Translate a dev `KEY_*` constant to BC's `WC_*` name for the same
    physical key. Plain letters/digits/F-keys share a suffix; everything
    else must be in `_KEY_TO_WC_NAME`."""
    if key in _KEY_TO_WC_NAME:
        return _KEY_TO_WC_NAME[key]
    assert key.startswith("KEY_"), key
    return "WC_" + key[len("KEY_"):]


def _bc_bound_wc_names():
    """Every `App.WC_*` name passed as the first positional argument of a
    `g_kKeyboardBinding.BindKey(...)` call in the SDK's
    `DefaultKeyboardBinding.py`. Commented-out calls are not parsed (ast
    never sees them), matching what actually runs."""
    from engine import paths

    try:
        sdk = paths.sdk_scripts()
    except Exception:  # noqa: BLE001 - no BC install configured here
        import pytest
        pytest.skip("no BC install resolvable")
    path = sdk / "DefaultKeyboardBinding.py"
    if not path.exists():
        import pytest
        pytest.skip("DefaultKeyboardBinding.py not present")

    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "BindKey"):
            continue
        if not node.args:
            continue
        key = node.args[0]
        if isinstance(key, ast.Attribute):
            names.add(key.attr)
    return names


def test_no_dev_key_collides_with_bcs_own_keyboard_binding():
    """A dev key must not sit on a physical key BC's own
    `DefaultKeyboardBinding.Initialize()` already binds -- dev-key dispatch
    never consumes the key, so both handlers would fire on one press.

    Scoped to `engine/dev_dial_groups.py` alone (this is the file whose
    keys this check exists to re-verify -- the / L O keys dev_nebula_dials.py
    originally claimed moved here with the minor-rocks dial-group registry).
    `engine/dev_keybindings.py` predates this check and, running it there
    too, ALSO trips on three pre-existing collisions
    (KEY_LEFT_BRACKET/WC_OPEN_BRACKET, KEY_RIGHT_BRACKET/WC_CLOSE_BRACKET,
    KEY_I/WC_I) that are a real, separate bug outside this task's scope --
    filed as a follow-up, not silently fixed here."""
    bc_bound = _bc_bound_wc_names()
    dial_groups_file = [p for p in _DEV_KEYBINDING_FILES if p.name == "dev_dial_groups.py"]
    collisions = []
    for key in _registered_dev_keys_in(dial_groups_file):
        wc_name = _key_to_wc_name(key)
        if wc_name in bc_bound:
            collisions.append((key, wc_name))
    assert not collisions, (
        "dev_dial_groups.py keybinding(s) collide with BC's own "
        "DefaultKeyboardBinding.py: "
        + ", ".join("%s (%s)" % (k, w) for k, w in collisions)
    )


# ── A MacBook keyboard ──────────────────────────────────────────────────────
#
# Mark tunes on a MacBook: no numeric keypad, no Pause/Break, Insert, Scroll
# Lock, Print Screen or Num Lock. The nebula dials first shipped on Numpad
# / * . 0 and Pause -- all unreachable there.
_NOT_ON_A_MACBOOK_PREFIXES = ("KEY_KP_",)
_NOT_ON_A_MACBOOK = {"KEY_PAUSE", "KEY_INSERT", "KEY_SCROLL_LOCK",
                     "KEY_PRINT_SCREEN", "KEY_NUM_LOCK", "KEY_MENU"}


def _off_macbook(keys):
    return sorted(k for k in keys
                  if k in _NOT_ON_A_MACBOOK
                  or k.startswith(_NOT_ON_A_MACBOOK_PREFIXES)
                  or (k.startswith("KEY_F") and k[5:].isdigit() and int(k[5:]) > 12))


def test_nebula_dial_keys_exist_on_a_macbook():
    dial_groups_file = [p for p in _DEV_KEYBINDING_FILES
                        if p.name == "dev_dial_groups.py"]
    off = _off_macbook(_registered_dev_keys_in(dial_groups_file))
    assert not off, f"dial group key(s) a MacBook keyboard lacks: {off}"
