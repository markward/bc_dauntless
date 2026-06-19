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
import math
import os

_logger = logging.getLogger(__name__)

# Opt-in coupling diagnostic: set BRIDGE_COUPLING_DEBUG=1 to append a per-turn /
# per-tick trace to /tmp/bridge_coupling.log. Off by default (no production
# impact). Used to root-cause "seat rotates but officer doesn't ride it".
_DEBUG = bool(os.environ.get("BRIDGE_COUPLING_DEBUG"))
_DEBUG_PATH = "/tmp/bridge_coupling.log"
_dbg_ticks: dict = {}   # iid -> ticks already logged (cap volume)


def _dbg(msg: str) -> None:
    if not _DEBUG:
        return
    try:
        with open(_DEBUG_PATH, "a") as fh:
            fh.write(msg + "\n")
    except Exception:
        pass


def _iid_str(iid) -> str:
    """index:generation of an InstanceId, for spotting instance-identity drift."""
    if iid is None:
        return "None"
    return f"{getattr(iid, 'index', '?')}:{getattr(iid, 'generation', '?')}"


def _mat_summary(m) -> str:
    """Compact description of a row-major 4x4: column scales (1.0 = no scale),
    rotation angle from the trace, and translation."""
    if m is None:
        return "None"
    cols = [(m[0], m[4], m[8]), (m[1], m[5], m[9]), (m[2], m[6], m[10])]
    scales = [round(math.sqrt(sum(c * c for c in col)), 4) for col in cols]
    trace = m[0] + m[5] + m[10]
    cos_a = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    angle = round(math.degrees(math.acos(cos_a)), 2)
    trans = [round(m[3], 2), round(m[7], 2), round(m[11], 2)]
    return f"scale={scales} angle={angle}deg trans={trans}"


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
            _dbg_ticks[id(iid)] = 0
        _dbg(f"[turn_chair] PLAY bridge={_iid_str(bridge)} "
             f"officer_iid={_iid_str(iid)} seat_node={seat_node!r} "
             f"path={path!r} coupled={iid in self._coupled}")

    def unturn_chair(self, officer, chair_clip, *, renderer):
        bridge = self._bridge_iid()
        if bridge is not None and chair_clip is not None:
            try:
                # chair_clip here is the BackCaptain action, which the SDK
                # builds from the DEDICATED reverse NIF (e.g.
                # db_chair_H_face_capt_reverse, authored turned->rest). BC plays
                # it FORWARD. Passing reverse=True double-reverses it: the first
                # sampled frame is the clip's END (rest), so the seat snaps to
                # rest instantly ("click back"). Play it forward (reverse=False).
                renderer.play_instance_node_clip(
                    bridge, self._resolve(chair_clip["clip_nif"]), False, False)
            except Exception:
                _logger.debug("unturn_chair play failed", exc_info=True)
        # Coupling continues to track the reversing seat until reset/settle;
        # the officer rides the chair back as the reverse clip plays
        # (turned -> rest -> R_delta -> I -> placement).

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
            if _DEBUG:
                n = _dbg_ticks.get(id(iid), 0)
                _dbg_ticks[id(iid)] = n + 1
                # Log ticks 0-3 then every 6th up to ~40 (covers the full ~0.53s
                # turn at 60fps so we see whether anim EVER leaves rest).
                if n < 4 or (n % 6 == 0 and n <= 42):
                    a_ang = _mat_summary(list(anim)).split("angle=")[1].split()[0]
                    r_ang = _mat_summary(list(rest)).split("angle=")[1].split()[0]
                    d_ang = _mat_summary(coupling).split("angle=")[1].split()[0]
                    _dbg(f"[update] t#{n} READ bridge={_iid_str(self._bridge_iid())} "
                         f"seat={rec['seat_node']!r} anim_ang={a_ang} "
                         f"rest_ang={r_ang} Rdelta_ang={d_ang}")

    def reset(self, *, renderer=None):
        bridge = self._bridge_iid()
        if renderer is not None and bridge is not None:
            try:
                renderer.stop_instance_node_anim(bridge)
            except Exception:
                pass
        self._coupled.clear()
