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
    w.tick(6.0); assert w.is_active() is False        # done at align+transit
    assert w.travel_dir() == (1.0, 0.0, 0.0)


def test_flash_booms_at_burst_and_exit():
    w = WarpVFX(); w.start((1, 0, 0), 2.0, 4.0, 0.0)
    w.tick(2.0); assert w.flash_intensity() > 0.5     # burst boom at align end
    w.tick(4.0); assert w.flash_intensity() < 0.2     # quiet mid-transit
    w.tick(5.9); assert w.flash_intensity() > 0.3     # exit boom near end


def test_stop_resets():
    w = WarpVFX(); w.start((1, 0, 0), 2.0, 4.0, 0.0)
    w.stop()
    assert (w.is_active(), w.streak_intensity(), w.flash_intensity()) == (False, 0.0, 0.0)
