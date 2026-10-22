"""The warp-in flash render feed (warp-in spec 6.3).

host_loop._build_warp_in_flash_render_data turns engine.appc.warp_in_flash
records into the native set_warp_in_flashes dicts: centre in RENDER space
(frames.to_render, so a flash in a set outside the viewed frame is dropped),
forward passed unshifted (a direction), radius/age/lifetime carried as-is.
"""
import pytest

import App
import engine.host_loop as host_loop
from engine.appc import warp_in_dials, warp_in_flash
from engine.appc.sets import SetClass_Create
from engine.systems import frames


@pytest.fixture(autouse=True)
def _isolate():
    def _clear():
        App.g_kSetManager._sets.clear()
        App.g_kSetManager.ClearRenderedSet()
        warp_in_flash.reset()
        warp_in_dials.reset()
        frames.reset_render_origin()
    _clear()
    yield
    _clear()


def _set(name):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    return s


def test_feed_skips_flashes_outside_viewed_set():
    viewed = _set("Viewed")
    other = _set("Elsewhere")
    App.g_kSetManager.MakeRenderedSet("Viewed")
    warp_in_flash.spawn(viewed, (1.0, 2.0, 3.0), (0.0, 1.0, 0.0), 2.0, 1.5)
    warp_in_flash.spawn(other, (9.0, 9.0, 9.0), (0.0, 1.0, 0.0), 3.0, 1.5)

    out = host_loop._build_warp_in_flash_render_data()

    assert [d["radius"] for d in out] == [2.0]
    assert out[0]["world_center"] == (1.0, 2.0, 3.0)


def test_feed_is_empty_with_nothing_viewed():
    viewed = _set("Viewed")
    warp_in_flash.spawn(viewed, (1.0, 2.0, 3.0), (0.0, 1.0, 0.0), 2.0, 1.5)
    assert host_loop._build_warp_in_flash_render_data() == []


def test_feed_carries_age_and_lifetime():
    viewed = _set("Viewed")
    App.g_kSetManager.MakeRenderedSet("Viewed")
    warp_in_flash.spawn(viewed, (10.0, 20.0, 30.0), (1.0, 0.0, 0.0), 2.5, 1.5)
    warp_in_flash.advance(0.25)
    frames.set_render_origin((10.0, 0.0, 0.0))

    out = host_loop._build_warp_in_flash_render_data()

    assert out == [{
        "world_center": (0.0, 20.0, 30.0),   # render space: origin subtracted
        "forward": (1.0, 0.0, 0.0),          # a direction: never shifted
        "radius": 2.5,
        "age": pytest.approx(0.25),
        "lifetime": 1.5,
    }]


def test_params_are_the_warp_in_dials():
    warp_in_dials._dials["core_radii"] = 2.5
    warp_in_dials._dials["tint_g"] = 0.5
    p = host_loop._warp_in_flash_params()
    assert p == {
        "core_radii": 2.5,
        "streak_radii": warp_in_dials.DEFAULTS["streak_radii"],
        "ring_radii": warp_in_dials.DEFAULTS["ring_radii"],
        "intensity": warp_in_dials.DEFAULTS["intensity"],
        "streak_end": warp_in_dials.DEFAULTS["streak_end"],
        "ring_rise": warp_in_dials.DEFAULTS["ring_rise"],
        "tint": (warp_in_dials.DEFAULTS["tint_r"], 0.5,
                 warp_in_dials.DEFAULTS["tint_b"]),
    }


def test_combat_push_sends_flashes_and_params(monkeypatch):
    from engine import host_io
    viewed = _set("Viewed")
    App.g_kSetManager.MakeRenderedSet("Viewed")
    warp_in_flash.spawn(viewed, (1.0, 2.0, 3.0), (0.0, 1.0, 0.0), 2.0, 1.5)
    sent = {}
    monkeypatch.setattr(host_io, "set_warp_in_flashes",
                        lambda items: sent.setdefault("flashes", items))
    monkeypatch.setattr(host_io, "set_warp_in_flash_params",
                        lambda params: sent.setdefault("params", params))

    host_loop._push_combat_render_data([])

    assert [d["radius"] for d in sent["flashes"]] == [2.0]
    assert sent["params"] == host_loop._warp_in_flash_params()
