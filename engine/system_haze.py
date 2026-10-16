"""The one builder for the system-nebula ("haze") profile dict.

The arrival push (host_loop._push_system_nebula) and the warp preload must
hand the native layer an identical dict: its far-field table cache is keyed
on the dict's contents, so any difference is a cache miss and a multi-second
rebuild.
"""
from engine.cameras import SCENE_FAR_GU


def profile_dict(m, *, veil, dials, far_gu):
    """The dict pushed to set_system_nebula_profile, or None when `m` is
    None, has no profile, or has no star."""
    if m is None or m.profile is None:
        return None
    star = next((b for b in m.bodies if b.orbits is None), None)
    if star is None:
        return None
    from engine.systems import profile as _profile
    colour = m.profile.color or (0.0, 0.0, 0.0)
    star_rgb = (tuple(star.appearance.color) if star.appearance.color
                else (1.0, 1.0, 1.0))
    return {
        "r": [row.distance_gu for row in m.profile.rows],
        "nebula": [row.nebula for row in m.profile.rows],
        "k_sys": _profile.k_sys(m, veil),
        "star_radius": star.radius_gu,
        "cloud_rgb": tuple(colour),
        "star_rgb": star_rgb,
        "far_gu": far_gu,
        "g": dials["g"],
        "floor": dials["floor"],
    }


def profile_dict_for_set(set_name):
    """profile_dict for the system a set belongs to, or None."""
    from engine import dev_nebula_dials
    from engine.systems import resolve
    found = resolve.for_set(set_name)
    if found is None:
        return None
    return profile_dict(found[0], veil=dev_nebula_dials.veil(),
                        dials=dev_nebula_dials.current(),
                        far_gu=SCENE_FAR_GU)
