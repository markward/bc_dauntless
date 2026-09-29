"""Developer keys to live-tune the system-scale nebula look dials.

`docs/superpowers/specs/2026-09-29-system-nebula-render-design.md` Task 7:
lets a developer nudge `SystemNebulaPass`'s look dials while the pass is
running, instead of editing the C++ constants and rebuilding for every trial.

Each press mutates the module's live dial dict and pushes the WHOLE dict to
the native pass via `engine.renderer.system_nebula_set_dials`, then prints
`[nebula dials] {...}` to stdout so the values can be read off and folded
back into `system_nebula_pass.cc`'s struct defaults once settled.

Keys chosen (none claimed by `input_map.ACTIONS`, the existing dev-keybinding
registry in `engine/dev_keybindings.py`, the directly-read set (throttle
1-9/F12/Escape/Space), or the SDK-routed F6/F9 -- see
`tests/unit/test_dev_key_collisions.py`, which now scans this module too).
Deliberately avoids the bare `T` key even though it looked free: `KEY_T` is
also polled, WITH Alt, by the tractor-beam toggle
(`tests/integration/test_modifier_chord_poller.py`), and `dispatch_dev_key`
fires on the bare keycode regardless of any modifier -- binding `T` here
would double-fire every time a developer pressed Alt+T for tractors.

  J / L   floor          -  / x  (divide / multiply by 1.25)
  N / M   g              -0.05 / +0.05, clamped to [0, 0.95]
  U / O   lane_contrast  -0.1 / +0.1, clamped to [0, 1]
  B / P   near_range     -  / x  (divide / multiply by 1.5)

`lane_size` travels in the pushed dict too (unchanged -- there is no key for
it) because the native `Dials` struct expects the whole dial set each call.

A `g` or `floor` change makes the native pass rebuild its far-field table
(`SystemNebulaPass::set_dials` re-runs `set_profile` with the new
`LookParams`) -- the build takes ~1.6s, which is fine for a deliberate key
press. `lane_contrast` and `near_range` changes never rebuild anything; the
shader reads them directly every frame.
"""
import engine.dev_mode as dev_mode

DEFAULTS: dict = {
    "floor": 0.03,
    "g": 0.6,
    "lane_contrast": 0.7,
    "lane_size": 15000.0,
    "near_range": 30000.0,
}

_G_MIN, _G_MAX, _G_STEP = 0.0, 0.95, 0.05
_LANE_CONTRAST_MIN, _LANE_CONTRAST_MAX, _LANE_CONTRAST_STEP = 0.0, 1.0, 0.1
_FLOOR_FACTOR = 1.25
_NEAR_RANGE_FACTOR = 1.5

# Live dial state, mutated only via _push() below. Module-level so repeated
# key presses accumulate across a session (mirrors dev_keybindings.py's
# module-level toggle state, e.g. _test_character_iid).
_dials: dict = dict(DEFAULTS)


def step(dials: dict, name: str, direction: int) -> dict:
    """Pure: return a NEW dict with `name` stepped by `direction` (+1 or -1).

    `floor` and `near_range` step multiplicatively (x or / the dial's
    factor); `g` and `lane_contrast` step additively and clamp. Never
    mutates `dials`.
    """
    out = dict(dials)
    if name == "floor":
        out["floor"] = (out["floor"] * _FLOOR_FACTOR if direction > 0
                        else out["floor"] / _FLOOR_FACTOR)
    elif name == "g":
        out["g"] = max(_G_MIN, min(_G_MAX, out["g"] + direction * _G_STEP))
    elif name == "lane_contrast":
        out["lane_contrast"] = max(
            _LANE_CONTRAST_MIN, min(_LANE_CONTRAST_MAX,
                                    out["lane_contrast"]
                                    + direction * _LANE_CONTRAST_STEP))
    elif name == "near_range":
        out["near_range"] = (out["near_range"] * _NEAR_RANGE_FACTOR
                             if direction > 0
                             else out["near_range"] / _NEAR_RANGE_FACTOR)
    else:
        raise ValueError("unknown nebula dial: %r" % (name,))
    return out


def _push(name: str, direction: int) -> None:
    global _dials
    _dials = step(_dials, name, direction)
    from engine import renderer as r
    r.system_nebula_set_dials(_dials)
    print("[nebula dials] %s" % _dials)


def register(_h) -> None:
    """Register the eight step keybindings. Call once at boot, gated on
    `dev_mode.is_enabled()` -- see `engine/host_loop.py`'s `run()`.

    `_h` is the `_dauntless_host` extension module (or a test double
    exposing `.keys.KEY_*`), matching `dev_keybindings.register_for_frame`'s
    convention.
    """
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_J, lambda: _push("floor", -1),
        "System nebula floor / 1.25 (dev) - J",
    )
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_L, lambda: _push("floor", +1),
        "System nebula floor x 1.25 (dev) - L",
    )
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_N, lambda: _push("g", -1),
        "System nebula g -0.05 (dev) - N",
    )
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_M, lambda: _push("g", +1),
        "System nebula g +0.05 (dev) - M",
    )
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_U, lambda: _push("lane_contrast", -1),
        "System nebula lane contrast -0.1 (dev) - U",
    )
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_O, lambda: _push("lane_contrast", +1),
        "System nebula lane contrast +0.1 (dev) - O",
    )
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_B, lambda: _push("near_range", -1),
        "System nebula near range / 1.5 (dev) - B",
    )
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_P, lambda: _push("near_range", +1),
        "System nebula near range x 1.5 (dev) - P",
    )
