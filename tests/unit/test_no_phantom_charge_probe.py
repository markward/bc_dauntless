"""_advance_weapons must not probe a torpedo tube for an EnergyWeapon API.

UpdateCharge/GetMaxCharge are bound exclusively on EnergyWeapon
(sdk/Build/scripts/App.py:6426-6440). BC's TorpedoTube never had them. But
host_loop.py:487 guarded with `hasattr(emitter, "UpdateCharge")`, and hasattr is
VACUOUSLY TRUE on every subsystem -- TGObject.__getattr__ (engine/core/ids.py:125)
returns a truthy _Stub for any missing attribute. So host_loop CALLED that stub on
every tube, every frame: 3.3M hits, rank 1 of docs/stub_heatmap.md.

This test asserts the probe is gone by watching stub_telemetry, which is what the
hasattr() lookup trips.
"""
from engine.appc.subsystems import TorpedoSystem, TorpedoTube, _EnergyWeaponFireMixin
from engine.core import stub_telemetry
from engine.host_loop import _advance_weapons


def _mro_has(cls, name: str) -> bool:
    return any(name in klass.__dict__ for klass in cls.__mro__)


def test_hasattr_is_vacuously_true_here():
    """Guard-rail documenting WHY isinstance is required. If this ever fails,
    _Stub's catch-all changed and the dispatch rule can be revisited."""
    tube = TorpedoTube("Forward Torpedo 1")
    assert hasattr(tube, "UpdateCharge")          # !!! true, and it is a _Stub
    assert hasattr(tube, "TotallyMadeUpMethod")   # !!! also true


def test_torpedo_tube_has_no_charge_api_in_its_mro():
    assert not _mro_has(TorpedoTube, "UpdateCharge")
    assert not _mro_has(TorpedoTube, "GetMaxCharge")
    assert not isinstance(TorpedoTube("t"), _EnergyWeaponFireMixin)


def test_advance_weapons_never_probes_a_tube_for_updatecharge(monkeypatch):
    """THE regression test. Ranks 1 and 2 of the heatmap, 4.5M hits."""
    hits = []
    monkeypatch.setattr(stub_telemetry, "ENABLED", True)
    monkeypatch.setattr(stub_telemetry, "record_attr",
                        lambda owner, attr: hits.append((owner, attr)))

    class _Ship:
        def __init__(self, system):
            self._system = system
        def GetTorpedoSystem(self):     return self._system
        def GetPhaserSystem(self):      return None
        def GetPulseWeaponSystem(self): return None
        def GetTractorBeamSystem(self): return None

    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    tube = TorpedoTube("Forward Torpedo 1")
    tube._max_ready = 1
    tube._num_ready = 1
    tube._resize_slots()
    system.AddChildSubsystem(tube)

    _advance_weapons([_Ship(system)], 1.0 / 60.0)

    charge_probes = [h for h in hits if h[1] in ("UpdateCharge", "GetMaxCharge")]
    assert charge_probes == [], (
        "_advance_weapons still probes a tube for an EnergyWeapon API: %r"
        % (charge_probes,))
