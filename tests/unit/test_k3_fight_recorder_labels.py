"""The k3_fight Recorder's labels are unique (native damage task review M6).

A recorded ship's subsystem is labelled by name, and a set by name, so the
two arms -- which first see them in different orders -- agree. Two
same-named subsystems of one ship must still get different labels, or a
delivery naming the wrong one of them would compare equal."""
import types

import pytest

from engine.appc.ships import ShipClass_Create
from engine.appc.sets import SetClass_Create
from engine.appc.subsystems import PhaserSystem, PhaserBank
from tests.helpers.k3_fight import Recorder


def _recorder(ships):
    rec = types.SimpleNamespace(
        labels={id(s): s.GetName() for s in ships}, named=[], held=[],
        torps=[], torp_ids=set())
    return rec, lambda obj: Recorder.label(rec, obj)


def _ship_with_two_banks(name):
    ship = ShipClass_Create(name)
    system = PhaserSystem("Phasers")
    first, second = PhaserBank("Phaser"), PhaserBank("Phaser")
    for bank in (first, second):
        system.AddChildSubsystem(bank)
    ship.SetPhaserSystem(system)
    return ship, first, second


def test_same_named_subsystems_of_one_ship_get_different_labels():
    ship, first, second = _ship_with_two_banks("A")
    _rec, label = _recorder([ship])
    # Seen in either order, each keeps its place-in-the-ship label.
    assert label(second) == "A/Phaser[1]"
    assert label(first) == "A/Phaser[0]"
    assert label(first) == "A/Phaser[0]"
    assert label(ship.GetPhaserSystem()) == "A/Phasers"


def test_a_label_taken_by_another_object_is_refused():
    a = SetClass_Create()
    a.SetName("Region")
    b = SetClass_Create()
    b.SetName("Region")
    _rec, label = _recorder([])
    assert label(a) == "set:Region"
    with pytest.raises(AssertionError, match="set:Region"):
        label(b)
