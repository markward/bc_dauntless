import pytest

from engine.systems import profile as P
from engine.systems import profile_render as PR


class _Loc:
    x, y, z = 10.0, 20.0, 30.0


class _Player:
    def GetWorldLocation(self):
        return _Loc()


def _prof(neb, color=(0.6, 0.35, 0.72)):
    return P.Profile(rows=[P.ProfileRow(0.0, nebula=neb)], color=color)


def test_no_volume_in_clear_space_or_without_a_colour(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(0.0), 5.0))
    assert PR.synthetic_volume(_Player()) is None
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(0.5, color=None), 5.0))
    assert PR.synthetic_volume(_Player()) is None
    monkeypatch.setattr(P, "locate", lambda obj: None)
    assert PR.synthetic_volume(_Player()) is None


def test_volume_is_centred_on_the_player_in_the_cloud_colour(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(1.0), 5.0))
    v = PR.synthetic_volume(_Player())
    assert v["spheres"] == [(10.0, 20.0, 30.0, PR.SPIKE_RADIUS_GU)]
    assert v["rgb"] == (0.6, 0.35, 0.72)
    assert v["visibility"] == pytest.approx(145.0)


def test_thinner_nebula_sees_further_and_is_sparser(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(1.0), 5.0))
    thick = PR.synthetic_volume(_Player())
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(0.2), 5.0))
    thin = PR.synthetic_volume(_Player())
    assert thin["visibility"] > thick["visibility"]
    assert thin["fbm"][2] > thick["fbm"][2]          # higher floor = sparser
