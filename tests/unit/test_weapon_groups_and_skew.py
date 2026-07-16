"""BC-faithful weapon groups, dumbfire flag, fire timer, and skew fire tests."""

from engine.appc.weapon_subsystems import TorpedoTube, TorpedoSystem
from engine.appc.properties import TorpedoTubeProperty


def _tube_with_groups(mask):
    tube = TorpedoTube("FT1")
    prop = TorpedoTubeProperty("FT1")
    prop.SetGroups(mask)
    tube.SetProperty(prop)
    return tube


def test_groups_bitmask_one_based_membership():
    # galaxy.py ForwardTorpedo1.SetGroups(25): bits {0,3,4} -> groups {1,4,5}
    tube = _tube_with_groups(25)
    assert tube.IsMemberOfGroup(1)
    assert tube.IsMemberOfGroup(4)
    assert tube.IsMemberOfGroup(5)
    assert not tube.IsMemberOfGroup(2)
    assert not tube.IsMemberOfGroup(3)


def test_group_zero_means_all_weapons():
    assert _tube_with_groups(0).IsMemberOfGroup(0)
    assert TorpedoTube("bare").IsMemberOfGroup(0)   # no property at all


def test_skew_fire_is_persistent_and_survives_firing():
    tube = _tube_with_groups(25)
    assert tube.IsSkewFire() == 0
    tube.SetSkewFire(1)
    assert tube.IsSkewFire() == 1
    tube.StopFiring()            # firing lifecycle must NOT clear it
    assert tube.IsSkewFire() == 1


def test_system_skew_broadcast_sets_children_only():
    sys_ = TorpedoSystem("Torpedoes")
    t1, t2 = _tube_with_groups(25), _tube_with_groups(26)
    sys_.AddChildSubsystem(t1)
    sys_.AddChildSubsystem(t2)
    sys_.SetSkewFire(1)
    assert t1.IsSkewFire() == 1 and t2.IsSkewFire() == 1
    assert not hasattr(sys_, "_skew_fire")   # no system-level flag (audited)


def test_tube_is_dumbfire_capable_banks_are_not():
    from engine.appc.weapon_subsystems import PhaserBank
    assert _tube_with_groups(0).IsDumbFire() == 1
    assert PhaserBank("bank").IsDumbFire() == 0


def test_leaf_emitters_never_skew_fire():
    # Leaf banks derive from WeaponSystem, not Weapon — without a base-class
    # IsSkewFire they hit the truthy _Stub in _spawn_projectile's skew probe
    # (stub-heatmap row PulseWeapon.IsSkewFire, 40 hits/run; masked today only
    # by the isinstance(GetRight(), TGPoint3) guard).
    from engine.appc.weapon_subsystems import PhaserBank, PulseWeapon
    for w in (PulseWeapon("cannon"), PhaserBank("bank")):
        got = w.IsSkewFire()
        assert got == 0
        assert isinstance(got, int)   # a real 0, not a truthy _Stub
