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

    # BC-faithful launch (Task 6): velocity is straight out each tube's
    # authored Direction, never aimed at the target.  Galaxy's two AFT tubes
    # (fixture position/rotation gives them world Direction (0,-1,0)) launch
    # straight AWAY from a target dead ahead; their limited guidance turn
    # rate (max_angular_accel) cannot complete a ~180 degree correction
    # within guidance_lifetime, so those two never reach the target and
    # instead run out their flight-time TTL. The 4 forward tubes still home
    # in and hit. Task 7's per-tube launch cone is what restores BC's actual
    # walk-out (narrow spread, no tubes firing backward); until then this
    # test ticks past TTL (30s) so the strays expire on time-out instead of
    # impact.
    for _ in range(320):
        _advance_combat([ship, target], dt=0.1)
        if len(projectiles._active) == 0:
            break

    final_hull = target.GetHull().GetCondition()
    assert final_hull < initial_hull, "target should have taken damage"
    assert len(projectiles._active) == 0, \
        "every torpedo should have resolved (impact or TTL expiry)"
