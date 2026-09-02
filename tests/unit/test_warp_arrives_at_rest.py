"""The warp exit must not shove the ship forward after it arrives.

Reported live in E3M2: warping into Vesuvi4 put the player inside the dust
cloud -- purple screen, immediate hull damage, the Berkeley reading 82.89 km
instead of 49.77, and no Hail option.

All four were ONE bug. A diagnostic at the arrival action proved the placement
was perfect: the ship landed on Vesuvi4's own "Player Start" (-1.7, -335.8,
0.2), 284.4 GU = 49.77 km from the Berkeley, with the nebula correct and
`player_inside=0`. Then the warp VFX manager moved it ~760 GU into the cloud
over the next two seconds, where concealment suppressed sensor identification
and therefore the hail button.

The mechanism is not a mistuned glide. `ship_speed` returns 0.0 for the whole
transit, so the ship is STATIONARY when it arrives -- and the exit phase then
returned `warp_speed * (1 - smooth(...))`, injecting full in-system warp speed
out of nothing and decaying it over _T_EXIT_DECEL. There was never a speed to
decelerate from.

This also restores BC's arrival behaviour, which `_PlacePlayerAction` already
documents from the reference: the ship arrives AT REST -- 243 reads of the
velocity vector, one write, all components zeroed. The exit override was
overriding that a frame later.

The exit PHASE is kept: it still runs, still reports `phase == "exit"`, and the
engine-glow envelope still cools the nacelles down. Only the forward speed is
zero, so the ship cools down where it arrived instead of flying on.
"""
from engine.warp_vfx import _T_EXIT_DECEL, _T_ENTER_BOOST


def _mgr(t_align=2.0, t_transit=10.0):
    """The real manager, driven on its own clock (`tick(now)` derives elapsed
    from the start time) rather than by poking private state."""
    from engine.warp_vfx import WarpVFX
    m = WarpVFX()
    m.start((0.0, 1.0, 0.0), t_align, t_transit, now=0.0)
    return m


def _advance(m, to):
    m.tick(to)
    return m


def test_the_ship_is_at_rest_the_moment_it_arrives():
    """Arrival is at `total`; the placement lands the ship here and BC leaves
    it at rest."""
    m = _mgr()
    total = 2.0 + 10.0
    _advance(m, total)

    assert m.ship_speed(nominal=5.0, warp_speed=800.0) == 0.0


def test_the_ship_stays_at_rest_through_the_exit_tail():
    """The whole decel window. Any non-zero here is distance travelled off the
    arrival marker -- at 800 GU/s even a fraction of a second is kilometres."""
    m = _mgr()
    total = 2.0 + 10.0
    for frac in (0.01, 0.25, 0.5, 0.75, 0.99):
        _advance(m, total + _T_EXIT_DECEL * frac)
        assert m.ship_speed(nominal=5.0, warp_speed=800.0) == 0.0, (
            "moving at %.0f%% through the exit tail" % (frac * 100))


def test_the_transit_is_still_stationary():
    """Unchanged, and the reason the old exit ramp made no physical sense:
    there is no speed to decelerate FROM."""
    m = _mgr()
    _advance(m, 2.0 + 5.0)

    assert m.ship_speed(nominal=5.0, warp_speed=800.0) == 0.0


def test_the_align_boost_is_untouched():
    """The pre-jump acceleration is real and must survive -- the ship really is
    flying then, and this is what the burst flash is timed against."""
    m = _mgr(t_align=2.0)
    _advance(m, 2.0 - _T_ENTER_BOOST * 0.5)
    mid = m.ship_speed(nominal=5.0, warp_speed=800.0)

    assert 5.0 < mid < 800.0, "align boost should ramp cruise -> warp speed"


def test_cruise_before_the_boost_is_untouched():
    m = _mgr(t_align=4.0)
    _advance(m, 1.0)

    assert m.ship_speed(nominal=5.0, warp_speed=800.0) == 5.0


def test_the_exit_phase_still_runs_for_the_visuals():
    """Only the SPEED is zeroed. The phase still exists so the nacelle glow
    cools down after arrival instead of cutting out."""
    m = _mgr()
    total = 2.0 + 10.0
    _advance(m, total + _T_EXIT_DECEL * 0.5)

    assert m._phase == "exit"
    assert m._active is True
