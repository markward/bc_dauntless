"""The Mods screen's writer: one guarded, Python 1.5-safe zz_ file per ship,
in the mod's own Custom/Ships spelling, registered and re-run in-process."""
import ast
import os

import pytest

from engine import foundation, mods, ship_catalog
from engine.foundation import quickbattle
from engine.ship_catalog import gate_writer

ANS = {"title": "Avenger", "species": "Federation", "era": ("DS9", "DS9"),
       "role": "tactical", "playable": True, "variant_of": "Defiant",
       "class_default": True}


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset(); quickbattle.reset(); mods.configure(None)
    yield
    foundation.reset(); quickbattle.reset(); mods.configure(None)


def test_render_is_guarded_and_python15_safe():
    text = gate_writer.render("DCMPAvenger", ANS)
    assert "if hasattr(Foundation.ShipDef, 'DCMPAvenger'):" in text
    assert "'era': ('DS9', 'DS9')" in text and "'playable': 1" in text
    assert "'variant_of': 'Defiant'" in text and "'class_default': 1" in text
    tree = ast.parse(text)
    assert not any(isinstance(n, ast.Constant) and isinstance(n.value, bool) for n in ast.walk(tree))
    assert not any(isinstance(n, ast.JoinedStr) for n in ast.walk(tree))


def test_render_all_eras_and_quotes():
    text = gate_writer.render("X", {"title": "Vor'cha", "era": ("all",)})
    assert "'era': 'all'" in text and "'title': 'Vor\\'cha'" in text


def test_render_escapes_control_characters():
    title = "USS Line\nBreak\r\tTab\x01 back\\slash 'q'"
    tree = ast.parse(gate_writer.render("X", {"title": title}))
    d = next(n for n in ast.walk(tree) if isinstance(n, ast.Dict) and n.keys)
    assert ast.literal_eval(d) == {"title": title}


def test_render_omits_class_default_when_false():
    assert "class_default" not in gate_writer.render("X", dict(ANS, class_default=False))


def _mod_tree(tmp_path):
    ships = tmp_path / "mods" / "DCMPv2" / "Scripts" / "Custom" / "Ships"
    ships.mkdir(parents=True)
    (ships / "DCMP.py").write_text(
        "import Foundation\n"
        "Foundation.ShipDef.DCMPAvenger = Foundation.FedShipDef('DCMPAvenger', 103, "
        "{'name': 'Avenger', 'shipFile': 'DCMPAvenger'})\n")
    sdk_ships = tmp_path / "mods" / "DCMPv2" / "Scripts" / "ships"
    sdk_ships.mkdir(parents=True)
    (sdk_ships / "DCMPAvenger.py").write_text("#")
    mods.configure(mods.build_index(tmp_path / "mods"))
    return ships


def test_ships_dir_follows_the_mods_spelling(tmp_path):
    ships = _mod_tree(tmp_path)
    d, prefix = gate_writer.ships_dir("DCMPv2")
    assert d == ships and prefix == "Custom/Ships"


def test_ships_dir_fallback_reuses_existing_scripts_casing(tmp_path):
    """A mod whose only Custom script lives under Custom/Autoload (so the
    first loop in ships_dir -- which only looks for an existing
    custom/ships/*.py file -- finds nothing) must fall back into the mod's
    REAL `Scripts/` directory, not a newly-invented lowercase `scripts/`
    sibling. The on-disk dir is capital-S `Scripts`; a case-sensitive
    filesystem would get a second, wrong, lowercase `scripts/` dir if the
    fallback hard-codes the casing."""
    root = tmp_path / "mods" / "AutoloadOnly"
    autoload = root / "Scripts" / "Custom" / "Autoload"
    autoload.mkdir(parents=True)
    (autoload / "plug.py").write_text("#")
    stock_ships = root / "Scripts" / "ships"
    stock_ships.mkdir(parents=True)
    (stock_ships / "X.py").write_text("#")
    mods.configure(mods.build_index(tmp_path / "mods"))

    d, prefix = gate_writer.ships_dir("AutoloadOnly")

    assert d == root / "Scripts" / "Custom" / "Ships"
    assert prefix == "Custom/Ships"
    # The path string itself (not merely existence, which a case-insensitive
    # filesystem would satisfy either way) must carry the real "Scripts"
    # spelling, and no sibling "scripts" dir may have been invented.
    assert str(d).endswith("Scripts/Custom/Ships")
    assert not any(p.name == "scripts" for p in root.iterdir())


def test_write_registers_and_runs_the_file(tmp_path):
    _mod_tree(tmp_path)
    foundation.load_plugins()
    path = gate_writer.write_answers("DCMPv2", "DCMPAvenger", "DCMPAvenger", ANS)
    assert path.name == "zz_Dauntless_DCMPAvenger.py" and path.is_file()
    assert not path.with_suffix(".py.tmp").exists()
    assert mods.current().lookup("custom/ships/zz_dauntless_dcmpavenger.py") is not None
    assert foundation.ShipDef.DCMPAvenger.dauntless["variant_of"] == "Defiant"


def test_write_failure_is_a_gate_write_error(tmp_path):
    ships = _mod_tree(tmp_path)
    os.chmod(ships, 0o500)
    try:
        with pytest.raises(gate_writer.GateWriteError) as e:
            gate_writer.write_answers("DCMPv2", "DCMPAvenger", "DCMPAvenger", ANS)
        assert "zz_Dauntless_DCMPAvenger.py" in str(e.value)
    finally:
        os.chmod(ships, 0o700)


def test_missing_attr_is_a_gate_write_error(tmp_path):
    _mod_tree(tmp_path)
    with pytest.raises(gate_writer.GateWriteError):
        gate_writer.write_answers("DCMPv2", "X", None, ANS)
