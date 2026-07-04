"""Target reticle text overlay (name + range/speed) — pure Python.

Projects the box top/bottom world points to screen with the gameplay camera
(the same one the GL reticle pass uses) so the labels align with the box.
Driven imperatively from host_loop; rendered by reticle_text.js in CEF.
See docs/superpowers/specs/2026-06-09-reticle-chrome-bars-text-design.md
"""
from __future__ import annotations

from engine.units import GU_TO_KM, GUPS_TO_KPH
from engine.ui.ship_property_viewer import project
from engine.ui.target_reticle import _valid_target, _valid_subsystem


class _ReticleCam:
    """Adapter exposing the interface ship_property_viewer.project expects
    (eye()/up() methods; target/fov_y_rad/near/far attributes), built from the
    gameplay camera params host_loop already computes."""
    def __init__(self, eye, target, up, fov_y_rad, near, far):
        self._eye = eye
        self.target = target
        self._up = up
        self.fov_y_rad = fov_y_rad
        self.near = near
        self.far = far

    def eye(self):
        return self._eye

    def up(self):
        return self._up


def build_reticle_text(player, camera, viewport) -> dict:
    """Return {visible, name, line2, name_xy, line2_xy}.

    name = locked subsystem name if any, else target ship name.
    line2 = "<range> km / <speed> kph". Hidden when no target or the box
    top/bottom project behind the camera / off-clip.
    """
    target = _valid_target(player)
    if target is None:
        return {"visible": False}

    centre = target.GetWorldLocation()
    pc = player.GetWorldLocation()
    dx, dy, dz = centre.x - pc.x, centre.y - pc.y, centre.z - pc.z
    dist_gu = (dx * dx + dy * dy + dz * dz) ** 0.5
    radius = target.GetRadius() if hasattr(target, "GetRadius") else 0.0
    # BC's range readout is the distance to the target's BOUNDING SPHERE,
    # not to its centre. Confirmed against the original game by orbiting
    # Haven (radius 90 GU): BC reads ~25 km, which is the authored
    # CircleObject radius+150 GU orbit measured from the surface
    # (150 GU ≈ 26 km); a centre-distance readout would say 42 km, and the
    # planet itself renders wider than 25 km. Negligible for small ships,
    # decisive for planets/stations.
    dist_gu = dist_gu - radius if dist_gu > radius else 0.0
    vel = target.GetVelocity() if hasattr(target, "GetVelocity") else None
    speed_gu = (vel.x * vel.x + vel.y * vel.y + vel.z * vel.z) ** 0.5 if vel else 0.0

    sub = _valid_subsystem(player)
    name = sub.GetName() if sub is not None else target.GetName()
    line2 = "%.2f km / %.0f kph" % (dist_gu * GU_TO_KM, speed_gu * GUPS_TO_KPH)
    up = camera.up()
    top    = (centre.x + up[0] * radius, centre.y + up[1] * radius, centre.z + up[2] * radius)
    bottom = (centre.x - up[0] * radius, centre.y - up[1] * radius, centre.z - up[2] * radius)
    tsx, tsy, _td, tvis = project(top, camera, viewport)
    bsx, bsy, _bd, bvis = project(bottom, camera, viewport)
    if not (tvis and bvis):
        return {"visible": False}

    return {
        "visible": True,
        "name": name,
        "line2": line2,
        "name_xy": (tsx, tsy),
        "line2_xy": (bsx, bsy),
    }
