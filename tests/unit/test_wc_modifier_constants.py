"""WC_ALT_/WC_CTRL_/WC_CAPS_ modifier-chord constants.

Undefined WC_* names resolve through App.py's __getattr__ to a _NamedStub
whose int() is 0 — the collapse-onto-slot-0 bug class. hasattr(App, ...)
is therefore ALWAYS true; these tests check the input module directly and
assert int-ness on App.
"""
import re
from pathlib import Path

import App
import engine.appc.input as appc_input

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_BASES = (
    [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [chr(c) for c in range(ord("0"), ord("9") + 1)]
    + ["F%d" % n for n in range(1, 13)]
)


def _family_names():
    return ["WC_%s_%s" % (mod, base)
            for mod in ("ALT", "CTRL", "CAPS") for base in _BASES]


def test_all_family_constants_are_real_ints_on_App():
    for name in _family_names():
        val = getattr(App, name)
        assert isinstance(val, int), "%s is not an int (stub collapse!)" % name
        assert val != 0, "%s collapsed to 0" % name


def test_family_codes_distinct_and_disjoint_from_base_band():
    codes = [getattr(appc_input, n) for n in _family_names()]
    assert len(set(codes)) == len(codes), "duplicate chord codes"
    base_codes = {v for k, v in vars(appc_input).items()
                  if k.startswith("WC_") and isinstance(v, int) and v < 0x200}
    assert not (set(codes) & base_codes), "chord band collides with base band"


def test_every_wc_name_the_sdk_references_is_defined():
    sdk = _PROJECT_ROOT / "sdk" / "Build" / "scripts"
    src = ""
    for fname in ("KeyConfig.py", "DefaultKeyboardBinding.py"):
        src += (sdk / fname).read_text(errors="replace")
    referenced = set(re.findall(r"App\.(WC_[A-Za-z0-9_]+)", src))
    missing = sorted(n for n in referenced
                     if not isinstance(getattr(appc_input, n, None), int))
    assert missing == [], "SDK references undefined WC_ names: %s" % missing


def test_modifier_chords_export_shape():
    assert appc_input.MODIFIER_BANDS == {"ALT": 0x200, "CTRL": 0x400, "CAPS": 0x800}
    assert len(appc_input.MODIFIER_CHORDS) == 3 * len(_BASES)
    mod, base, code = appc_input.MODIFIER_CHORDS[0]
    assert code == appc_input.MODIFIER_BANDS[mod] | getattr(appc_input, "WC_" + base)


_CHORD_TARGET_ET_NAMES = (
    "ET_MANAGE_POWER", "ET_MANEUVER", "ET_INPUT_SELF_DESTRUCT",
    "ET_INPUT_CLEAR_TARGET", "ET_INPUT_INTERCEPT",
    "ET_INPUT_DEBUG_KILL_TARGET", "ET_INPUT_DEBUG_QUICK_REPAIR",
    "ET_INPUT_DEBUG_GOD_MODE", "ET_INPUT_DEBUG_LOAD_QUANTUMS",
    "ET_OTHER_BEAM_TOGGLE_CLICKED", "ET_OTHER_CLOAK_TOGGLE_CLICKED",
)


def test_chord_target_event_constants_are_real_ints():
    import App
    for name in _CHORD_TARGET_ET_NAMES:
        assert isinstance(getattr(App, name), int), name


def test_chord_target_event_constants_do_not_collide_with_any_other_et_value():
    """None of the 11 chord-target ET_* constants may share a value with
    ANY other ET_* attribute on the App module — a collision there means
    two unrelated events dispatch to the same handler chain (e.g. the
    ET_INPUT_SELF_DESTRUCT / ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL clash at
    1055, fixed by renumbering SELF_DESTRUCT to 1056).

    Scoped to just the 11 chord targets, not a global uniqueness check:
    App already carries at least one PRE-EXISTING duplicate unrelated to
    this branch (ET_CLOAKED_COLLISION == ET_POWER_FRACTION_CHANGED == 1075),
    which is out of scope here."""
    import App
    all_et = {}
    for name in dir(App):
        if not name.startswith("ET_"):
            continue
        val = getattr(App, name)
        if isinstance(val, int):
            all_et.setdefault(val, set()).add(name)

    for name in _CHORD_TARGET_ET_NAMES:
        val = getattr(App, name)
        collisions = all_et.get(val, set()) - {name}
        assert not collisions, (
            "%s (%d) collides with %s" % (name, val, sorted(collisions))
        )
