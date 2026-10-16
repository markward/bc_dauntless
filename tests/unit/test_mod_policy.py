"""engine/mod_policy: which mod files Dauntless refuses, which mods it blocks.
Spec docs/superpowers/specs/2026-10-16-legacy-fx-api-surface-design.md §5."""
from pathlib import Path

from engine import mod_policy as P

_LAYOUT = Path(__file__).resolve().parents[1] / "fixtures" / "mod_layouts" / "nanofx_2_0_beta.txt"


def _pf(raw: str) -> P.PolicyFile:
    """A mod-relative path as build_index keys it: data/ and sfx/ keep their
    top segment (game target); scripts/ drops it (sdk target)."""
    parts = raw.replace("\\", "/").strip("/").split("/")
    top = parts[0].lower()
    if top == "scripts":
        return P.PolicyFile(P.SDK, "/".join(parts[1:]).lower())
    return P.PolicyFile(P.GAME, "/".join(parts).lower())


def _nanofx_files():
    return [_pf(line) for line in _LAYOUT.read_text().splitlines() if line.strip()]


def test_standalone_nanofx_is_blocked_whole():
    d = P.decide(_nanofx_files(), {})
    assert d.blocked == P.REASON_NANOFX_BLOCKED
    assert d.refused == {}


def test_nanofx_bundled_in_a_pack_skips_only_its_own_files():
    files = _nanofx_files() + [_pf("scripts/ships/MyShip.py"),
                               _pf("data/Models/Ships/MyShip/MyShip.nif")]
    d = P.decide(files, {})
    assert d.blocked is None
    assert d.refused["custom/nanofxv2/nanofx_lib.py"] == P.REASON_NANOFX_BUNDLED
    assert d.refused["custom/autoload/loadnanofx.py"] == P.REASON_NANOFX_BUNDLED
    assert "ships/myship.py" not in d.refused
    # ATP is used by other mods in its own right: never refused.
    assert not any(r.startswith("custom/advancedtechnologies/") for r in d.refused)
    # Foundation's own files in the same pack are refused under rule B.
    assert d.refused["foundation.py"] == P.REASON_FOUNDATION
    assert d.refused["fixes20030217.py"] == P.REASON_FOUNDATION


def test_nanofx_texture_files_without_a_marker_are_left_alone():
    files = [_pf("scripts/Custom/NanoFXv2/SpecialFX/Gfx/Blinker/Blank.tga"),
             _pf("scripts/ships/Hardpoints/MyShipHP.py")]
    d = P.decide(files, {})
    assert d.blocked is None and d.refused == {}


def test_foundation_always_refused_files():
    names = ["scripts/Foundation.py", "scripts/FoundationMenu.py",
             "scripts/FoundationTriggers.py", "scripts/Fixes20030217.py",
             "scripts/Custom/Autoload/000-Fixes20030221.py",
             "scripts/Custom/Autoload/000-Utilities-GetFileNames-20030402.py"]
    d = P.decide([_pf(n) for n in names] + [_pf("scripts/ships/A.py")], {})
    assert set(d.refused) == {_pf(n).rel for n in names}
    assert set(d.refused.values()) == {P.REASON_FOUNDATION}


def test_conditional_files_refused_only_when_they_import_foundation():
    lts = _pf("scripts/LoadTacticalSounds.py")
    qb = _pf("scripts/QuickBattle/QuickBattle.py")
    mm = _pf("scripts/MainMenu/mainmenu.py")
    for f in (lts, qb, mm):
        assert P.needs_imports(f)
    d = P.decide([lts, qb, mm], {lts.rel: {"App", "Foundation"},
                                 qb.rel: {"App", "FoundationMenu"},
                                 mm.rel: {"App"}})
    assert d.refused == {lts.rel: P.REASON_FOUNDATION, qb.rel: P.REASON_FOUNDATION}


def test_needs_imports_is_false_for_everything_else():
    assert not P.needs_imports(_pf("scripts/ships/A.py"))
    assert not P.needs_imports(_pf("data/LoadTacticalSounds.py"))


def test_a_plain_ship_pack_is_untouched():
    d = P.decide([_pf("scripts/ships/A.py"), _pf("data/Models/A.nif")], {})
    assert d.blocked is None and d.refused == {}
