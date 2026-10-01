import pytest

from engine.rocks import minor_contact as mc
from engine.rocks import minor_dials as md


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    md.reset(); mc.reset()
    monkeypatch.setattr(mc, "_spawn_puff", lambda p: None)
    monkeypatch.setattr(mc, "_play_grit", lambda p, r: True)
    monkeypatch.setattr(mc, "_flicker", lambda player, p, session: True)
    monkeypatch.setattr(mc, "_shields_up", lambda player: True)
    monkeypatch.setattr(mc, "_muted", lambda player: False)
    yield
    mc.reset()


def _c(r=0.3):
    return {"point": (0.0, 0.0, 0.0), "radius": r, "rel_speed": 5.0}


def test_rate_limits_hold_over_ten_seconds():
    totals = {"puffs": 0, "grits": 0, "flickers": 0}
    for i in range(600):                             # 10 s at 60 Hz, 20 contacts/frame
        out = mc.pump(object(), contacts=[_c()] * 20, now=i / 60.0)
        for k in totals:
            totals[k] += out[k]
    assert totals["puffs"] <= 6 * 10 + 6
    assert totals["grits"] <= 4 * 10 + 4
    assert totals["flickers"] <= 2 * 10 + 2


def test_small_minors_make_no_puff():
    out = mc.pump(object(), contacts=[_c(r=0.05)], now=0.0)
    assert out["puffs"] == 0 and out["grits"] == 1


def test_no_flicker_with_shields_down(monkeypatch):
    monkeypatch.setattr(mc, "_shields_up", lambda player: False)
    assert mc.pump(object(), contacts=[_c()], now=0.0)["flickers"] == 0


def test_muted_while_dashing_or_in_warp(monkeypatch):
    monkeypatch.setattr(mc, "_muted", lambda player: True)
    assert mc.pump(object(), contacts=[_c()] * 5, now=0.0) == \
        {"puffs": 0, "grits": 0, "flickers": 0}


def test_no_player_drains_and_does_nothing():
    assert mc.pump(None, contacts=[_c()], now=0.0) == \
        {"puffs": 0, "grits": 0, "flickers": 0}
