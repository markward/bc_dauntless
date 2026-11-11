"""Walking Custom/Autoload and Custom/Ships.

Neither directory is imported by BC itself -- Foundation is what loads
them, which is exactly why an installed mod's ships currently do nothing.
"""

import sys

import pytest

from engine import foundation, mods
from engine.foundation import loader, quickbattle


def _touch(p, body=""):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)
    yield
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)


def _mod(tmp_path, name="M"):
    return tmp_path / name / "scripts" / "Custom"


def test_autoload_runs_before_ships(tmp_path):
    """Plugins register resources ship definitions may reference, so they
    go first. Order is asserted, not assumed."""
    order = tmp_path / "order.txt"
    _touch(_mod(tmp_path) / "Autoload" / "a_plugin.py",
           "open(%r, 'a').write('autoload\\n')" % str(order))
    _touch(_mod(tmp_path) / "Ships" / "a_ship.py",
           "open(%r, 'a').write('ship\\n')" % str(order))

    mods.configure(mods.build_index(tmp_path))
    loader.load_plugins()

    assert order.read_text(encoding="utf-8").split() == ["autoload", "ship"]


def test_filename_order_is_honoured_within_a_directory(tmp_path):
    """Real plugins carry numeric prefixes (FTech ships
    000-Fixes20030305-FoundationTriggers.py) so authors rely on it."""
    order = tmp_path / "order.txt"
    for n in ("300-c.py", "000-a.py", "100-b.py"):
        _touch(_mod(tmp_path) / "Autoload" / n,
               "open(%r, 'a').write('%s\\n')" % (str(order), n))

    mods.configure(mods.build_index(tmp_path))
    loader.load_plugins()

    assert order.read_text(encoding="utf-8").split() == ["000-a.py", "100-b.py", "300-c.py"]


def test_one_raising_script_does_not_stop_the_others(tmp_path):
    ok = tmp_path / "ok.txt"
    _touch(_mod(tmp_path) / "Ships" / "a_bad.py", "raise ValueError('boom')")
    _touch(_mod(tmp_path) / "Ships" / "b_good.py",
           "open(%r, 'a').write('ran\\n')" % str(ok))

    mods.configure(mods.build_index(tmp_path))
    report = loader.load_plugins()

    assert ok.read_text(encoding="utf-8").strip() == "ran"
    assert any("a_bad" in name and "ValueError" in err
               for name, err in report.failures)


def test_no_mods_loads_nothing_and_does_not_raise(tmp_path):
    mods.configure(mods.build_index(tmp_path / "absent"))
    report = loader.load_plugins()
    assert report.ships == [] and report.autoload == [] and report.failures == []


def test_a_ship_script_can_register_through_the_real_surface(tmp_path):
    _touch(_mod(tmp_path) / "Ships" / "s.py",
           "import Foundation\n"
           "Foundation.ShipDef.X = Foundation.FedShipDef('X', 1, {'name': 'X'})\n"
           "Foundation.ShipDef.X.RegisterQBShipMenu('Fed Ships', qb=None)\n")

    mods.configure(mods.build_index(tmp_path))
    report = loader.load_plugins()

    assert report.failures == []
    assert ("X", 1000) in quickbattle.registered()


# -- plugins load the way the SDK loader loads every other script ------------

def test_a_plugin_written_in_python_1_5_runs(tmp_path):
    """Foundation imported these scripts inside BC's Python 1.5, so they are
    1.5 source: `has_key`, `print` statements, 8-column tabs. They must get
    the same fixes as every other SDK script, not plain Python 3 parsing."""
    out = tmp_path / "out.txt"
    _touch(_mod(tmp_path) / "Autoload" / "old.py",
           "d = {'k': 1}\n"
           "if d.has_key('k'):\n"
           "\tx = 1\n"
           "        y = 2\n"
           "print 'loaded'\n"
           "open(%r, 'w').write(str(x + y))\n" % str(out))

    mods.configure(mods.build_index(tmp_path))
    report = loader.load_plugins()

    assert report.failures == []
    assert out.read_text(encoding="utf-8") == "3"


def test_a_bytecode_only_plugin_runs(tmp_path):
    """A plugin shipped only as Python 1.5 .pyc runs through the lifter,
    like a bytecode-only mod module:

        import Foundation
        Foundation.ShipDef.BC = Foundation.FedShipDef('BC', 1, {'name': 'BC'})
    """
    from tests.helpers import py15_assembler as a15
    pyc = _mod(tmp_path) / "Ships" / "bc.pyc"
    pyc.parent.mkdir(parents=True, exist_ok=True)
    pyc.write_bytes(a15.pyc(a15.module(
        [("SET_LINENO", 1), ("IMPORT_NAME", 0), ("STORE_NAME", 0),
         ("SET_LINENO", 2), ("LOAD_NAME", 0), ("LOAD_ATTR", 1),
         ("LOAD_CONST", 0), ("LOAD_CONST", 1),
         ("BUILD_MAP", 0), ("DUP_TOP",), ("LOAD_CONST", 0),
         ("ROT_TWO",), ("LOAD_CONST", 2), ("STORE_SUBSCR",),
         ("CALL_FUNCTION", 3), ("LOAD_NAME", 0), ("LOAD_ATTR", 2),
         ("STORE_ATTR", 3),
         ("LOAD_CONST", 3), ("RETURN_VALUE",)],
        consts=("BC", 1, "name", None),
        names=("Foundation", "FedShipDef", "ShipDef", "BC"))))

    mods.configure(mods.build_index(tmp_path))
    report = loader.load_plugins()

    assert report.failures == []
    assert report.ships == ["custom/ships/bc.pyc"]
    assert foundation.ShipDef.BC.abbrev == "BC"


def test_a_py_plugin_beats_its_own_pyc(tmp_path):
    out = tmp_path / "out.txt"
    _touch(_mod(tmp_path) / "Autoload" / "p.py",
           "open(%r, 'w').write('py')\n" % str(out))
    (_mod(tmp_path) / "Autoload" / "p.pyc").write_bytes(b"not bytecode")

    mods.configure(mods.build_index(tmp_path))
    report = loader.load_plugins()

    assert report.failures == []
    assert report.autoload == ["custom/autoload/p.py"]
    assert out.read_text(encoding="utf-8") == "py"
