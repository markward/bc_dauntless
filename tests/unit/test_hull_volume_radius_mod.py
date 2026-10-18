"""The damage lattice's cell follows the hole size, not just the hardpoint.

A hull's holes are scaled by BC's DamageRadMod (SetVisibleDamageRadiusModifier;
stations 8.0), but SetDamageResolution is authored for ship-sized holes. At the
authored cell the FedOutpost / SpaceFacility lattice was 13.4M cells, 512x what
its 8x holes need, and every whole-lattice pass at its death cost 130-240 ms in
Debug (perf-register P-4, SIG-032). So the cell grows with the modifier,
keeping twice the cell count a hole-matched lattice would have (Mark,
2026-10-18: about 50k for the station). A modifier of 1 -- every ship --
changes nothing.
"""
import types

import pytest

from engine.appc import hull_volume

STATION = 15.0 * 8.0 / 2.0 ** (1.0 / 3.0)


def test_ships_keep_their_authored_resolution():
    assert hull_volume.effective_resolution(10.0, 1.0) == 10.0


def test_a_station_cell_grows_with_its_hole_modifier():
    assert hull_volume.effective_resolution(15.0, 8.0) == pytest.approx(STATION)


@pytest.mark.parametrize("mod", [1.1, 0.5, 0.0, -3.0, None, "x"])
def test_a_small_or_bad_modifier_never_makes_a_lattice_finer(mod):
    assert hull_volume.effective_resolution(10.0, mod) == 10.0


class FakeShip:
    def __init__(self, resolution, radius_mod=None):
        self._resolution = resolution
        if radius_mod is not None:
            self._vis_dmg_radius_mod = radius_mod

    def GetDamageResolution(self):
        return self._resolution


class Recorder:
    def __init__(self):
        self.calls = []

    def hull_volume_set_resolution(self, iid, resolution):
        self.calls.append(("set", iid, resolution))

    def hull_volume_prewarm_model(self, handle, resolution):
        self.calls.append(("model", handle, resolution))


@pytest.fixture
def recorder(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(hull_volume, "_renderer", r)
    return r


def test_spawn_pushes_the_effective_resolution(recorder):
    assert hull_volume.push_resolution(FakeShip(15.0, radius_mod=8.0), 3)
    assert hull_volume.push_resolution(FakeShip(10.0), 4)
    (_, iid_a, res_a), (_, iid_b, res_b) = recorder.calls
    assert (iid_a, iid_b) == (3, 4)
    assert res_a == pytest.approx(STATION)
    assert res_b == 10.0


def test_warp_preload_prewarms_the_effective_resolution(recorder):
    assert hull_volume.prewarm_for_model(FakeShip(15.0, radius_mod=8.0), 9)
    (_, handle, res), = recorder.calls
    assert handle == 9
    assert res == pytest.approx(STATION)
