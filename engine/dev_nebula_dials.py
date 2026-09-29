"""Developer keys to live-tune the system-scale nebula look dials.

`docs/superpowers/specs/2026-09-29-system-nebula-render-design.md` Task 7:
lets a developer nudge `SystemNebulaPass`'s look while the pass is running,
instead of editing constants and rebuilding for every trial.

Seven dials, three keys (a MacBook keyboard -- no numpad, no Pause):

  /   select the next dial: veil -> floor -> g -> lane_contrast ->
      near_range -> conceal_cap -> godray_gain -> veil ...
  L   step the selected dial DOWN
  O   step the selected dial UP

  veil           x or / 1.25, clamped to [0.001, 0.99]  (Python-side)
  floor          x or / 1.25
  g              +/- 0.05, clamped to [0, 0.95]
  lane_contrast  +/- 0.1,  clamped to [0, 1]
  near_range     x or / 1.5
  conceal_cap    +/- 0.01, clamped to [0, LOCK_BREAK_T) (Python-side): the
                 radial profile's concealment ceiling; 0.20 = re-acquire line
  godray_gain    x or / 1.25 (Python-side): the star's god-ray intensity,
                 gain x profile nebula x star transmittance at the player

Every press prints `[nebula dials] ...` with the selected dial and the whole
dial dict, so settled values can be read off and folded back into the
defaults.

WHY ONLY THREE KEYS. A dev key must be free in every namespace a key can be
claimed in (tests/unit/test_dev_key_collisions.py enforces all of them):
BC's own `DefaultKeyboardBinding.py` BindKey calls, `input_map.ACTIONS`,
the dev-keybinding registry (`engine/dev_keybindings.py` + this module),
the directly-read keys (throttle 1-9, F12 DevTools, Escape, Space), the
SDK-routed F6/F9 -- and it must exist on a MacBook and be exported by the
host key table (`_dauntless_host.keys`). Checked 2026-09-29 against every
key a MacBook has:
  - BC binds every digit, every letter except K/L/O, F1-F6/F9, the arrows,
    Tab, Backspace, ` - = [ ] \\, Home/End/PgUp/PgDn/Delete (fn+arrows).
  - Of what BC leaves free, the dev registry already holds K (BoP wing
    state), , . ; ' (explosion light), F7, F8, F10, F11; F12 is DevTools.
  - Enter is not exported and drives the pause menu; Caps Lock only reports
    state changes on macOS.
That leaves exactly /, L and O. The earlier numpad / Pause picks were
unreachable on Mark's MacBook.

The veil is not a native dial: it sets the star's transmittance from the
system's outermost region, so host_loop re-solves `k_sys` with
`profile.k_sys(m, veil())` and re-pushes the profile (a ~1.6s table
rebuild) whenever it changes, and the flare veil uses the same value via
`profile.star_transmittance(player, veil())`. The four native dials go to
`engine.renderer.system_nebula_set_dials` as one dict each press
(`lane_size` rides along unchanged -- the native struct expects the whole
set). A `g` or `floor` change rebuilds the far-field table (~1.6s);
`lane_contrast` and `near_range` never rebuild anything.
"""
import engine.dev_mode as dev_mode

DEFAULTS: dict = {
    "veil": 0.15,   # == engine.systems.profile.VEIL_DEFAULT (test-pinned)
    "floor": 0.0916,   # Mark's live pick 2026-09-29 (0.03 read too dark)
    "g": 0.6,
    "lane_contrast": 0.7,
    "lane_size": 15000.0,
    "near_range": 30000.0,
    # == engine.appc.sensor_detection.PROFILE_CONCEALMENT_CAP (test-pinned).
    # Python-side like the veil: concealment_at reads it under --developer.
    "conceal_cap": 0.19,
    # Python-side: scales the star's god-ray entry (host_loop
    # _push_nebula_godrays via profile_fx.star_godray_intensity).
    "godray_gain": 1.0,
}

# The order `/` cycles through. The veil first: the spec names it as the
# first thing to tune.
DIAL_ORDER: tuple = ("veil", "floor", "g", "lane_contrast", "near_range",
                     "conceal_cap", "godray_gain")

