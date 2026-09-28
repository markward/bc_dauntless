"""In a MAPPED region the key light points FROM THE STAR and takes the
STAR'S COLOUR at BC's authored brightness (Mark's call 2026-09-27, live
finding at Ona 2: the region's authored light sat 73 degrees below the visible
sun, and Ona 3's near-white light lit a red star's system).

The key light is the brightest directional (tools/systems/survey.py
_key_light's rule). Other directionals and the ambient are untouched; an
unmapped set is untouched.
"""
import math

import pytest

import App
from engine import host_loop
from engine.appc.ships import ShipClass_Create
from engine.systems import frames, resolve, star_light
from tests.helpers.fresh_world import _fresh_world
from tests.helpers.mapped_regions import load_region


def _lum(c):
    return star_light.luminance(c)


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v)


def _angle_deg(a, b):
    a, b = _unit(a), _unit(b)
    d = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))
    return math.degrees(math.acos(d))


# ── pure function ──────────────────────────────────────────────────────


def test_brightest_directional_takes_the_star_direction_and_hue():
    key = ((0.0, 0.0, -1.0), (0.9, 0.9, 0.9))
    fill = ((1.0, 0.0, 0.0), (0.3, 0.3, 0.3))
    star_dir = (0.0, 3.0, 4.0)
    star_color = (0.91, 0.35, 0.24)
    out = star_light.key_light_from_star([fill, key], star_dir, star_color)
    assert out[0] == fill
    (d, c) = out[1]
    assert d == pytest.approx((0.0, 0.6, 0.8), abs=1e-12)
    assert _lum(c) == pytest.approx(_lum(key[1]), rel=1e-9)
    # Same hue: c is a positive multiple of the star colour.
    k = c[0] / star_color[0]
    assert c == pytest.approx(tuple(k * s for s in star_color), rel=1e-9)


def test_no_directionals_is_unchanged():
    assert star_light.key_light_from_star([], (1.0, 0.0, 0.0),
                                          (1.0, 1.0, 1.0)) == []


# ── real regions ───────────────────────────────────────────────────────


@pytest.fixture
def game():
    return _fresh_world()


def _player_in(game, pSet, where=(0.0, 0.0, 0.0)):
    player = ShipClass_Create("Galaxy")
    pSet.AddObjectToSet(player, "player")
    player.SetTranslateXYZ(*where)
    player.UpdateNodeOnly()
    game.SetPlayer(player)
    return player


def _star_of(pSet):
    m = resolve.map_of(resolve.system_of(pSet.GetName()))
    return next(b for b in m.bodies if b.orbits is None)


def _authored_key(pSet):
    from engine.appc.lights import aggregate_for_renderer
    _, dirs = aggregate_for_renderer(pSet, (0, 0, 0), [])
    return max(dirs, key=lambda dc: _lum(dc[1]))


def _key(dirs):
    return max(dirs, key=lambda dc: _lum(dc[1]))


def test_ona2_key_light_points_from_the_star_in_its_colour(game):
    ona2 = load_region("Ona", "Ona2")
    player = _player_in(game, ona2, (500.0, -300.0, 40.0))
    star = _star_of(ona2)
    authored = _authored_key(ona2)

    ambient_bc, dirs_bc = host_loop._aggregate_lights(ona2)
    ambient, dirs = host_loop._aggregate_lights(ona2, player)

    pos = frames.system_position(player)[1:]
    want = _unit(tuple(s - p for s, p in zip(star.position_gu, pos)))
    d, c = _key(dirs)
    assert d == pytest.approx(want, abs=1e-6)
    assert _lum(c) == pytest.approx(_lum(authored[1]), rel=1e-9)
    k = c[0] / star.appearance.color[0]
    assert c == pytest.approx(
        tuple(k * s for s in star.appearance.color), rel=1e-9)
    # The authored light really was far off the star (the live finding).
    assert _angle_deg(authored[0], want) > 30.0
    # Ambient and every other directional are BC's.
    assert ambient == ambient_bc
    others = [dc for dc in dirs if dc is not _key(dirs)]
    others_bc = [dc for dc in dirs_bc if dc is not _key(dirs_bc)]
    assert others == others_bc


def test_ona2_key_light_follows_the_player_every_frame(game):
    ona2 = load_region("Ona", "Ona2")
    player = _player_in(game, ona2)
    _, dirs_a = host_loop._aggregate_lights(ona2, player)
    player.SetTranslateXYZ(0.0, 50000.0, 0.0)
    player.UpdateNodeOnly()
    _, dirs_b = host_loop._aggregate_lights(ona2, player)
    star = _star_of(ona2)
    pos = frames.system_position(player)[1:]
    want = _unit(tuple(s - p for s, p in zip(star.position_gu, pos)))
    assert _key(dirs_b)[0] == pytest.approx(want, abs=1e-6)
    assert _angle_deg(_key(dirs_a)[0], _key(dirs_b)[0]) > 1.0


def test_ona1_key_light_barely_moves(game):
    ona1 = load_region("Ona", "Ona1")
    player = _player_in(game, ona1)
    authored = _authored_key(ona1)
    _, dirs = host_loop._aggregate_lights(ona1, player)
    assert _angle_deg(_key(dirs)[0], authored[0]) < 3.0


def test_an_unmapped_set_is_byte_identical(game):
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "QuickBattleRegion")
    light = App.LightPlacement_Create("Light", "QuickBattleRegion", None)
    fwd = App.TGPoint3(); fwd.SetXYZ(0.3, 0.4, -0.866)
    up = App.TGPoint3(); up.SetXYZ(0.0, 0.0, 1.0)
    light.AlignToVectors(fwd, up)
    light.ConfigDirectionalLight(1.0, 0.9, 0.8, 0.7)
    player = _player_in(game, pSet)
    assert (host_loop._aggregate_lights(pSet, player)
            == host_loop._aggregate_lights(pSet))
