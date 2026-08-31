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
    """Pins the controller's pre-flight collision check (q13 sweep Task 7):
    all 144 chords are unique, and none collides with ANY of BC's ~350
    measured WC_ values -- not just the 48 base keys they're keyed on.

    Pre-correction this compared against a `value < 0x200` heuristic, which
    only worked because our invented codes partitioned cleanly into a low
    base band and a high chord band. BC's own measured values don't honour
    that split (WC_CAPS_A is 65, well under 0x200), so the check now reads
    real measured values directly. Widened past just the 48 base names
    (which only catches a collision with the SAME family a chord derives
    from) to the full measured WC_ table, so a collision with an unrelated
    name -- e.g. a punctuation or navigation key -- would also be caught.
    """
    from engine.appc.constants_generated import MODULE_CONSTANTS
    family = set(_family_names())
    codes = [getattr(appc_input, n) for n in _family_names()]
    assert len(set(codes)) == len(codes), "duplicate chord codes"
    # Every OTHER measured WC_ name -- excluding the 144 chords themselves,
    # since e.g. WC_ALT_A is itself a measured name and would trivially
    # "collide" with its own value.
    other_measured_wc = {v for k, v in MODULE_CONSTANTS.items()
                         if k.startswith("WC_") and k not in family
                         and isinstance(v, int)}
    assert not (set(codes) & other_measured_wc), (
        "a chord collides with an unrelated measured WC_ value")


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
    """MODIFIER_BANDS still exists (it seeds the fallback for names BC's dump
    omits, e.g. WC_CAPS_1..9/F1..F12), but MODIFIER_CHORDS' codes are no
    longer required to equal band|base -- BC separately measured most
    WC_ALT_*/WC_CTRL_*/WC_CAPS_* names, so each triple's code must match
    the corrected WC_<mod>_<base> global, whatever its actual source."""
    assert appc_input.MODIFIER_BANDS == {"ALT": 0x200, "CTRL": 0x400, "CAPS": 0x800}
    assert len(appc_input.MODIFIER_CHORDS) == 3 * len(_BASES)
    for mod, base, code in appc_input.MODIFIER_CHORDS:
        assert code == getattr(appc_input, "WC_%s_%s" % (mod, base))


def test_modifier_chords_are_bc_measured_not_synthesized():
    """BC separately measured these -- e.g. WC_ALT_A is 57393, not the
    band|base formula's 0x200 | 97 == 609. WC_CAPS_A is BC's Shift+A
    character code (65, uppercase ASCII), confirming CAPS_ means "capital
    character", not a CapsLock modifier bit.

    Reads engine.appc.input directly (the definition site), not App."""
    assert appc_input.WC_ALT_A == 57393
    assert appc_input.WC_CTRL_A == 57441
    assert appc_input.WC_CAPS_A == 65


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

    Scoped to just the 11 chord targets, not a global uniqueness check.
    """
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
