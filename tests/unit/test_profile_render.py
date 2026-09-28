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


def test_synthetic_volume_does_not_grow_the_id_registry(monkeypatch):
    # Final review #5: it built a MetaNebula (a registered TGObject) every
    # frame just to read the default fbm dials.
    from engine.core import ids
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(1.0), 5.0))
    PR.synthetic_volume(_Player())
    before = len(ids._registry)
    for _ in range(50):
        PR.synthetic_volume(_Player())
    assert len(ids._registry) == before


def test_default_fbm_dials_are_a_module_constant_with_unchanged_values():
    from engine.appc import nebula
    assert nebula.DEFAULT_FBM_DIALS == (0.02, 1.5, 0.30)
    assert nebula.MetaNebula().GetFbmDials() == nebula.DEFAULT_FBM_DIALS


def test_synthetic_volume_fbm_is_built_from_the_default_dials(monkeypatch):
    from engine.appc import nebula
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(1.0), 5.0))
    freq, gain, floor = PR.synthetic_volume(_Player())["fbm"]
    assert (freq, gain, floor) == nebula.DEFAULT_FBM_DIALS
