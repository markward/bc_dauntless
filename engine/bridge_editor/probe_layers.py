"""Probe-layer planner (spec 2026-10-17-bridge-reflection-layers §2, §4.4).
Pure.

Animated materials whose wave is identical in a state share ONE reflection
layer for that state: the probe captures them at their peak, and the layer's
live value v = w(t)^2.2 scales the capture at draw time. Layers are capped
per state by bridge quality; waves past the cap are dropped (and warned),
keeping authored order."""
import hashlib
from dataclasses import dataclass, field

from engine.bridge_editor import behaviour as bh

LAYER_CAP = {0: 2, 1: 4, 2: 8}


def layer_cap(quality: int) -> int:
    return LAYER_CAP[min(max(int(quality), 0), 2)]


def _key_of(anim):
    sine = anim["shape"] == "sine"
    return (anim["shape"], float(anim["period_s"]), float(anim.get("phase", 0.0)),
            float(anim.get("min", 0.0)),
            0.0 if sine else float(anim.get("duty", 0.5)),
            0.0 if sine else float(anim.get("soft", 0.0)))


def wave_key(material, state):
    """The whole wave scoped to `state` (sorted tuple of every animation), or
    None when nothing animates there."""
    keys = [_key_of(m) for m in material.get("modifiers", ())
            if m["type"] == "animation" and state in m["scope"]]
    return tuple(sorted(keys)) if keys else None


@dataclass(frozen=True)
class Layer:
    state: str
    key: tuple
    materials: tuple


@dataclass
class ProbePlan:
    layers: list
    warnings: list
    _of: dict = field(default_factory=dict, repr=False)
    _animated: set = field(default_factory=set, repr=False)

    def layer_of(self, material, state) -> int:
        return self._of.get((material, state), -1)

    def animated(self, material, state) -> bool:
        return (material, state) in self._animated


EMPTY = ProbePlan([], [])


def _contributes(name, material, state, resolved, light_materials, mapped):
    if any(any(bh.output(material, state, 0.0, mesh in mapped, waves=False)[0])
           for mesh, mat in resolved.items() if mat == name):
        return True
    return name in light_materials and any(
        bh.output(material, state, 0.0, False, for_light=True, waves=False)[0])


def plan(doc, resolved, light_materials, mapped, cap) -> ProbePlan:
    used = set(resolved.values())
    out = ProbePlan([], [])
    for state in sorted(bh.STATES, key=bh.state_index):
        groups = {}                       # key -> [material], doc order
        for name, material in doc["materials"].items():
            if name not in used:
                continue
            key = wave_key(material, state)
            if key is None:
                continue
            out._animated.add((name, state))
            if _contributes(name, material, state, resolved, light_materials, mapped):
                groups.setdefault(key, []).append(name)
        for n, (key, names) in enumerate(groups.items()):
            if n < cap:
                for name in names:
                    out._of[(name, state)] = len(out.layers)
                out.layers.append(Layer(state, key, tuple(names)))
            else:
                out.warnings.append(
                    "bridge reflections: %s wave on %s dropped past the layer cap of %d"
                    % (state, ", ".join(names), cap))
    return out


def layer_identity(layer) -> int:
    """A layer's identity for the renderer (spec §4.4): a stable unsigned
    64-bit hash of its state and wave key -- never its members or index, and
    never Python's salted hash(). BridgePass invalidates a layer's slot when
    the identity at its index changes, so a re-plan never shows another
    layer's capture."""
    digest = hashlib.blake2b(repr((layer.state, layer.key)).encode("utf-8"),
                             digest_size=8).digest()
    return int.from_bytes(digest, "little")


def layer_values(plan, t) -> list:
    vals = []
    for layer in plan.layers:
        w = 1.0
        for shape, period, phase, lo, duty, soft in layer.key:
            w *= bh.wave_factor({"shape": shape, "period_s": period, "phase": phase,
                                 "min": lo, "duty": duty, "soft": soft}, t)
        vals.append(w ** 2.2)
    return vals
