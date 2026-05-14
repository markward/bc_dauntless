"""End-to-end: target lock + target-subsystem cycled to a specific
subsystem.  Fire → damage applied to that subsystem specifically.
"""
from unittest.mock import patch

import App
from engine.appc import projectiles
from engine.appc.math import TGPoint3
from engine.appc.subsystems import SensorSubsystem
from engine.host_loop import _advance_combat


def test_targeted_subsystem_takes_damage(galaxy_red, target_ship_at):
    ship = galaxy_red
    target = target_ship_at(0, 200, 0, hull_max=10000.0)

    bridge = SensorSubsystem("Bridge")
    bridge.SetMaxCondition(500.0)
    bridge._parent_ship = target
    bridge._position = TGPoint3(0, 5, 0)
    bridge._radius = 5.0
    target._children = [bridge]

    ship._target = target
    ship._target_subsystem = bridge

    initial_bridge = bridge.GetCondition()

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    for _ in range(200):
        _advance_combat([ship, target], dt=0.1)
        if len(projectiles._active) == 0:
            break

    assert bridge.GetCondition() < initial_bridge, "bridge should have taken damage"
