"""End-to-end: torpedo hits a ship; under the splash attribution model,
a subsystem whose splash sphere overlaps the impact point takes damage.

With pick_target_subsystem removed, subsystem damage is driven purely by
proximity.  The bridge is positioned at the ship centroid with a radius
large enough to guarantee the torpedo impact point falls within its splash
sphere regardless of where on the ship hull the torpedo detonates.
"""
from unittest.mock import patch

import App
from engine.appc import projectiles
from engine.appc.math import TGPoint3
from engine.appc.subsystems import SensorSubsystem
from engine.host_loop import _advance_combat


def test_subsystem_in_splash_range_takes_damage(galaxy_red, target_ship_at):
    """A subsystem centred on the ship and large enough to cover the hull
    radius will be hit by any torpedo impact on that ship.

    Target ship radius = 20.  Bridge centred at body (0,0,0) with
    r_sub = 25 → splash threshold r_sub + r_hit >= 25.15.  The torpedo
    hit point is always on or inside the bounding sphere (distance ≤ 20
    from centre), so it falls well within the threshold.
    """
    ship = galaxy_red
    target = target_ship_at(0, 200, 0, hull_max=10000.0)

    bridge = SensorSubsystem("Bridge")
    bridge.SetMaxCondition(500.0)
    bridge._parent_ship = target
    bridge._position = TGPoint3(0, 0, 0)   # centroid
    bridge._radius = 25.0                   # covers full bounding sphere
    # Attach via the named slot that GetSubsystems() walks.
    target._sensor_subsystem = bridge

    ship._target = target

    initial_bridge = bridge.GetCondition()

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    for _ in range(200):
        _advance_combat([ship, target], dt=0.1)
        if len(projectiles._active) == 0:
            break

    assert bridge.GetCondition() < initial_bridge, "bridge should have taken damage"
