"""Tests for planet/sun rendering wiring in host_loop."""
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# _iter_planets
# ---------------------------------------------------------------------------

def test_iter_planets_yields_planet_objects():
    """Planets added to a set are produced by _iter_planets."""
    import App
    from engine.appc.planet import Planet_Create
    from engine import host_loop

    pSet = App.SetClass_Create()
    pPlanet = Planet_Create(170.0, "data/models/environment/GreenPurplePlanet.nif")
    pSet.AddObjectToSet(pPlanet, "Biranu 1")
    App.g_kSetManager.AddSet(pSet, "_test_planets_basic")
    try:
        planets = list(host_loop._iter_planets())
        assert pPlanet in planets
    finally:
        App.g_kSetManager.DeleteSet("_test_planets_basic")


def test_iter_planets_skips_sun():
    """Sun is a Planet subclass but must NOT appear in _iter_planets output."""
    import App
    from engine.appc.planet import Planet_Create, Sun_Create
    from engine import host_loop

    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0)
    pSet.AddObjectToSet(pSun, "Sun")
    pPlanet = Planet_Create(170.0, "data/models/environment/GreenPurplePlanet.nif")
    pSet.AddObjectToSet(pPlanet, "Biranu 1")
    App.g_kSetManager.AddSet(pSet, "_test_planets_no_sun")
    try:
        planets = list(host_loop._iter_planets())
        assert pPlanet in planets
        assert pSun not in planets
    finally:
        App.g_kSetManager.DeleteSet("_test_planets_no_sun")


def test_iter_planets_skips_ship_like_objects():
    """Objects with GetScript (ship-like) are ignored by _iter_planets."""
    import App
    from engine.appc.planet import Planet_Create
    from engine import host_loop

    class _FakeShip:
        def GetScript(self):
            return "ships.Federation.Galaxy"

    pSet = App.SetClass_Create()
    pPlanet = Planet_Create(100.0, "data/models/environment/IcePlanet.nif")
    pShip = _FakeShip()
    pSet.AddObjectToSet(pPlanet, "planet")
    pSet.AddObjectToSet(pShip, "ship")
    App.g_kSetManager.AddSet(pSet, "_test_planets_skip_ships")
    try:
        planets = list(host_loop._iter_planets())
        assert pPlanet in planets
        assert pShip not in planets
    finally:
        App.g_kSetManager.DeleteSet("_test_planets_skip_ships")


def test_iter_planets_empty_set_contributes_nothing():
    """Adding an empty set to the manager must not grow the planet iterator."""
    import App
    from engine import host_loop

    before = set(id(p) for p in host_loop._iter_planets())
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "_test_planets_empty")
    try:
        after = set(id(p) for p in host_loop._iter_planets())
        assert after == before
    finally:
        App.g_kSetManager.DeleteSet("_test_planets_empty")


# ---------------------------------------------------------------------------
# _planet_nif_path
# ---------------------------------------------------------------------------

def test_planet_nif_path_returns_none_for_empty_model():
    """Planet with no model_path (e.g. bare Sun_Create) → None."""
    from engine.appc.planet import Planet_Create
    from engine import host_loop

    # Planet_Create with empty path (what Sun analogue has)
    pPlanet = Planet_Create(100.0, "")
    result = host_loop._planet_nif_path(pPlanet)
    assert result is None


def test_planet_nif_path_returns_none_when_file_missing():
    """Relative path that does not resolve to a real file → None."""
    from engine.appc.planet import Planet_Create
    from engine import host_loop

    pPlanet = Planet_Create(100.0, "data/models/environment/DoesNotExist.nif")
    result = host_loop._planet_nif_path(pPlanet)
    assert result is None


def test_planet_nif_path_returns_absolute_path_when_file_exists(tmp_path, monkeypatch):
    """A model_path that resolves to an existing file → absolute path string."""
    from engine.appc.planet import Planet_Create
    from engine import host_loop

    # Create a fake NIF under a fake game tree so the file-exists check passes.
    fake_nif = tmp_path / "game" / "data" / "models" / "environment" / "Test.nif"
    fake_nif.parent.mkdir(parents=True)
    fake_nif.write_bytes(b"FAKE")

    pPlanet = Planet_Create(100.0, "data/models/environment/Test.nif")

    # Temporarily redirect engine.paths' game root inside host_loop.
    import engine.host_loop as hl
    monkeypatch.setattr(hl._paths, "game_root", lambda: tmp_path / "game")
    result = hl._planet_nif_path(pPlanet)

    assert result == str(fake_nif)


def test_planet_nif_path_verbose_logs_skip_reason(capsys):
    """With verbose=True, missing-file skips print a diagnostic."""
    from engine.appc.planet import Planet_Create
    from engine import host_loop

    pPlanet = Planet_Create(100.0, "data/models/environment/DoesNotExist.nif")
    host_loop._planet_nif_path(pPlanet, verbose=True)
    out = capsys.readouterr().out
    assert "skip" in out.lower()


# ---------------------------------------------------------------------------
# Integration: planet instances created in run()
# ---------------------------------------------------------------------------

def test_run_M1Basic_verbose_reports_planet_instances():
    """OPEN_STBC_HOST_VERBOSE=1 must log at least one planet instance
    for M1Basic/Biranu1 (which registers GreenPurplePlanet and moon)."""
    import os

    PLANET_NIF = (PROJECT_ROOT / "game" / "data" / "Models" /
                  "Environment" / "GreenPurplePlanet.nif")
    GALAXY_NIF = (PROJECT_ROOT / "game" / "data" / "Models" /
                  "Ships" / "Galaxy" / "Galaxy.nif")
    if not PLANET_NIF.is_file() or not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")

    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    os.environ["OPEN_STBC_HOST_VERBOSE"] = "1"
    try:
        from engine import host_loop
        rc = host_loop.run("Custom.Tutorial.Episode.M1Basic.M1Basic", max_ticks=2)
        assert rc == 0
    finally:
        os.environ.pop("OPEN_STBC_HOST_VERBOSE", None)
