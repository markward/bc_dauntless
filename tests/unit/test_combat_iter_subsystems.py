"""Tests for combat._iter_subsystems — walks all leaf subsystems of a ship."""

from engine.appc.combat import _iter_subsystems


class _FakeSub:
    def __init__(self, name, children=None):
        self.name = name
        if children is not None:
            self._children = list(children)


class _FakeHull(_FakeSub):
    pass


class _FakeShip:
    def __init__(self, hull, subsystems):
        self._hull = hull
        self._subs = list(subsystems)

    def GetHull(self):
        return self._hull

    def GetSubsystems(self):
        return list(self._subs)


def _names(subs):
    return [s.name for s in subs]


def test_iter_subsystems_yields_top_level_plus_children_skipping_hull():
    hull = _FakeHull("Hull")
    sensors = _FakeSub("Sensors")
    phaser_bank_a = _FakeSub("PhaserA")
    phaser_bank_b = _FakeSub("PhaserB")
    weapons = _FakeSub("Weapons", children=[phaser_bank_a, phaser_bank_b])
    ship = _FakeShip(hull=hull, subsystems=[hull, sensors, weapons])

    out = list(_iter_subsystems(ship))

    assert _names(out) == ["Sensors", "Weapons", "PhaserA", "PhaserB"]
    assert hull not in out


def test_iter_subsystems_handles_no_children_attr():
    hull = _FakeHull("Hull")
    sensors = _FakeSub("Sensors")  # no _children attribute
    ship = _FakeShip(hull=hull, subsystems=[hull, sensors])

    out = list(_iter_subsystems(ship))

    assert _names(out) == ["Sensors"]


def test_iter_subsystems_handles_none_entries():
    hull = _FakeHull("Hull")
    sensors = _FakeSub("Sensors")
    ship = _FakeShip(hull=hull, subsystems=[hull, None, sensors])

    out = list(_iter_subsystems(ship))

    assert _names(out) == ["Sensors"]


def test_iter_subsystems_legacy_fallback_via_child_subsystem_index():
    """Stub ships that predate GetSubsystems still get walked via the
    legacy GetNumChildSubsystems / GetChildSubsystem path. Hull is still
    excluded.
    """
    hull = _FakeHull("Hull")
    sensors = _FakeSub("Sensors")
    weapons = _FakeSub("Weapons")

    class _LegacyShip:
        def GetHull(self):
            return hull

        def GetNumChildSubsystems(self):
            return 3

        def GetChildSubsystem(self, i):
            return [hull, sensors, weapons][i]

    out = list(_iter_subsystems(_LegacyShip()))

    assert _names(out) == ["Sensors", "Weapons"]
