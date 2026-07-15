"""End-to-end: Galaxy at RED + locked target ahead.  Right-click →
torpedo's initial velocity points at target.  After several ticks
position is closer to target.  Eventually collides; target hull
condition decreases.
"""
from unittest.mock import patch

import App
from engine.appc import projectiles
from engine.host_loop import _advance_combat


def test_torpedo_homes_to_target_and_damages_hull(galaxy_red, target_ship_at):
    ship = galaxy_red
    target = target_ship_at(0, 200, 0, hull_max=10000.0)
    ship._target = target

    initial_hull = target.GetHull().GetCondition()

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    # Torpedoes spawned and homing.  One tap fires EVERY ready tube in the
    # working group (Galaxy chain "Single" = group 0 = all 6 tubes,
    # SetSingleFire(0) multi-fire) — a transient mid-branch state: Task 7's
    # ship-wide 0.5 s stagger + per-tube launch cone restore the BC walk-out.
    assert len(projectiles._active) == 6
    torp = projectiles._active[0]
    assert torp._velocity.y > 0.0
    assert torp._target_ship is target

    # Tick until collision (PhotonTorpedo launch_speed = 19; 200 / 19 ≈ 10.5s).
    for _ in range(200):
        _advance_combat([ship, target], dt=0.1)
        if len(projectiles._active) == 0:
            break

    final_hull = target.GetHull().GetCondition()
    assert final_hull < initial_hull, "target should have taken damage"
    assert len(projectiles._active) == 0, "torpedo should have expired on impact"
