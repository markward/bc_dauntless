"""engine.bridge_selection — registry, ship universe, labels."""
import pytest

from engine import mods
from engine import bridge_selection as bs
from tests.helpers.bridge_fixtures import (   # noqa: F401
    fake_install, install_mod, register_player_ship)


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

def test_available_ships_are_bcs_player_menu_hulls_that_exist(fake_install):
    """BC's player picker is GeneratePlayerShipMenu's fixed list, not the
    ships/ directory: a starbase or asteroid script is a friend/enemy
    catalog entry only. A player hull whose script is absent (Nebula here)
    is not offered either."""
    ships = bs.available_ships()
    assert "__init__" not in ships
    assert "galaxy" not in ships            # Hardpoints/galaxy.py is not a ship
    assert "FedStarbase" not in ships and "Asteroid" not in ships
    assert "Nebula" not in ships
    assert set(ships) == {"Galaxy", "Sovereign", "Akira", "BirdOfPrey", "KessokLight"}


def test_stock_player_ships_is_bcs_sixteen():
    assert bs.STOCK_PLAYER_SHIPS == (
        "Akira", "Ambassador", "Galaxy", "Nebula", "Sovereign",
        "BirdOfPrey", "Vorcha", "Marauder", "Warbird",
        "Galor", "Keldon", "CardHybrid", "KessokLight", "KessokHeavy",
        "Shuttle", "Transport")


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
    register_player_ship("LCIntrepid")
    assert "LCIntrepid" in bs.available_ships()
    assert "lcintrepid" not in bs.available_ships()


def test_a_mod_ship_registered_only_for_the_catalog_is_not_playable(fake_install, tmp_path):
    install_mod(tmp_path, "Cube", {"scripts/Ships/BorgCube.py": "# mod ship\n"})
    register_player_ship("BorgCube", player=False)      # RegisterQBShipMenu only
    assert "BorgCube" not in bs.available_ships()


def test_a_registered_mod_ship_without_a_script_is_not_offered(fake_install):
    register_player_ship("Ghost")
    assert "Ghost" not in bs.available_ships()


def test_mod_registration_spelling_folds_onto_the_script(fake_install, tmp_path):
    # The LC pack declares shipFile 'LCintrepid' against LCIntrepid.py.
    install_mod(tmp_path, "Intrepid", {"scripts/Ships/LCIntrepid.py": "# mod ship\n"})
    register_player_ship("LCintrepid")
    assert "LCIntrepid" in bs.available_ships()


def test_a_mod_override_of_a_stock_ship_is_not_duplicated(fake_install, tmp_path):
    install_mod(tmp_path, "CGSov", {"scripts/ships/sovereign.py": "# replaces\n"})
    assert bs.available_ships().count("Sovereign") == 1
    assert "sovereign" not in bs.available_ships()


def test_missing_ships_tgl_does_not_raise(fake_install):
    _sdk, game_root = fake_install
    (game_root / "data" / "TGL" / "Ships.tgl").unlink()
    bs.clear_caches()
    assert bs.ship_label("Galaxy") == "Galaxy"


def test_reconfiguring_mods_invalidates_the_cache_without_clear_caches(fake_install, tmp_path):
    register_player_ship("LCIntrepid")
    assert "LCIntrepid" not in bs.available_ships()      # populate the cache
    root = tmp_path / "mods"
    p = root / "Intrepid" / "scripts" / "Ships" / "LCIntrepid.py"
    p.parent.mkdir(parents=True); p.write_text("# mod ship\n")
    mods.configure(mods.build_index(root))               # NO bs.clear_caches()
    assert "LCIntrepid" in bs.available_ships()


# ---- BridgePins ---------------------------------------------------------------

@pytest.fixture
def pins(fake_install, tmp_path):
    return bs.load_bridge_pins(tmp_path / "bridges.json")


def test_absent_file_yields_the_three_defaults(pins):
    assert pins.pins() == {"Galaxy": "GalaxyBridge",
                           "Sovereign": "SovereignBridge",
                           "Akira": "SovereignBridge"}
    assert pins.pins() is not bs.DEFAULT_PINS      # a copy, never the constant


def test_present_file_is_authoritative_even_when_empty(fake_install, tmp_path):
    p = tmp_path / "bridges.json"
    p.write_text('{"version": 1, "pins": {}}')
    pins = bs.load_bridge_pins(p)
    assert pins.pins() == {}
    assert pins.resolve("Galaxy") == "GalaxyBridge"   # default bridge, not default PIN


