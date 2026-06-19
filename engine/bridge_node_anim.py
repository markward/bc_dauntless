"""BridgeNodeAnimController — plays chair clips on the bridge (non-skinned)
instance and couples a seated officer to the animated 'console seat NN' node so
the chair carries the officer. This is the chair half of the turn-to-captain
flow; the officer's BODY clip still plays via BridgeCharacterAnimController.

Coupling math (row-major 4x4): with the officer placed at OFFICER_TRANSFORM
(identity), the coupled world is just
    R_delta = seat_animated_world · inverse(seat_rest_world)
R_delta already encodes the seat's world pivot (rest world contains the seat's
world translation), so a point riding the seat at rest position p moves to
R_delta · p; do NOT conjugate by the pivot again. At rest R_delta = I ->
identity -> byte-identical to placement.

See docs/superpowers/specs/2026-06-19-bridge-node-animation-design.md.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


def identity4():
    return [1.0, 0, 0, 0,  0, 1.0, 0, 0,  0, 0, 1.0, 0,  0, 0, 0, 1.0]


def mat_mul(a, b):
    """Row-major 4x4 multiply (a · b)."""
    out = [0.0] * 16
    for r in range(4):
        for c in range(4):
            out[r * 4 + c] = sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
    return out


def mat_inverse_rigid(m):
    """Inverse of a rigid (rotation R + translation t) row-major 4x4:
    [Rᵀ | -Rᵀ t]. Sufficient: seat transforms are rotation+translation."""
    r00, r01, r02 = m[0], m[1], m[2]
    r10, r11, r12 = m[4], m[5], m[6]
    r20, r21, r22 = m[8], m[9], m[10]
    tx, ty, tz = m[3], m[7], m[11]
    # transpose rotation
    inv = [r00, r10, r20, 0,
           r01, r11, r21, 0,
           r02, r12, r22, 0,
           0,   0,   0,   1.0]
    # -Rᵀ t
    inv[3]  = -(inv[0] * tx + inv[1] * ty + inv[2] * tz)
    inv[7]  = -(inv[4] * tx + inv[5] * ty + inv[6] * tz)
    inv[11] = -(inv[8] * tx + inv[9] * ty + inv[10] * tz)
    return inv


class BridgeNodeAnimController:
    def __init__(self, bridge_iid_getter=None, asset_resolver=None):
        self._bridge_iid_getter = bridge_iid_getter or (lambda: None)
        self._resolve = asset_resolver or (lambda p: p)
        # officer_iid -> dict(officer, seat_node)
        self._coupled = {}

    def _bridge_iid(self):
        try:
            return self._bridge_iid_getter()
        except Exception:
            return None

    @staticmethod
    def _discover_seat_node(renderer, path):
        """The chair clip animates one bridge node ('console seat NN') plus the
        non-bridge 'Camera captain' track. Return the seat node name by the BC
        naming convention, or None."""
        fn = getattr(renderer, "load_animation_clips", None)
        if fn is None:
            return None
        try:
            clips = fn(path)
        except Exception:
            return None
        if not clips:
            return None
        for tr in clips[0].get("tracks", []):
            # Native load_animation_clips emits the track's node under "node";
            # the fakes historically used "target_node_name"/"name". Accept all.
            name = (tr.get("node") or tr.get("target_node_name")
                    or tr.get("name") or "")
            if name.lower().startswith("console seat"):
                return name
        return None

    def turn_chair(self, officer, chair_clip, *, renderer):
        bridge = self._bridge_iid()
        if bridge is None or chair_clip is None:
            return
        path = self._resolve(chair_clip["clip_nif"])
        seat_node = chair_clip.get("seat_node") or \
            self._discover_seat_node(renderer, path)
        try:
            renderer.play_instance_node_clip(bridge, path, False, False)
        except Exception:
            _logger.debug("turn_chair play failed", exc_info=True)
            return
        iid = getattr(officer, "_render_instance", None)
        if iid is not None and seat_node:
            self._coupled[iid] = {"officer": officer, "seat_node": seat_node}

    def unturn_chair(self, officer, chair_clip, *, renderer):
        bridge = self._bridge_iid()
        if bridge is not None and chair_clip is not None:
            try:
                renderer.play_instance_node_clip(
                    bridge, self._resolve(chair_clip["clip_nif"]), False, True)
            except Exception:
                _logger.debug("unturn_chair play failed", exc_info=True)
        # Coupling continues to track the reversing seat until reset/settle;
        # simplest correct behavior is to keep the officer coupled while the
        # reverse plays (the seat returns to rest -> R_delta -> I -> identity).

    def update(self, renderer):
        for iid, rec in list(self._coupled.items()):
            bridge = self._bridge_iid()
            if bridge is None:
                continue
            try:
                anim = renderer.instance_node_world(bridge, rec["seat_node"], True)
                rest = renderer.instance_node_world(bridge, rec["seat_node"], False)
            except Exception:
                continue
            if anim is None or rest is None:
                continue
            # R_delta already encodes the seat's world pivot (rest world holds
            # the seat translation); applying it directly rides the officer on
            # the seat. Conjugating by the pivot again would rotate about 2·pivot.
            coupling = mat_mul(list(anim), mat_inverse_rigid(list(rest)))
            try:
                renderer.set_world_transform(iid, coupling)
            except Exception:
                _logger.debug("coupling set_world_transform failed", exc_info=True)

    def reset(self, *, renderer=None):
        bridge = self._bridge_iid()
        if renderer is not None and bridge is not None:
            try:
                renderer.stop_instance_node_anim(bridge)
            except Exception:
                pass
        self._coupled.clear()
