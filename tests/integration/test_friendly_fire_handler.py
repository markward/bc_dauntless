"""End-to-end: friendly NPC in front of player + lock + fire →
ET_WEAPON_HIT broadcast handler invoked.

We install a spy broadcast handler so the test doesn't depend on
MissionLib.FriendlyFireHandler being functional in headless mode
(it requires mission state we don't set up here).  The spy fires
whenever apply_hit broadcasts a WeaponHitEvent.
"""
import sys
import types
from unittest.mock import patch

import App
from engine.appc import projectiles
from engine.host_loop import _advance_combat


def test_friendly_fire_event_broadcast(galaxy_red, target_ship_at):
    ship = galaxy_red
    target = target_ship_at(0, 200, 0)
    ship._target = target

    spy = []

    def handler(_obj, evt):
        spy.append(evt.GetTarget())

    mod = types.ModuleType("_test_friendly_fire_spy")
    mod.handler = handler
    sys.modules["_test_friendly_fire_spy"] = mod
    try:
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_WEAPON_HIT, None,
            "_test_friendly_fire_spy.handler",
        )

        with patch("engine.audio.tg_sound.TGSoundManager.instance"):
            App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
            App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

        for _ in range(200):
            _advance_combat([ship, target], dt=0.1)
            if spy:
                break

        # A single tap launches exactly one torpedo (Task 7's ship-wide 0.5s
        # stagger gate — SetSingleFire(0) no longer means "every ready tube
        # in the same tick"; the stagger throttles the whole system to one
        # launch per tap).
        assert len(spy) == 1
        assert all(t is target for t in spy)
    finally:
        App.g_kEventManager.RemoveBroadcastHandler(
            App.ET_WEAPON_HIT, None, "_test_friendly_fire_spy.handler")
        del sys.modules["_test_friendly_fire_spy"]
