"""The exterior/viewscreen far plane must reach across a whole star system.

At the celestial layer's x20 scale even the LOCAL planet sits at 5,997 GU, so
a 5,000 GU frustum clips the first thing you look at rather than the last.
Raising the far plane is the fix; faking the distance is not. Forward-Z
precision is governed by the NEAR plane, which these tests pin as unaffected.

The widest sightline is DERIVED from the checked-in maps here, never restated.
The design says in bold that the figure "is a product of the maps and must be
rechecked whenever they are regenerated", and that a far plane which no longer
covers it "does not fail loudly -- it silently clips the most distant world in
one system". A guard that hard-codes the number cannot catch that: it agrees
with itself while the maps move underneath it. The number has already moved
once, 420,676 -> 452,715 GU in a single generator change (+7.6%).
"""
import itertools
import math


def widest_sightline_gu():
    """The longest line of sight the maps can produce, in game units.

    Per system: the greatest distance between any two reference points --
    every body position and every region anchor, which is where a camera can
    actually stand -- PLUS that system's largest body radius, because what
    clips is a body's far LIMB, not its centre. Radii run to 14,000 GU
    (Chambana's star), which is a third of the headroom a centre-to-centre
    figure appears to leave.

    Returns the max across every map in engine/systems/maps.
    """
    from engine.systems import map as system_map

    widest = 0.0
    for system in system_map.available():
        m = system_map.load(system)
        points = ([tuple(b.position_gu) for b in m.bodies]
                  + [tuple(r.anchor_gu) for r in m.regions])
        span = max((math.dist(a, b)
                    for a, b in itertools.combinations(points, 2)), default=0.0)
        limb = max((b.radius_gu for b in m.bodies), default=0.0)
        widest = max(widest, span + limb)
    return widest


def test_the_exterior_and_viewscreen_cameras_reach_the_whole_system():
    """A far plane under the widest sightline silently clips the most distant
    world in one system. Derived from the maps, so regenerating them moves
    this bound and the guard moves with it."""
    from engine import host_loop

    widest = widest_sightline_gu()
    assert widest > 0.0, "no system maps found -- the guard is checking nothing"
    assert host_loop.SCENE_FAR_GU >= widest, (
        f"exterior far plane {host_loop.SCENE_FAR_GU:,.0f} GU does not cover "
        f"the widest sightline the maps produce, {widest:,.0f} GU")
    assert host_loop.VS_FAR >= widest, (
        f"viewscreen far plane {host_loop.VS_FAR:,.0f} GU does not cover "
        f"the widest sightline the maps produce, {widest:,.0f} GU")


def test_the_derived_sightline_accounts_for_a_bodys_far_limb():
    """The half of the bound a centre-to-centre figure drops. Itari's
    centre-to-centre span is ~452,715 GU; its largest body is not a point."""
    from engine.systems import map as system_map

    centres_only = 0.0
    for system in system_map.available():
        m = system_map.load(system)
        points = ([tuple(b.position_gu) for b in m.bodies]
                  + [tuple(r.anchor_gu) for r in m.regions])
        centres_only = max(centres_only, max(
            (math.dist(a, b)
             for a, b in itertools.combinations(points, 2)), default=0.0))
    assert widest_sightline_gu() > centres_only


def test_the_bridge_camera_is_left_alone():
    """A room. Raising its far plane costs precision for nothing."""
    from engine import host_loop

    assert host_loop._BridgeCamera.FAR == 800.0


def test_depth_precision_is_effectively_unchanged():
    """The whole argument for raising the far plane rather than faking the
    distance. Forward-Z precision is governed by the NEAR plane."""
    from engine import host_loop

    def dz(z, n, f):
        return (1.0 / 2**24) * z * z * (f - n) / (f * n)

    before = dz(4900.0, 1.0, 5000.0)
    after = dz(4900.0, 1.0, host_loop.SCENE_FAR_GU)
    assert after / before < 1.001
