"""The far tier's host-loop hooks (far-tier plan Task 10): both realise seams
note the model they ACTUALLY loaded, the scene reconcile pushes the far tier
right after the minors, a mission swap clears it, and boot registers its
dial group. Drives the real seams (tests/unit/test_rock_redirect_realise.py's
fakes, tests/unit/test_minor_rocks_mission_swap.py's swap)."""
import inspect

import pytest

import App
from engine import host_loop as hl
from engine.appc.sets import SetClass_Create
from engine.rocks import catalogue, far_tier
from tests.unit.test_rock_redirect_realise import (
    _FakeRenderer, _GltfFailingRenderer, _stock_asteroid_path)


@pytest.fixture
def noted(monkeypatch):
    calls = []
    monkeypatch.setattr(far_tier, "note_model",
                        lambda ship, path, scale: calls.append((ship, path, scale)))
    return calls


def _rock():
    from tests.unit.test_rock_class import _make
    return _make(App.GENUS_ASTEROID)


def _realize(ship, r_, monkeypatch):
    monkeypatch.setattr(hl, "_ship_nif_path", lambda s, **k: _stock_asteroid_path())
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    s.AddObjectToSet(ship, "Debris1")
    session = hl.MissionSession(mission_name="t")
    hl.realize_set_objects(session, s, r_, ships=[ship])
    return session


def test_realize_set_objects_notes_the_catalogue_rock_it_loaded(monkeypatch, noted):
    rock = _rock()
    r_ = _FakeRenderer()
    _realize(rock, r_, monkeypatch)
    call = r_.load_calls[-1]
    assert noted == [(rock, call.path, call.kwargs["scale"])]


def test_realize_set_objects_notes_the_stock_nif_on_fallback(monkeypatch, noted):
    rock = _rock()
    _realize(rock, _GltfFailingRenderer(), monkeypatch)
    assert noted == [(rock, _stock_asteroid_path(), 1.0)]


def test_realize_set_objects_flags_the_rock_end_to_end(monkeypatch):
    rock = _rock()
    session = _realize(rock, _FakeRenderer(), monkeypatch)
    (flag,) = far_tier.desired_rocks(session.ship_instances)
    assert flag["index"] >= 0
    assert flag["instance"] == session.ship_instances[rock]


def _quickbattle(monkeypatch, r_):
    from tools import mission_harness
    mission_harness.setup_sdk()
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: _stock_asteroid_path())
    controller = hl.HostController()
    controller.renderer = r_
    controller.loader = hl._MissionLoader(controller, verbose=False)
    controller.loader.load_quickbattle()
    from engine.core.game import Game_GetCurrentGame
    return Game_GetCurrentGame().GetPlayer()


def test_realize_session_notes_the_model_it_loaded(monkeypatch, noted):
    r_ = _FakeRenderer()
    player = _quickbattle(monkeypatch, r_)
    call = r_.load_calls[-1]
    assert (player, call.path, call.kwargs["scale"]) in noted
    assert call.path.endswith("lod0.gltf")


def test_realize_session_notes_the_stock_nif_on_fallback(monkeypatch, noted):
    player = _quickbattle(monkeypatch, _GltfFailingRenderer())
    assert (player, _stock_asteroid_path(), 1.0) in noted


def test_reconcile_scene_reconciles_the_far_tier_after_the_minors(monkeypatch):
    from engine.rocks import minors
    order = []
    for name in ("_ensure_system_loaded", "_reconcile_runtime_instances",
                 "_reconcile_celestial_instances", "_check_mapped_bodies_untouched"):
        monkeypatch.setattr(hl, name, lambda *a, **k: None)
    monkeypatch.setattr(minors, "reconcile", lambda s, r: order.append("minors"))
    monkeypatch.setattr(far_tier, "reconcile", lambda s, r: order.append(("far", s, r)))
    session, r_ = hl.MissionSession(mission_name="t"), object()
    hl._reconcile_scene(session, r_)
    assert order == ["minors", ("far", session, r_)]


def test_a_mission_swap_clears_the_far_tier(monkeypatch):
    from engine.rocks import minors
    cleared = []

    class _FakeSwapRenderer:
        def destroy_instance(self, iid):
            pass
        def minors_clear(self):
            pass
        def far_clear(self):
            cleared.append(1)

    class _StubLoader:
        def load(self, name):
            return hl.MissionSession(mission_name=name)

    rock = _rock()
    far_tier.note_model(rock, _stock_asteroid_path(), 1.0)
    h = hl.HostController()
    h.renderer = _FakeSwapRenderer()
    h.loader = _StubLoader()
    h.session = hl.MissionSession(mission_name="prev")
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()
    assert cleared == [1]
    assert far_tier.desired_rocks({rock: 1}) == []


def test_a_mission_swap_resets_rock_promotion(monkeypatch):
    """Review Focus 4: the swap also resets rock promotion, before the
    renderer's far-tier exclusion is wiped by far_clear."""
    from engine.rocks import promotion
    calls = []
    monkeypatch.setattr(promotion, "reset", lambda r=None: calls.append(r))

    class _FakeSwapRenderer:
        def destroy_instance(self, iid):
            pass
        def minors_clear(self):
            pass
        def far_clear(self):
            pass

    class _StubLoader:
        def load(self, name):
            return hl.MissionSession(mission_name=name)

    h = hl.HostController()
    h.renderer = _FakeSwapRenderer()
    h.loader = _StubLoader()
    h.session = hl.MissionSession(mission_name="prev")
    renderer = h.renderer
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()
    assert calls == [renderer]


def test_boot_registers_the_far_dial_group_beside_the_minor_dials():
    src = inspect.getsource(hl.run)
    mnr = src.find("_minor_dials.register()")
    far = src.find("_far_dials.register()")
    assert mnr >= 0 and far >= 0
    assert 0 < far - mnr < 200, "register the far group beside the minors'"


def test_scenery_contact_pumps_beside_the_minor_contact():
    """Large-rock touches (rock-fields Task 8) respond sim-side, at the same
    call site as the minor contacts (the sim tick's rock-breakup scope)."""
    src = inspect.getsource(hl)
    mnr = src.find("_pump_minor_contact(player, session=session)")
    scn = src.find("_pump_scenery_contact(player, session=session)")
    assert mnr >= 0 and scn >= 0
    assert 0 < scn - mnr < 200, "pump the scenery contacts beside the minors'"


def test_a_mission_swap_resets_the_scenery_contacts():
    src = inspect.getsource(hl.HostController)
    mnr = src.find("_minor_contact.reset()")
    scn = src.find("_scenery_contact.reset()")
    assert mnr >= 0 and scn >= 0
    assert 0 < scn - mnr < 200
