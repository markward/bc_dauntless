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
    # Exit tail: the ship HAS ARRIVED and does not move.
    #
    # ⚠️ This assertion was INVERTED on 2026-09-02, and deliberately: it used
    # to require `0.0 < s_mid < 600.0`, pinning a "glide-in" that was the bug.
    # Transit speed is already 0 (line above), so the exit was not decelerating
    # from anything -- it injected full in-system warp speed one frame AFTER
    # the arrival placement had set the ship down and zeroed its velocity, then
    # decayed it. Live in E3M2 that carried the player ~760 GU off the arrival
    # marker into a nebula. See tests/unit/test_warp_arrives_at_rest.py for the
    # full account. Changed to accommodate a behaviour fix, NOT relaxed to make
    # a failure go away.
    w.tick(8.5)            # 0.5s into the 2s tail
    assert w.ship_speed(5.0, 600.0) == 0.0
    w.tick(10.0); assert w.ship_speed(5.0, 600.0) == 0.0


def test_flash_booms_at_burst_and_exit():
    w = WarpVFX(); w.start((1, 0, 0), 2.0, 4.0, 0.0)
    w.tick(2.0); assert w.flash_intensity() > 0.5     # burst boom at align end
    w.tick(4.0); assert w.flash_intensity() < 0.2     # quiet mid-transit
    w.tick(5.9); assert w.flash_intensity() > 0.3     # exit boom near end


def test_sky_vantage_advances_along_heading_during_transit():
    # Vantage flies forward along the heading at `rate` u/s across the transit,
    # held at the start during align and at the end during the decel tail.
    w = WarpVFX()
    w.start(heading=(0.0, 0.0, 1.0), t_align=2.0, t_transit=4.0, now=0.0,
            vantage=(10.0, 0.0, 0.0))
    w.tick(1.0); assert w.sky_vantage(5.0) == (10.0, 0.0, 0.0)   # align: held at start
    w.tick(2.0); assert w.sky_vantage(5.0) == (10.0, 0.0, 0.0)   # burst: te=0
    w.tick(4.0)                                                   # 2s into transit
    assert w.sky_vantage(5.0) == (10.0, 0.0, 10.0)               # +rate*te along +z
    w.tick(8.0)                                                   # past transit (exit)
    assert w.sky_vantage(5.0) == (10.0, 0.0, 20.0)               # clamped at t_transit


def test_sky_vantage_none_when_unmapped():
    w = WarpVFX()
    w.start(heading=(0.0, 0.0, 1.0), t_align=2.0, t_transit=4.0, now=0.0)  # no vantage
    w.tick(4.0)
    assert w.sky_vantage(5.0) is None


def test_sky_vantage_arrives_at_destination_when_both_mapped():
    # When both endpoints are galaxy-mapped the vantage interpolates src->dst and
    # lands EXACTLY on dst at transit end, so the destination's own nebula looms
    # ahead and envelops on arrival (continuous with the in-system projection)
    # instead of streaming past and vanishing before exit. `rate` is ignored here.
    w = WarpVFX()
    w.start(heading=(0.0, 0.0, 1.0), t_align=2.0, t_transit=4.0, now=0.0,
            vantage=(0.0, 0.0, 0.0), dst_vantage=(0.0, 0.0, 40.0))
    w.tick(2.0); assert w.sky_vantage(5.0) == (0.0, 0.0, 0.0)     # burst: at src
    w.tick(4.0); assert w.sky_vantage(5.0) == (0.0, 0.0, 20.0)    # half transit: midpoint
    w.tick(6.0); assert w.sky_vantage(5.0) == (0.0, 0.0, 40.0)    # transit end: at dst
    w.tick(8.0); assert w.sky_vantage(5.0) == (0.0, 0.0, 40.0)    # exit decel: held at dst


def test_sky_vantage_legacy_rate_advance_when_destination_unmapped():
    # Destination not galaxy-mapped (dst_vantage None): keep the legacy
    # fixed-rate parallax along the heading from the source vantage.
    w = WarpVFX()
    w.start(heading=(0.0, 0.0, 1.0), t_align=2.0, t_transit=4.0, now=0.0,
            vantage=(10.0, 0.0, 0.0))  # no dst_vantage
    w.tick(4.0); assert w.sky_vantage(5.0) == (10.0, 0.0, 10.0)   # +rate*te along +z


def test_stop_resets():
    w = WarpVFX(); w.start((1, 0, 0), 2.0, 4.0, 0.0)
    w.stop()
    assert (w.is_active(), w.streak_intensity(), w.flash_intensity()) == (False, 0.0, 0.0)


# --- warp-engine glow envelope -------------------------------------------
# engine_glow() -> (drive, burst), both 0..1 SHAPES (not brightnesses): the
# nacelle drive spools up across align, holds through transit and fades over
# the exit decel; the burst is a one-shot spike at the jump. They are mapped
# onto an actual shader gain by subsystem_glow.warp_gain.

def test_engine_glow_is_zero_while_inactive():
    w = WarpVFX()
    assert w.engine_glow() == (0.0, 0.0)


def test_engine_glow_drive_spools_up_across_align():
    w = WarpVFX(); w.start((1, 0, 0), t_align=2.0, t_transit=4.0, now=0.0)
    w.tick(0.0)
    assert w.engine_glow()[0] == 0.0          # cold at align start
    w.tick(1.0)
    mid = w.engine_glow()[0]
    assert 0.0 < mid < 1.0                    # spooling
    w.tick(1.9)
    assert w.engine_glow()[0] > mid           # monotonically building


def test_engine_glow_bursts_at_the_jump_and_decays_quickly():
    w = WarpVFX(); w.start((1, 0, 0), t_align=2.0, t_transit=4.0, now=0.0)
    w.tick(2.0)                               # e == t_align: the jump
    drive, burst = w.engine_glow()
    assert drive == 1.0 and burst == 1.0
    w.tick(2.2)                               # mid-decay
    assert 0.0 < w.engine_glow()[1] < 1.0
    w.tick(2.5)                               # past BURST_DECAY_S: spike is spent
    assert w.engine_glow()[1] == 0.0
    w.tick(4.0)                               # mid-transit: driven, no burst
    assert w.engine_glow() == (1.0, 0.0)


def test_engine_glow_fades_over_the_exit_decel():
    w = WarpVFX(); w.start((1, 0, 0), t_align=2.0, t_transit=4.0, now=0.0)
    w.tick(6.0)                               # transit end: still at full drive
    assert w.engine_glow()[0] == 1.0
    w.tick(7.0)                               # 1s into the 2s decel tail
    mid = w.engine_glow()[0]
    assert 0.0 < mid < 1.0
    w.tick(8.0)                               # tail end: cold, and inactive
    assert w.engine_glow() == (0.0, 0.0)
