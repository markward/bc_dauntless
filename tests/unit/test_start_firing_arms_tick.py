"""StartFiring ARMS the BC weapon tick instead of dispatching directly.

Task 5 of the BC-faithful weapon dispatch branch: `WeaponSystem.StartFiring`
records held-trigger state (`_fire_held`, `_held_target`, `_held_offset`,
`_add_target`) and forces one immediate `update_weapons(0.0)` (SetForceUpdate
makes the inter-shot timer pass, so a single tap still fires this frame —
the SDK's FireWeapons does exactly StartFiring + SetForceUpdate(1)).
`StopFiring` disarms: clears the held state, the target list, and resets
`_last_group_fired` to the -1 sentinel.
"""
from engine.appc.weapon_subsystems import TorpedoSystem


class _LiveTarget:
    def IsDead(self): return False


def test_start_firing_arms_and_fires_via_force_update(monkeypatch):
    sys_ = TorpedoSystem("Torpedoes")
    sys_.TurnOn()
    fired = []
    monkeypatch.setattr(sys_, "update_weapons", lambda dt: fired.append(dt) or True)
    target = _LiveTarget()
    sys_.StartFiring(target, None)
    assert getattr(sys_, "_fire_held", False)
    assert target in sys_._target_list
    assert sys_.GetForceUpdate() == 1
    assert fired == [0.0]                 # immediate same-frame attempt


def test_stop_firing_disarms_and_clears_targets():
    sys_ = TorpedoSystem("Torpedoes")
    sys_.TurnOn()
    sys_.StartFiring(_LiveTarget(), None)
    sys_.StopFiring()
    assert not sys_._fire_held
    assert sys_.GetNumTargets() == 0
    assert sys_._last_group_fired == -1


def test_repeated_start_firing_is_idempotent():
    """AI scripts call StartFiring every evaluation tick — the same target
    must not be duplicated in the target list (see _add_target dedupe)."""
    sys_ = TorpedoSystem("Torpedoes")
    sys_.TurnOn()
    target = _LiveTarget()
    sys_.StartFiring(target, None)
    sys_.StartFiring(target, None)
    sys_.StartFiring(target, None)
    assert sys_.GetNumTargets() == 1
    assert sys_._fire_held


def test_is_firing_reflects_fire_held():
    """IsFiring() = any child firing OR the held trigger — the WeaponsDisplay
    and several SDK consumers read this on systems with no active emitter."""
    sys_ = TorpedoSystem("Torpedoes")
    sys_.TurnOn()
    assert sys_.IsFiring() == 0
    sys_.StartFiring(_LiveTarget(), None)
    assert sys_.IsFiring() == 1
    sys_.StopFiring()
    assert sys_.IsFiring() == 0
