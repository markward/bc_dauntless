from engine.warp_vfx import WarpVFX


def test_inactive_by_default():
    w = WarpVFX()
    assert w.is_active() is False


def test_vantage_lerps_src_to_dst():
    w = WarpVFX()
    w.start((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), duration=4.0,
            travel_dir=(1.0, 0.0, 0.0), now=100.0)
    assert w.is_active() is True
    w.tick(100.0); assert abs(w.vantage()[0] - 0.0) < 1e-6
    w.tick(102.0); assert abs(w.vantage()[0] - 5.0) < 1e-6   # halfway
    w.tick(104.0); assert abs(w.vantage()[0] - 10.0) < 1e-6  # end
    w.tick(104.0); assert w.is_active() is False             # done at/after duration


def test_streak_and_flash_envelopes():
    w = WarpVFX()
    w.start((0,0,0), (1,0,0), duration=4.0, travel_dir=(1,0,0), now=0.0)
    w.tick(0.0)
    # flash pulses high at entry, streak ramps in
    assert w.flash_intensity() > 0.5
    w.tick(2.0)
    assert w.streak_intensity() > 0.5      # streaking mid-transit
    assert w.flash_intensity() < 0.2       # entry flash faded
    w.tick(3.9)
    assert w.flash_intensity() > 0.3       # exit flash rising near the end


def test_stop_resets():
    w = WarpVFX()
    w.start((0,0,0), (1,0,0), 4.0, (1,0,0), 0.0)
    w.stop()
    assert w.is_active() is False
    assert w.streak_intensity() == 0.0 and w.flash_intensity() == 0.0
