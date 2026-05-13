"""populated_subsystems includes Power + Repair entries in canonical order."""
from engine.ui.target_list import populated_subsystems, _SUBSYSTEM_GETTERS


def test_power_and_repair_are_in_getter_list():
    labels = [label for label, _ in _SUBSYSTEM_GETTERS]
    assert "Power Plant" in labels
    assert "Engineering" in labels


def test_canonical_order_places_defensive_before_offensive():
    """Roughly: hull -> shield -> sensor -> power -> engineering ->
    impulse -> warp -> phaser -> pulse -> torpedo -> tractor."""
    labels = [label for label, _ in _SUBSYSTEM_GETTERS]
    # Use index comparisons rather than asserting the full order so
    # later canonical-order tweaks don't churn this test.
    assert labels.index("Hull")               < labels.index("Shield Generator")
    assert labels.index("Shield Generator")   < labels.index("Sensor Subsystem")
    assert labels.index("Sensor Subsystem")   < labels.index("Power Plant")
    assert labels.index("Power Plant")        < labels.index("Engineering")
    assert labels.index("Engineering")        < labels.index("Impulse Engines")
    assert labels.index("Phaser System")      < labels.index("Tractor Beam System")


class _ShipWithPowerAndRepair:
    class _Sub:
        def __init__(self, n): self._n = n
        def GetName(self): return self._n
    def GetHull(self):              return None
    def GetSensorSubsystem(self):   return None
    def GetImpulseEngineSubsystem(self): return None
    def GetWarpEngineSubsystem(self):    return None
    def GetPhaserSystem(self):           return None
    def GetPulseWeaponSystem(self):      return None
    def GetTorpedoSystem(self):          return None
    def GetTractorBeamSystem(self):      return None
    def GetShieldSubsystem(self):        return None
    def GetPowerSubsystem(self):         return self._Sub("Power Plant")
    def GetRepairSubsystem(self):        return self._Sub("Engineering")


def test_populated_includes_power_and_repair_when_present():
    rows = populated_subsystems(_ShipWithPowerAndRepair())
    labels = [label for label, _ in rows]
    assert labels == ["Power Plant", "Engineering"]
