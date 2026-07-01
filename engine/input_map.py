"""Central action → physical-key map for dauntless flight/camera/combat input.

dauntless reads physical keys in two unrelated places: `_PlayerControl` and the
camera handler read GLFW keys directly (`h.key_state(h.keys.KEY_W)`), while the
fire/function pollers forward a hardcoded (glfw_key, WC_code) table into the BC
binding path.  Both were hardcoded to specific keys, so there was no way to
rebind.

`InputMap` is the single source of truth for `action_id → physical key`.  Both
subsystems read their keys from it, and the Configuration → Controls tab edits
it.  Remapping happens at the *physical-key layer* (which GLFW key drives each
action); the BC WC→ET binding table is untouched, so we never need the SDK's
ClearBinding/FindKeyString/GenerateMappingFile/RebuildMappingFromFile.

Keys are identified by a stable display name (e.g. "W", "F1", "=").  GLFW_KEYS
maps each display name to its GLFW integer code — GLFW codes are stable public
constants, so this table is self-contained and testable headless; `verify_against_host`
sanity-checks it against the live `host.keys` submodule at startup.
"""
from __future__ import annotations

from typing import Optional

from engine.appc.config_mapping import TGConfigMapping

# ── GLFW key codes (stable public constants) ────────────────────────────────
# display_name → GLFW code, restricted to the bindable universe.  Reserved keys
# (Esc/Space/Shift/Ctrl/Super/F12) are deliberately absent so they can't be
# captured and shadow pause/mode/system handling.
GLFW_KEYS: dict[str, int] = {}
# Letters A-Z = GLFW 65-90 (== ord).
for _c in range(ord("A"), ord("Z") + 1):
    GLFW_KEYS[chr(_c)] = _c
# Digits 0-9 = GLFW 48-57 (== ord).
for _d in range(ord("0"), ord("9") + 1):
    GLFW_KEYS[chr(_d)] = _d
# Function keys F1-F11 = GLFW 290-300.  F12 is reserved (CEF DevTools toggle),
# so it's intentionally excluded from the bindable universe.
for _i in range(1, 12):
    GLFW_KEYS["F%d" % _i] = 290 + (_i - 1)
# Common punctuation / navigation (GLFW codes).
GLFW_KEYS.update({
    "=": 61, "-": 45, "[": 91, "]": 93, ";": 59, "'": 39,
    ",": 44, ".": 46, "/": 47, "\\": 92, "`": 96,
    "Tab": 258, "Enter": 257, "Backspace": 259,
    "Insert": 260, "Delete": 261, "Home": 268, "End": 269,
    "PageUp": 266, "PageDown": 267,
    "Left": 263, "Right": 262, "Up": 265, "Down": 264,
})

# Display names that must never be bound (capture won't scan them, but the bind
# handler also rejects them defensively).  These are not in GLFW_KEYS.
RESERVED: frozenset = frozenset({"Esc", "Space", "F12", "Shift", "Ctrl", "Cmd"})

# ── Remappable actions ──────────────────────────────────────────────────────
# (action_id, label, category, default_key_name).  Order drives UI layout.
ACTIONS: tuple = (
    ("pitch_down",           "Nose Down",                "Flight",   "W"),
    ("pitch_up",             "Nose Up",                  "Flight",   "S"),
    ("yaw_left",             "Yaw Left",                 "Flight",   "A"),
    ("yaw_right",            "Yaw Right",                "Flight",   "D"),
    ("roll_left",            "Roll Left",                "Flight",   "Q"),
    ("roll_right",           "Roll Right",               "Flight",   "E"),
    ("reverse",             "Reverse Thrust",            "Throttle", "R"),
    ("full_stop",           "Full Stop",                 "Throttle", "0"),
    ("camera_cycle",         "Cycle Camera",             "Camera",   "C"),
    ("camera_zoom_target",   "Zoom on Target (hold)",    "Camera",   "Z"),
    ("camera_reverse_chase", "Look Back (hold)",         "Camera",   "V"),
    ("camera_zoom_in",       "Zoom In",                  "Camera",   "="),
    ("camera_zoom_out",      "Zoom Out",                 "Camera",   "-"),
    ("fire_primary",         "Fire Phasers",             "Weapons",  "F"),
    ("fire_secondary",       "Fire Torpedoes",           "Weapons",  "X"),
    ("fire_tertiary",        "Fire Pulse / Disruptors",  "Weapons",  "G"),
    ("talk_helm",            "Talk to Helm",             "Crew",     "F1"),
    ("talk_tactical",        "Talk to Tactical",         "Crew",     "F2"),
    ("talk_xo",              "Talk to First Officer",    "Crew",     "F3"),
    ("talk_science",         "Talk to Science",          "Crew",     "F4"),
    ("talk_engineering",     "Talk to Engineering",      "Crew",     "F5"),
)

ACTION_IDS: tuple = tuple(a[0] for a in ACTIONS)
_DEFAULTS: dict = {a[0]: a[3] for a in ACTIONS}
_LABELS: dict = {a[0]: a[1] for a in ACTIONS}
_CATEGORIES: tuple = tuple(dict.fromkeys(a[2] for a in ACTIONS))  # ordered-unique

