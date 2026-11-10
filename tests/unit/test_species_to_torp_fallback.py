"""A torpedo constant missing from Multiplayer.SpeciesToTorp reads as UNKNOWN.

Mod torpedo scripts end Create() with
`pTorp.SetNetType(Multiplayer.SpeciesToTorp.<NAME>)` naming a type that only
an extended community copy of that SDK file defines (the Majestic Class's
PHOTON6 / QUANTUM2). Without the pack the AttributeError aborted Create() and
the torpedo never launched, although the net type is multiplayer-only.
"""

import importlib
import types

import pytest

from engine.compat import species_to_torp


def _fake_module():
    mod = types.ModuleType("Multiplayer.SpeciesToTorp")
    mod.UNKNOWN = 0
    mod.PHOTON = 2
    mod.MAX_TORPS = 16
    return mod


@pytest.fixture(autouse=True)
def _fresh_announcements():
    species_to_torp._announced.clear()
    yield
    species_to_torp._announced.clear()


def test_missing_constant_reads_as_unknown():
    mod = _fake_module()
    species_to_torp.install(mod)
    assert mod.PHOTON6 == 0
    assert mod.QUANTUM2 == mod.UNKNOWN


def test_defined_constants_are_untouched():
    mod = _fake_module()
    species_to_torp.install(mod)
    assert mod.PHOTON == 2
    assert mod.MAX_TORPS == 16


def test_non_constant_names_still_raise():
    """Only CONSTANT-shaped names fall back: hasattr probes, dunders and
    misspelt functions must keep failing the ordinary way."""
    mod = _fake_module()
    species_to_torp.install(mod)
    assert not hasattr(mod, "__wrapped__")
    assert not hasattr(mod, "GetScriptFromSpecies2")
    assert not hasattr(mod, "photon6")
    with pytest.raises(AttributeError):
        mod.__path__


def test_each_missing_name_is_announced_once(capsys):
    mod = _fake_module()
    species_to_torp.install(mod)
    mod.PHOTON6
    mod.PHOTON6
    mod.QUANTUM2
    lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(lines) == 2
    assert all(l.startswith("[weapons] ") for l in lines)
    assert "PHOTON6" in lines[0] and "QUANTUM2" in lines[1]


def test_reinstall_after_reload_keeps_working():
    mod = _fake_module()
    species_to_torp.install(mod)
    species_to_torp.install(mod)
    assert mod.PHOTON6 == 0


def test_real_sdk_module_through_the_loader():
    """The stock SDK file, imported the way a mod torpedo script imports it,
    gets the fallback from the loader's override pass."""
    mod = importlib.import_module("Multiplayer.SpeciesToTorp")
    assert mod.PHOTON == 2
    assert mod.ROMULANCANNON == 15
    assert mod.PHOTON6 == mod.UNKNOWN == 0


def test_both_sdk_loaders_route_species_to_torp():
    """The runtime loader (tools/mission_harness.py) and its test twin
    (tests/conftest.py) must gate identically: the tests only run the twin,
    so without this the runtime loader could drop the hook unseen."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    gate = '_qual == "Multiplayer.SpeciesToTorp"'
    for rel in ("tools/mission_harness.py", "tests/conftest.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert gate in text, f"{rel} does not route Multiplayer.SpeciesToTorp"
