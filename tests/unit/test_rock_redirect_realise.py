"""Both ship-realise seams (realize_set_objects, _MissionLoader._realize_session)
redirect a stock BC asteroid NIF to a catalogue rock, at the stock mesh's
authored size, and leave every other ship untouched.

Spec: docs/superpowers/specs/2026-09-30-rock-catalogue-design.md
"""
from dataclasses import dataclass, field
from typing import Optional

import pytest

import App
from engine import host_loop as hl
from engine import paths
from engine.appc.sets import SetClass_Create
from engine.rocks import catalogue


@dataclass
class _LoadCall:
    path: str
    search: object
    reps: object
    kwargs: dict = field(default_factory=dict)


class _FakeRenderer:
    """Mirrors the fixture pattern in tests/unit/test_realize_set.py, extended
    to record load_model's kwargs (Review Focus: the scale kwarg must reach
    the renderer, not just be computed)."""

    def __init__(self):
        self._next = 1
        self.live = set()
        self.load_calls: list[_LoadCall] = []

    def load_model(self, path, search, texture_replacements=None, decals=None, **kwargs):
        self.load_calls.append(_LoadCall(path, search, texture_replacements, dict(kwargs)))
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    def create_instance(self, h):
        iid = self._next
        self._next += 1
        self.live.add(iid)
        return iid

    def destroy_instance(self, iid):
        self.live.discard(iid)

    def set_world_transform(self, iid, m):
        pass

    def set_rim_eligible(self, iid, b):
        pass

    def set_rim_strength(self, iid, s):
        pass


@pytest.fixture(autouse=True)
def _catalogue_state():
    saved_enabled = catalogue.enabled()
    catalogue._memo.clear()
    catalogue._warned.clear()
    yield
    catalogue.set_enabled(saved_enabled)
    catalogue._memo.clear()
    catalogue._warned.clear()


def _stock_asteroid_path() -> str:
    """A REAL game-root path for asteroid1.nif -- satisfies R13 (the redirect
    only fires under paths.game_root()) without constructing a real SDK ship."""
    return str(paths.game_root() / "data" / "Models" / "Misc" / "Asteroids" / "asteroid1.NIF")


@pytest.fixture
def stock_asteroid_ship():
    ship = App.ShipClass_Create()
    ship.SetName("Debris1")
    return ship


@pytest.fixture
def galaxy_ship():
    ship = App.ShipClass_Create()
    ship.SetName("Galaxy")
    return ship


@pytest.fixture
def session():
    return hl.MissionSession(mission_name="t")


@pytest.fixture
def fake_renderer():
    return _FakeRenderer()


# ---- Seam 1: realize_set_objects ------------------------------------------

def test_stock_asteroid_realises_as_catalogue_rock(monkeypatch, fake_renderer,
                                                    stock_asteroid_ship, session):
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: _stock_asteroid_path())
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    s.AddObjectToSet(stock_asteroid_ship, "Debris1")

    hl.realize_set_objects(session, s, fake_renderer, ships=[stock_asteroid_ship])

    call = fake_renderer.load_calls[-1]
    assert call.path.endswith("lod0.gltf")
    rock = catalogue.pick(stock_asteroid_ship.GetName())
    assert call.kwargs["scale"] == pytest.approx(catalogue.load_scale(rock, "asteroid1.nif"))


def test_non_asteroid_load_is_unchanged(monkeypatch, fake_renderer, galaxy_ship, session):
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    s.AddObjectToSet(galaxy_ship, "Galaxy")

    hl.realize_set_objects(session, s, fake_renderer, ships=[galaxy_ship])

    call = fake_renderer.load_calls[-1]
    assert call.path == "fake.nif"
    assert "scale" not in call.kwargs


def test_toggle_off_loads_stock(monkeypatch, fake_renderer, stock_asteroid_ship, session):
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: _stock_asteroid_path())
    catalogue.set_enabled(False)
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    s.AddObjectToSet(stock_asteroid_ship, "Debris1")

    hl.realize_set_objects(session, s, fake_renderer, ships=[stock_asteroid_ship])

    call = fake_renderer.load_calls[-1]
    assert call.path.lower().endswith("asteroid1.nif")
    assert "scale" not in call.kwargs


# ---- _ship_load_key: distinct handles for the same rock at different scales

def test_ship_load_key_distinguishes_scale():
    k1 = hl._ship_load_key("x/lod0.gltf", None, None, 0.4)
    k2 = hl._ship_load_key("x/lod0.gltf", None, None, 3.1)
    assert k1 != k2


def test_ship_load_key_legacy_unchanged():
    assert hl._ship_load_key("a.nif", None) == "a.nif"


# ---- Seam 2: _MissionLoader._realize_session (QuickBattle boot path) ------

def test_realize_session_redirects_stock_asteroid(monkeypatch):
    """Drives _realize_session the same way test_hull_volume_wiring.py does:
    via the real QuickBattle boot cascade (load_quickbattle), which realizes
    exactly one ship (the player). _ship_nif_path is monkeypatched so that
    ship resolves to a real game-root stock-asteroid path."""
    from tools import mission_harness
    mission_harness.setup_sdk()

    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: _stock_asteroid_path())

    controller = hl.HostController()
    controller.renderer = _FakeRenderer()
    controller.loader = hl._MissionLoader(controller, verbose=False)

    session = controller.loader.load_quickbattle()

    from engine.core.game import Game_GetCurrentGame
    player = Game_GetCurrentGame().GetPlayer()
    assert player is not None
    assert player in session.ship_instances

    call = controller.renderer.load_calls[-1]
    assert call.path.endswith("lod0.gltf")
    rock = catalogue.pick(player.GetName())
    assert call.kwargs["scale"] == pytest.approx(catalogue.load_scale(rock, "asteroid1.nif"))