CONFIG_FILE = "Keybindings.cfg"
CONFIG_SECTION = "Controls"


class InputMap:
    """action_id → key display-name, with conflict checks and persistence."""

    def __init__(self, config_mapping: Optional[TGConfigMapping] = None,
                 filename: str = CONFIG_FILE):
        # Dedicated config mapping so Keybindings.cfg only holds [Controls]
        # (SaveConfigFile dumps every in-memory section).
        self._cfg = config_mapping if config_mapping is not None else TGConfigMapping()
        self._filename = filename
        self._map: dict = dict(_DEFAULTS)

    # ── Lookups ─────────────────────────────────────────────────────────────
    def name(self, action_id: str) -> str:
        """Current key display-name bound to `action_id`."""
        return self._map[action_id]

    def code(self, action_id: str) -> int:
        """Current GLFW key code bound to `action_id`."""
        return GLFW_KEYS[self._map[action_id]]

    def label(self, action_id: str) -> str:
        return _LABELS[action_id]

    def action_for(self, key_name: str) -> Optional[str]:
        """The action currently bound to `key_name`, or None (conflict check)."""
        for action_id, name in self._map.items():
            if name == key_name:
                return action_id
        return None

    def categories(self) -> tuple:
        return _CATEGORIES

    # ── Mutation ────────────────────────────────────────────────────────────
    def set(self, action_id: str, key_name: str) -> None:
        """Bind `action_id` to `key_name`.  Raises on unknown action/key."""
        if action_id not in self._map:
            raise KeyError("unknown action: %r" % (action_id,))
        if key_name not in GLFW_KEYS:
            raise ValueError("unbindable key: %r" % (key_name,))
        self._map[action_id] = key_name

    def reset(self) -> None:
        self._map = dict(_DEFAULTS)

    # ── Persistence ─────────────────────────────────────────────────────────
    def save(self) -> int:
        """Write the current map to CONFIG_FILE; returns 1 on success."""
        for action_id, name in self._map.items():
            self._cfg.SetStringValue(CONFIG_SECTION, action_id, name)
        return self._cfg.SaveConfigFile(self._filename)

    def load(self) -> None:
        """Load saved bindings, falling back to defaults for missing/unknown."""
        self._cfg.LoadConfigFile(self._filename)
        for action_id in ACTION_IDS:
            if self._cfg.HasValue(CONFIG_SECTION, action_id):
                name = self._cfg.GetStringValue(CONFIG_SECTION, action_id)
                self._map[action_id] = name if name in GLFW_KEYS else _DEFAULTS[action_id]
            else:
                self._map[action_id] = _DEFAULTS[action_id]

    # ── Startup sanity ──────────────────────────────────────────────────────
    def verify_against_host(self, host_keys) -> list:
        """Return a list of (name, expected, host) mismatches vs host.keys.

        Thin method form of the module-level verify_against_host (verification
        uses only module state, no instance). Kept for existing callers.
        """
        return verify_against_host(host_keys)


def _host_key_attr(name: str) -> Optional[str]:
    """Map a display name to its host.keys attribute (KEY_*), or None."""
    if name in _HOST_KEY_ATTR:
        return _HOST_KEY_ATTR[name]
    if name.isalnum():           # letters/digits/F-keys
        return "KEY_" + name
    return None


def verify_against_host(host_keys) -> list:
    """Module-level twin of InputMap.verify_against_host.

    The key-code table (GLFW_KEYS) and the name→host-attr mapping are both
    module state, so verification needs no InputMap instance. host_io.verify_keys
    calls this at real-host boot to catch the host `keys` submodule diverging
    from engine.input_map's table (e.g. an editing slip in host_bindings.cc).
    Returns a list of (name, expected, host) mismatches; empty == in sync.
    """
    mismatches = []
    for name, code in GLFW_KEYS.items():
        attr = _host_key_attr(name)
        if attr is None:
            continue
        host_code = getattr(host_keys, attr, None)
        if host_code is not None and host_code != code:
            mismatches.append((name, code, host_code))
    return mismatches


# Punctuation/nav display names → host.keys attribute (host_bindings.cc names).
_HOST_KEY_ATTR: dict = {
    "=": "KEY_EQUAL", "-": "KEY_MINUS",
    "[": "KEY_LEFT_BRACKET", "]": "KEY_RIGHT_BRACKET",
    ";": "KEY_SEMICOLON", "'": "KEY_APOSTROPHE",
    ",": "KEY_COMMA", ".": "KEY_PERIOD", "/": "KEY_SLASH",
    "\\": "KEY_BACKSLASH", "`": "KEY_GRAVE_ACCENT",
    "Tab": "KEY_TAB", "Enter": "KEY_ENTER", "Backspace": "KEY_BACKSPACE",
    "Insert": "KEY_INSERT", "Delete": "KEY_DELETE",
    "Home": "KEY_HOME", "End": "KEY_END",
    "PageUp": "KEY_PAGE_UP", "PageDown": "KEY_PAGE_DOWN",
    "Left": "KEY_LEFT", "Right": "KEY_RIGHT", "Up": "KEY_UP", "Down": "KEY_DOWN",
}
