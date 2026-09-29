from engine.systems.map import SystemMap
from tools.gen_system_maps import profile_from


def test_profile_from_reads_the_override():
    m = SystemMap(system="X", overrides={"profile": {"rows": [{"distance_gu": 0.0}]}})
    assert profile_from(m) == {"rows": [{"distance_gu": 0.0}]}
    assert profile_from(SystemMap(system="X")) is None
    assert profile_from(None) is None
