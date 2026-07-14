from engine.appc.characters import CharacterClass
from engine.core import stub_telemetry


def test_unknown_setter_is_recorded_in_stub_telemetry():
    stub_telemetry.reset()
    stub_telemetry.set_enabled(True)
    try:
        ch = CharacterClass("body.nif", "head.nif")
        ch.SetLookAtAdj(0, 0, 51)          # real SDK call (Felix.py:247), unimplemented
        snap = stub_telemetry.snapshot()
    finally:
        stub_telemetry.set_enabled(False)
        stub_telemetry.reset()
    assert any(
        "LookAtAdj" in str(k) for bucket in snap.values() for k in bucket
    ), snap


def test_numeric_getters_return_floats_not_none():
    ch = CharacterClass("body.nif", "head.nif")
    assert ch.GetBlinkChance() == 0.1              # BC's ctor default
    assert isinstance(ch.GetRandomAnimationChance(), float)
    ch.SetRandomAnimationChance(0.75)
    assert ch.GetRandomAnimationChance() == 0.75