def test_resolve_pinned_unpinned_and_default(pins):
    assert pins.resolve("Akira") == "SovereignBridge"
    assert pins.resolve("BirdOfPrey") == "GalaxyBridge"
    assert pins.resolve("") == "GalaxyBridge"
    assert pins.resolve(None) == "GalaxyBridge"


def test_missing_bridge_falls_back_keeps_the_pin_and_logs_once(pins, capsys):
    pins.add("BirdOfPrey", "GalaxyBridge")
    # Simulate a removed mod: hand-edit the file behind the store.
    pins.store.set("pins", "BirdOfPrey", "VoyagerBridge")
    assert pins.resolve("BirdOfPrey") == "GalaxyBridge"
    assert pins.resolve("BirdOfPrey") == "GalaxyBridge"
    assert pins.pins()["BirdOfPrey"] == "VoyagerBridge"      # not pruned
    out = capsys.readouterr().out
    assert out.count("BirdOfPrey -> VoyagerBridge") == 1


def test_add_writes_the_whole_map_so_defaults_persist(pins, tmp_path):
    import json
    pins.add("BirdOfPrey", "SovereignBridge")
    doc = json.loads((tmp_path / "bridges.json").read_text())
    assert doc["pins"] == {"Galaxy": "GalaxyBridge",
                           "Sovereign": "SovereignBridge",
                           "Akira": "SovereignBridge",
                           "BirdOfPrey": "SovereignBridge"}


def test_remove_a_default_sticks(pins, tmp_path):
    pins.remove("Akira")
    again = bs.load_bridge_pins(tmp_path / "bridges.json")
    assert "Akira" not in again.pins()
    assert again.resolve("Akira") == "GalaxyBridge"


def test_add_rejects_duplicate_ship_and_unknown_bridge(pins):
    with pytest.raises(bs.DuplicateShip):
        pins.add("Galaxy", "SovereignBridge")
    with pytest.raises(bs.UnknownBridge):
        pins.add("BirdOfPrey", "VoyagerBridge")
    assert "BirdOfPrey" not in pins.pins()


def test_remove_unknown_ship_is_a_noop(pins):
    pins.remove("NotAShip")
    assert len(pins.pins()) == 3


def test_reset_deletes_the_file_and_restores_defaults(pins, tmp_path):
    pins.remove("Akira")
    assert (tmp_path / "bridges.json").exists()
    pins.reset()
    assert not (tmp_path / "bridges.json").exists()
    assert pins.pins() == bs.DEFAULT_PINS


def test_corrupt_file_is_quarantined_and_defaults_used(fake_install, tmp_path):
    p = tmp_path / "bridges.json"
    p.write_text("{not json")
    pins = bs.load_bridge_pins(p)
    assert pins.pins() == bs.DEFAULT_PINS
    assert (tmp_path / "bridges.json.corrupt").exists()


def test_rows_carry_labels_and_missing_flags(fake_install, tmp_path):
    p = tmp_path / "bridges.json"
    p.write_text('{"version": 1, "pins": {"Galaxy": "GalaxyBridge", '
                 '"LCIntrepid": "VoyagerBridge", "FedStarbase": "GalaxyBridge"}}')
    pins = bs.load_bridge_pins(p)
    rows = pins.rows()
    assert rows[0] == bs.PinRow("Galaxy", "Galaxy", "GalaxyBridge", "Galaxy",
                                False, False)
    assert rows[1] == bs.PinRow("LCIntrepid", "LCIntrepid", "VoyagerBridge",
                                "Voyager", True, True)
    # A hull that exists but is not on the player menu is "missing" too: the
    # flag means "not playable", and the row is kept so it can be removed.
    assert rows[2].ship_missing is True and rows[2].bridge_missing is False


def test_rows_are_in_file_order(pins):
    assert [r.ship for r in pins.rows()] == ["Galaxy", "Sovereign", "Akira"]


def test_unpinned_ships_excludes_pinned(pins):
    assert pins.unpinned_ships() == ["BirdOfPrey", "KessokLight"]
    pins.add("BirdOfPrey", "GalaxyBridge")
    assert pins.unpinned_ships() == ["KessokLight"]


def test_default_bridges_path_sits_beside_settings_json():
    from engine import settings_store
    assert bs.default_bridges_path() == (
        settings_store.default_settings_path().parent / "bridges.json")
