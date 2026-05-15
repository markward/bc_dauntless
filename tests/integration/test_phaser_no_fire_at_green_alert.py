"""GREEN alert + LBUTTON-down → no phaser bank goes _firing."""
from unittest.mock import patch

import App
from engine.appc.ships import ShipClass


def test_lbutton_at_green_alert_silent(galaxy_red):
    """The shared fixture starts at RED; flip to GREEN and verify the
    multi-bank gate refuses to fire."""
    ship = galaxy_red
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    sys_ = ship.GetPhaserSystem()
    # Ensure banks have charge so the only gating factor is alert.
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    from engine.appc.math import TGPoint3
    class _Tgt:
        def GetWorldLocation(self):
            p = ship.GetWorldLocation()
            return TGPoint3(p.x, p.y + 100.0, p.z)
        def IsDead(self): return 0
    ship.SetTarget(_Tgt())

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_LBUTTON)
    firing = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    assert firing == 0, f"GREEN alert must suppress fire; got {firing} banks firing"