_VEIL_MIN, _VEIL_MAX, _VEIL_FACTOR = 0.001, 0.99, 1.25
_G_MIN, _G_MAX, _G_STEP = 0.0, 0.95, 0.05
_LANE_CONTRAST_MIN, _LANE_CONTRAST_MAX, _LANE_CONTRAST_STEP = 0.0, 1.0, 0.1
_FLOOR_FACTOR = 1.25
_NEAR_RANGE_FACTOR = 1.5
_CONCEAL_STEP = 0.01
_GODRAY_GAIN_FACTOR = 1.25

# Live dial state and the selected dial's index into DIAL_ORDER. Module-level
# so presses accumulate across a session (mirrors dev_keybindings.py's
# module-level toggle state).
_dials: dict = dict(DEFAULTS)
_selected: int = 0


def current() -> dict:
    """A copy of the live dial values (veil included)."""
    return dict(_dials)


def veil() -> float:
    """The live veil: the star's transmittance from the system's outermost
    region that k_sys is solved for (engine.systems.profile.k_sys). Read by
    host_loop for both the profile push and the flare veil."""
    return _dials["veil"]


def selected() -> str:
    """The dial L / O currently step."""
    return DIAL_ORDER[_selected]


def step(dials: dict, name: str, direction: int) -> dict:
    """Pure: return a NEW dict with `name` stepped by `direction` (+1 or -1).

    `veil`, `floor` and `near_range` step multiplicatively; `g` and
    `lane_contrast` step additively. Clamped where the dial has a range.
    Never mutates `dials`.
    """
    out = dict(dials)
    if name == "veil":
        v = (out["veil"] * _VEIL_FACTOR if direction > 0
             else out["veil"] / _VEIL_FACTOR)
        out["veil"] = max(_VEIL_MIN, min(_VEIL_MAX, v))
    elif name == "floor":
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
    elif name == "conceal_cap":
        # Strictly below LOCK_BREAK_T: at or above it the profile alone would
        # break every lock in the band (the E3M2 blindness the cap exists for).
        from engine.appc.sensor_detection import LOCK_BREAK_T
        c = round(out["conceal_cap"] + direction * _CONCEAL_STEP, 4)
        out["conceal_cap"] = max(0.0, min(LOCK_BREAK_T - 0.001, c))
    elif name == "godray_gain":
        out["godray_gain"] = (out["godray_gain"] * _GODRAY_GAIN_FACTOR
                              if direction > 0
                              else out["godray_gain"] / _GODRAY_GAIN_FACTOR)
    else:
        raise ValueError("unknown nebula dial: %r" % (name,))
    return out


def _native(dials: dict) -> dict:
    """The dials the native pass owns (not the Python-side veil / conceal_cap
    / godray_gain)."""
    return {k: v for k, v in dials.items()
            if k not in ("veil", "conceal_cap", "godray_gain")}


def godray_gain() -> float:
    """The live star god-ray gain (host_loop._push_nebula_godrays)."""
    return _dials["godray_gain"]


def conceal_cap() -> float:
    """The live profile-concealment cap (sensor_detection.concealment_at reads
    it under --developer). 0.20 is the re-acquire threshold: below it the
    profile can never hold a lock broken by a local cloud."""
    return _dials["conceal_cap"]


def _report() -> None:
    print("[nebula dials] selected=%s %s" % (selected(), _dials))


def _cycle() -> None:
    global _selected
    _selected = (_selected + 1) % len(DIAL_ORDER)
    _report()


def _push(direction: int) -> None:
    global _dials
    _dials = step(_dials, selected(), direction)
    from engine import renderer as r
    r.system_nebula_set_dials(_native(_dials))
    _report()


def register(_h) -> None:
    """Register the three keys. Call once at boot, gated on
    `dev_mode.is_enabled()` -- see `engine/host_loop.py`'s `run()`.

    `_h` is the `_dauntless_host` extension module (or a test double
    exposing `.keys.KEY_*`), matching `dev_keybindings.register_for_frame`'s
    convention.
    """
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_SLASH, _cycle,
        "System nebula: select next dial (veil/floor/g/lanes/near/cap/godrays) (dev) - /",
    )
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_L, lambda: _push(-1),
        "System nebula: selected dial down (dev) - L",
    )
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_O, lambda: _push(+1),
        "System nebula: selected dial up (dev) - O",
    )
