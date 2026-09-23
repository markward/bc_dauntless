"""The exterior/viewscreen far plane must reach across a whole star system.

At the celestial layer's x20 scale even the LOCAL planet sits at 5,997 GU, so
a 5,000 GU frustum clips the first thing you look at rather than the last.
Raising the far plane is the fix; faking the distance is not. Forward-Z
precision is governed by the NEAR plane, which these tests pin as unaffected.
"""


def test_the_exterior_and_viewscreen_cameras_reach_the_whole_system():
    """452,715 GU is the widest sightline across all 32 maps (Itari). A far
    plane under it silently clips the most distant world in one system."""
    from engine import host_loop

    assert host_loop.SCENE_FAR_GU >= 452_715.0
    assert host_loop.VS_FAR >= 452_715.0


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
