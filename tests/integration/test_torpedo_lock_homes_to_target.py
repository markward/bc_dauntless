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

    # Task 7's ship-wide 0.5s stagger throttles one tap to ONE launch: the
    # first tube in the round-robin working group (Forward Torpedo 1, index
    # 0), the only one that also clears the +/-30 degree cone against a
    # dead-ahead target — Galaxy's two AFT tubes (world Direction (0,-1,0))
    # would fail the cone outright and never launch at all (this restores
    # BC's actual walk-out: no tube ever fires backward at a forward target).
    assert len(projectiles._active) == 1
    torp = projectiles._active[0]
    assert torp._velocity.y > 0.0
    assert torp._target_ship is target

    # STRICT impact expectation (Task 7): every launch is now forward-facing
    # and cone-gated onto the resolved aim point, so the homing torpedo
    # should actually strike — no more TTL-timeout stray torpedoes to
    # paper over the assertion.
    for _ in range(320):
        _advance_combat([ship, target], dt=0.1)
        if len(projectiles._active) == 0:
            break

    final_hull = target.GetHull().GetCondition()
    assert final_hull < initial_hull, "target should have taken damage from an impact"
    assert len(projectiles._active) == 0, "the torpedo should have resolved"
