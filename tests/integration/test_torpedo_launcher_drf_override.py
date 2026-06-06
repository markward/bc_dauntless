"""Torpedo spawn propagates launcher hardpoint DRF to the torpedo object.

Per spec §3.2 the hardpoint DRF takes precedence over the payload DRF.
In the torpedo path host_loop passes the torpedo itself as
``hardpoint_weapon`` to ``apply_hit``; therefore the torpedo must carry
the launcher's DRF after spawn so that ``weapon_splash_radius`` returns
the correct value.

Scenario:
  - Galaxy ForwardTorpedo1 calls SetDamageRadiusFactor(0.20) in galaxy.py.
  - PhotonTorpedo.py:48 calls pTorp.SetDamageRadiusFactor(0.13) during
    mod.Create(torp).
  - After spawn the torpedo's _damage_radius_factor must be 0.20 (launcher),
    not 0.13 (payload).
"""
from unittest.mock import patch

import pytest

import App
from engine.appc import projectiles
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import TorpedoTube


def _find_torpedo_tube(ship):
    """Walk subsystems to locate the first TorpedoTube child."""
    for sub in ship.GetSubsystems():
        if isinstance(sub, TorpedoTube):
            return sub
        for child in getattr(sub, "_children", []) or []:
            if isinstance(child, TorpedoTube):
                return child
    return None


def test_launcher_drf_overrides_payload_drf_on_spawn(galaxy_red):
    """After firing from Galaxy ForwardTorpedo1 (DRF=0.20), the spawned
    torpedo's _damage_radius_factor must equal 0.20, not the PhotonTorpedo
    payload value of 0.13.

    Uses the ``galaxy_red`` fixture (RED alert, hardpoints loaded) so the
    tube is properly configured and CanFire() returns True.
    """
    ship = galaxy_red

    tube = _find_torpedo_tube(ship)
    assert tube is not None, "Galaxy must have at least one TorpedoTube"

    # Confirm the launcher has DRF 0.20 as set by galaxy.py.
    launcher_drf = tube.GetDamageRadiusFactor()
    assert launcher_drf == pytest.approx(0.20), (
        f"Galaxy ForwardTorpedo1 should have DRF=0.20 per galaxy.py; "
        f"got {launcher_drf}"
    )

    # Make sure there's a shot ready (SetupProperties sets _num_ready via
    # MaxReady, but belt-and-suspenders for clarity).
    if tube.GetNumReady() == 0:
        tube.SetNumReady(1)

    # Place a dummy target so _spawn_torpedo can resolve aim direction.
    from engine.appc.subsystems import HullSubsystem
    from engine.appc.ships import ShipClass_Create
    target = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(100000.0)
    target._hull = hull
    target.SetWorldLocation(TGPoint3(0, 200, 0))
    ship._target = target

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=target, offset=None)

    assert len(projectiles._active) == 1, (
        "exactly one torpedo should be in flight after TorpedoTube.Fire"
    )
    torp = projectiles._active[0]

    assert torp._damage_radius_factor == pytest.approx(0.20), (
        f"torpedo._damage_radius_factor should be launcher DRF 0.20, "
        f"not payload DRF 0.13; got {torp._damage_radius_factor}"
    )


def test_payload_drf_used_when_launcher_drf_is_zero(galaxy_red):
    """When a tube has DRF=0 (not set in the hardpoint script), the
    torpedo retains the payload's DRF from mod.Create.

    Zero out the tube's DRF to simulate a launcher with no hardpoint
    DRF configured, then fire and assert the torpedo keeps the payload value.
    """
    ship = galaxy_red

    tube = _find_torpedo_tube(ship)
    assert tube is not None, "Galaxy must have at least one TorpedoTube"

    # Zero out the launcher DRF to simulate the no-hardpoint-DRF case.
    tube.SetDamageRadiusFactor(0.0)
    assert tube.GetDamageRadiusFactor() == 0.0

    if tube.GetNumReady() == 0:
        tube.SetNumReady(1)

    from engine.appc.subsystems import HullSubsystem
    from engine.appc.ships import ShipClass_Create
    target = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(100000.0)
    target._hull = hull
    target.SetWorldLocation(TGPoint3(0, 200, 0))
    ship._target = target

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=target, offset=None)

    assert len(projectiles._active) == 1, (
        "torpedo should have been spawned"
    )
    torp = projectiles._active[0]

    # Payload DRF from PhotonTorpedo.py:48 is 0.13.
    assert torp._damage_radius_factor == pytest.approx(0.13), (
        f"when launcher DRF is 0, torpedo should keep payload DRF 0.13; "
        f"got {torp._damage_radius_factor}"
    )
