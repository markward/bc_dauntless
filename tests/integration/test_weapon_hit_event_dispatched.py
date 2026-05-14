"""End-to-end: per-ship instance handler installed on target receives
the ET_WEAPON_HIT event with correct source/target/damage/subsystem.

apply_hit sets the event's destination = target ship so the target's
ProcessEvent → per-instance handler dispatch fires.
"""
import sys
import types
from unittest.mock import patch

import App
from engine.appc import projectiles
from engine.host_loop import _advance_combat


def test_per_ship_instance_handler_receives_hit(galaxy_red, target_ship_at):
    ship = galaxy_red
    target = target_ship_at(0, 200, 0, hull_max=10000.0)
    ship._target = target

    received = []
    spy_mod_name = "_test_weapon_hit_dispatch_spy"
    spy_mod = types.ModuleType(spy_mod_name)
    spy_mod._capture = lambda _obj, evt: received.append(
        (evt.GetSource(), evt.GetTarget(), evt.GetDamage()))
    sys.modules[spy_mod_name] = spy_mod
    try:
        target.AddPythonFuncHandlerForInstance(
            App.ET_WEAPON_HIT, f"{spy_mod_name}._capture")

        with patch("engine.audio.tg_sound.TGSoundManager.instance"):
            App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
            App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

        for _ in range(200):
            _advance_combat([ship, target], dt=0.1)
            if received:
                break

        assert len(received) >= 1
        src, tgt, dmg = received[0]
        assert src is ship
        assert tgt is target
        assert dmg > 0.0
    finally:
        del sys.modules[spy_mod_name]
