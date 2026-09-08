"""BC authors a damage-volume resolution per ship; we never read it.

`ShipProperty.SetDamageResolution` is set in every hardpoint file (Shuttle 6,
Akira 8, Galaxy 10, Warbird 12, stations 15) and copied onto the ship at
engine/appc/ships.py:1164 -- into a field nothing consumes. It is the per-ship
detail ratio the hull-volume baker needs, and it is also finer than what BC
itself shipped: the Warbird's authored 12 against a baked cell size of 25 is
why its breaches cut into nothing.
"""
import pytest

from engine.appc import hull_volume


class FakeShip:
    def __init__(self, resolution):
        self._resolution = resolution

    def GetDamageResolution(self):
        return self._resolution


class Recorder:
    def __init__(self):
        self.calls = []

    def hull_volume_set_resolution(self, iid, resolution):
        self.calls.append((iid, resolution))


@pytest.fixture
def recorder(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(hull_volume, "_renderer", r)
    return r


def test_authored_resolution_reaches_the_renderer(recorder):
    assert hull_volume.push_resolution(FakeShip(8.0), 42) is True
    assert recorder.calls == [(42, 8.0)]


def test_each_ship_pushes_its_own_resolution(recorder):
    hull_volume.push_resolution(FakeShip(6.0), 1)    # Shuttle
    hull_volume.push_resolution(FakeShip(12.0), 2)   # Warbird
    assert recorder.calls == [(1, 6.0), (2, 12.0)]


def test_unset_resolution_is_not_pushed(recorder):
    """The field defaults to 0.0 (engine/appc/ships.py:91). Pushing that would
    make the baker divide by zero; the native default must stand instead."""
    assert hull_volume.push_resolution(FakeShip(0.0), 7) is False
    assert recorder.calls == []


def test_negative_resolution_is_not_pushed(recorder):
    assert hull_volume.push_resolution(FakeShip(-3.0), 7) is False
    assert recorder.calls == []


def test_a_ship_without_the_accessor_is_skipped(recorder):
    """Not every DamageableObject is a ShipClass."""
    assert hull_volume.push_resolution(object(), 7) is False
    assert recorder.calls == []


def test_a_renderer_failure_does_not_propagate(recorder, monkeypatch):
    """Spawn must never fail because a VFX detail could not be pushed."""
    def boom(iid, resolution):
        raise RuntimeError("no renderer")
    monkeypatch.setattr(recorder, "hull_volume_set_resolution", boom)
    assert hull_volume.push_resolution(FakeShip(10.0), 7) is False
