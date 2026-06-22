from engine.warp_vfx import WarpVFX


def test_inactive_by_default():
    w = WarpVFX()
    assert w.is_active() is False


def test_phases_and_turn():
    w = WarpVFX()
    w.start(heading=(1.0, 0.0, 0.0), t_align=2.0, t_transit=4.0, now=0.0)
    w.tick(0.0)
    assert w.phase() == "align" and w.turn_fraction() == 0.0
    assert w.streak_intensity() == 0.0          # no streak during align
    w.tick(1.0); assert 0.0 < w.turn_fraction() < 1.0
    w.tick(2.0); assert w.turn_fraction() == 1.0 and w.phase() == "transit"
    w.tick(4.0); assert w.streak_intensity() > 0.5   # streaking mid-transit
    # At align+transit (6.0) the transit is over but the manager stays active for
    # the post-arrival decel tail (phase "exit"), then deactivates after it.
    w.tick(6.0); assert w.is_active() is True and w.phase() == "exit"
    assert w.streak_intensity() == 0.0               # no streak during decel
    w.tick(8.0); assert w.is_active() is False        # done after the decel tail
    assert w.travel_dir() == (1.0, 0.0, 0.0)


def test_ship_speed_profile():
    # nominal=5, warp=600. align cruise -> last-1s boost -> transit 0 -> decel.
    w = WarpVFX()
    w.start(heading=(1.0, 0.0, 0.0), t_align=4.0, t_transit=4.0, now=0.0)
    # Cruise during early align (before the last-1s boost window at t=3..4).
    w.tick(1.0); assert w.ship_speed(5.0, 600.0) == 5.0
    w.tick(2.5); assert w.ship_speed(5.0, 600.0) == 5.0
    # Last second of align ramps cruise -> in-system warp.
    w.tick(3.5)
    s_boost = w.ship_speed(5.0, 600.0)
    assert 5.0 < s_boost < 600.0
    # Transit: camera ~still (0) so the slow dust drift isn't washed out.
    w.tick(6.0); assert w.ship_speed(5.0, 600.0) == 0.0
    # Exit decel tail: glides from warp speed down toward 0.
    w.tick(8.5)            # 0.5s into the 2s decel
    s_mid = w.ship_speed(5.0, 600.0)
    assert 0.0 < s_mid < 600.0
    w.tick(10.0); assert w.ship_speed(5.0, 600.0) == 0.0   # fully stopped at tail end


def test_flash_booms_at_burst_and_exit():
    w = WarpVFX(); w.start((1, 0, 0), 2.0, 4.0, 0.0)
    w.tick(2.0); assert w.flash_intensity() > 0.5     # burst boom at align end
    w.tick(4.0); assert w.flash_intensity() < 0.2     # quiet mid-transit
    w.tick(5.9); assert w.flash_intensity() > 0.3     # exit boom near end


def test_stop_resets():
    w = WarpVFX(); w.start((1, 0, 0), 2.0, 4.0, 0.0)
    w.stop()
    assert (w.is_active(), w.streak_intensity(), w.flash_intensity()) == (False, 0.0, 0.0)
