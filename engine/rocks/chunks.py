"""Host side of rock breakup: chunk specs -> rendered tumbling bodies.

A chunk is a debris_chunk body (collides, capped at kMaxLiveChunks, cleared
on mission swap by debris_chunk.clear) wearing a catalogue fragment.
Sub-project 3 replaces these with minors.

SIZE. Every ship-like instance draws at BC_MODEL_SCALE (0.01 GU per model
unit) x its scale, and the glTF loader writes metres x 1/1.75 x load_scale
model units. A fragment loaded at load_scale 1 has a bound radius of
bound_radius_m / 1.75 model units, so a chunk body with
    scale = r / (bound_radius_m / 1.75 x 0.01) = r x 175 / bound_radius_m
draws at r GU. The size lives in the body's scale, not the load scale, so
every chunk wearing one fragment shares ONE model load; r is still quantised
(stats.quantise_radius, 2 s.f.) so a chunk's collision radius matches the
sizes the rest of the rock code uses.
"""
from collections import defaultdict

import engine.dev_mode as dev_mode
from engine.appc.math import TGMatrix3, TGPoint3

kChunkLoadScale = 1.0


def body_scale(radius_gu: float, rock) -> float:
    """The debris_chunk scale that draws `rock`'s fragment (loaded at
    kChunkLoadScale) at `radius_gu` GU."""
    from engine.host_loop import BC_MODEL_SCALE
    from engine.rocks.catalogue import MODEL_UNITS_PER_METRE
    return float(radius_gu) / (rock.bound_radius_m * MODEL_UNITS_PER_METRE
                               * kChunkLoadScale * BC_MODEL_SCALE)


def _spawn(renderer, spec):
    from engine.appc import debris_chunk
    from engine.rocks import catalogue, stats
    rock = (catalogue.pick(spec.seed, kind="fragment", family=spec.family)
            or catalogue.pick(spec.seed, kind="fragment", family="silicate"))
    if rock is None:
        return None
    # lod_paths entries are already full paths (catalogue.load). Chunks are
    # small on screen: the lowest LOD.
    handle = renderer.load_model(str(rock.lod_paths[-1]), [], None,
                                 decals=None, scale=kChunkLoadScale)
    iid = renderer.create_instance(handle)
    renderer.set_surface_rock(iid, True)
    r_q = stats.quantise_radius(spec.radius_gu)
    R = TGMatrix3()
    R.MakeIdentity()
    return debris_chunk.spawn_body(
        iid, loc=TGPoint3(*spec.loc), rot=R, vel=TGPoint3(*spec.vel),
        angular=TGPoint3(*spec.angular), mass=spec.mass, radius=r_q,
        scale=body_scale(r_q, rock), pSet=spec.pSet)


def pump(renderer, session) -> None:
    from engine.appc import debris_chunk
    from engine.rocks import breakup, death
    groups = defaultdict(list)
    for spec in death.drain_chunk_specs():
        try:
            chunk = _spawn(renderer, spec)
        except Exception as e:
            dev_mode.log_swallowed("spawn rock chunk", e)
            continue
        if chunk is None:
            continue
        debris_chunk.push_transform(chunk, renderer)
        if spec.ghost_ids:
            groups[spec.ghost_ids].append(chunk)
    # One breakup's chunks share its ghost_ids (the parent's ObjID is unique).
    for ghost_ids, members in groups.items():
        debris_chunk.ghost(members, ghost_ids, breakup.kPieceGhostTime)
