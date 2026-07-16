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
