"""Foundation surface for ship metadata: the `dauntless` attribute, unlisted
(stock) definitions, and which mod built a definition."""
import pytest

from engine import foundation, mods
from engine.foundation import loader, quickbattle, shipdef
from engine.foundation.shipdef import ShipDefinition, all_definitions, plugin_origin


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)
    yield
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)


def test_dauntless_is_a_known_attribute():
    d = ShipDefinition("Fed", "X", 103, {"shipFile": "X"})
    d.dauntless = {"title": "X"}
    assert "dauntless" not in d.unknown_attributes


def test_unlisted_definition_stays_out_of_all_definitions():
    d = ShipDefinition("Fed", "X", None, {"shipFile": "X"}, _listed=False)
    assert d not in all_definitions()
    assert shipdef.icon_name_for_script("ships.X") is None


def test_listed_is_the_default():
    d = ShipDefinition("Fed", "X", 103, {"shipFile": "X"})
    assert d in all_definitions()


def test_origin_is_recorded_inside_plugin_origin_only():
    with plugin_origin("DCMPv2", "custom/ships/dcmp.py"):
        inside = ShipDefinition("Fed", "A", 103)
    outside = ShipDefinition("Fed", "B", 103)
    assert inside._origin == ("DCMPv2", "custom/ships/dcmp.py")
    assert outside._origin is None
    assert "_origin" not in inside.unknown_attributes


def _touch(p, body):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


_MAKE = ("from engine.foundation.shipdef import ShipDefinition\n"
         "ShipDefinition('Fed', %r, 103, {'shipFile': %r})\n")


def test_loader_attributes_each_definition_to_its_mod(tmp_path):
    _touch(tmp_path / "ModA" / "scripts" / "Custom" / "Ships" / "a.py", _MAKE % ("A", "A"))
    _touch(tmp_path / "ModB" / "scripts" / "Custom" / "Ships" / "b.py", _MAKE % ("B", "B"))
    mods.configure(mods.build_index(tmp_path))
    loader.load_plugins()
    got = {d.abbrev: d._origin for d in all_definitions()}
    assert got == {"A": ("ModA", "custom/ships/a.py"),
                   "B": ("ModB", "custom/ships/b.py")}


def test_origin_is_cleared_after_a_failing_plugin(tmp_path):
    _touch(tmp_path / "ModA" / "scripts" / "Custom" / "Ships" / "a.py",
           _MAKE % ("A", "A") + "raise RuntimeError('boom')\n")
    mods.configure(mods.build_index(tmp_path))
    report = loader.load_plugins()
    assert report.failures and report.failures[0][0] == "custom/ships/a.py"
    assert shipdef._CURRENT_ORIGIN is None
    later = ShipDefinition("Fed", "C", 103)
    assert later._origin is None
