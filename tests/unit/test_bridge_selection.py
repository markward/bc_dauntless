"""engine.bridge_selection — registry, ship universe, labels."""
import pytest

from engine import bridge_selection as bs
from tests.helpers.bridge_fixtures import fake_install, install_mod   # noqa: F401


# ---- registry ---------------------------------------------------------------

def test_stock_bridges_are_galaxy_and_sovereign_with_bc_labels(fake_install):
    assert bs.available_bridges() == [
        bs.BridgeInfo("GalaxyBridge", "Galaxy"),
        bs.BridgeInfo("SovereignBridge", "Sovereign"),
    ]
    assert bs.is_available("SovereignBridge")
    assert not bs.is_available("VoyagerBridge")


def test_bridge_label_for_an_unknown_bridge_strips_one_trailing_bridge(fake_install):
    assert bs.bridge_label("VoyagerBridge") == "Voyager"
    assert bs.bridge_label("Voyager") == "Voyager"
    assert bs.bridge_label("GalaxyBridge") == "Galaxy"


@pytest.mark.xfail(strict=True,
                   reason="mod bridge scan is the follow-up feature; contract "
                          "fixed by the 2026-09-16 ship-bridge-matrix spec §1")
def test_mod_bridge_scan_keeps_only_modules_defining_CreateBridgeModel(
        fake_install, tmp_path):
    install_mod(tmp_path, "VoyBridge", {
        "scripts/Bridge/VoyagerBridge.py":
            "import App\ndef CreateBridgeModel(pBridgeSet):\n    pass\n",
        "scripts/Bridge/VoyagerMenuHandlers.py":
            "def CreateMenus():\n    pass\n",
        "scripts/Bridge/Characters/Foo.py":
            "def CreateBridgeModel(x):\n    pass\n",   # wrong depth: ignored
    })
    assert bs.available_bridges()[2:] == [bs.BridgeInfo("VoyagerBridge", "Voyager")]
    assert bs.is_available("VoyagerBridge")


# ---- ship universe ------------------------------------------------------------

def test_available_ships_are_top_level_ship_script_stems(fake_install):
    ships = bs.available_ships()
    assert "__init__" not in ships
    assert "galaxy" not in ships            # Hardpoints/galaxy.py is not a ship
    assert set(ships) == {"Galaxy", "Sovereign", "Akira", "BirdOfPrey", "KessokLight"}


def test_available_ships_sorted_by_label(fake_install):
    # labels: Akira, Bird of Prey, Galaxy, Light Cruiser, Sovereign
    assert bs.available_ships() == ["Akira", "BirdOfPrey", "Galaxy",
                                    "KessokLight", "Sovereign"]


def test_ship_label_from_tgl_with_stem_fallback(fake_install):
    assert bs.ship_label("BirdOfPrey") == "Bird of Prey"
    assert bs.ship_label("KessokLight") == "Light Cruiser"
    assert bs.ship_label("LCIntrepid") == "LCIntrepid"


def test_mod_ships_join_the_universe_in_the_authors_spelling(fake_install, tmp_path):
    install_mod(tmp_path, "Intrepid", {
        "scripts/Ships/LCIntrepid.py": "# mod ship\n",
        "scripts/Ships/Hardpoints/lcintrepid.py": "# hp\n",
    })
    assert "LCIntrepid" in bs.available_ships()
    assert "lcintrepid" not in bs.available_ships()


def test_a_mod_override_of_a_stock_ship_is_not_duplicated(fake_install, tmp_path):
    install_mod(tmp_path, "CGSov", {"scripts/ships/sovereign.py": "# replaces\n"})
    assert bs.available_ships().count("Sovereign") == 1
    assert "sovereign" not in bs.available_ships()


def test_missing_ships_tgl_does_not_raise(fake_install):
    _sdk, game_root = fake_install
    (game_root / "data" / "TGL" / "Ships.tgl").unlink()
    bs.clear_caches()
    assert bs.ship_label("Galaxy") == "Galaxy"
