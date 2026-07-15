"""End-to-end: Galaxy at RED + no target.  Right-click → torpedo flies
along emitter direction.  No homing.  Expires on TTL without hitting
anything when there's no ship in front.
"""
from unittest.mock import patch

import App
from engine.appc import projectiles
from engine.host_loop import _advance_combat


def test_dumbfire_no_target_torpedo_expires_on_ttl(galaxy_red):
    ship = galaxy_red
    ship._target = None  # explicit

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    # One tap fires every ready tube in the working group (all 6 — see
    # test_torpedo_lock_homes_to_target for why; transient until Task 7).
    assert len(projectiles._active) == 6
    torp = projectiles._active[0]
    assert torp._target_ship is None
    assert torp._velocity.Length() > 0.0

    # Snapshot initial velocity.
    vx0, vy0, vz0 = torp._velocity.x, torp._velocity.y, torp._velocity.z

    # Tick 5s — well within 30s TTL, no targets in this test.
    for _ in range(50):
        _advance_combat([ship], dt=0.1)

    # Velocity unchanged (no steering).
    assert torp._velocity.x == vx0
    assert torp._velocity.y == vy0
    assert torp._velocity.z == vz0
    # Still active.
    assert len(projectiles._active) == 6

    # Tick past TTL (30s default).
    for _ in range(310):
        _advance_combat([ship], dt=0.1)

    assert len(projectiles._active) == 0
