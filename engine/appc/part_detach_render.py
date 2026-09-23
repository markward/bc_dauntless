"""The visual half of appendage severance: hide the part, fly it away.

`part_severance` decides WHEN a part comes off; this makes it visible. Split
out so the decision stays testable headlessly — every function here is a no-op
without a renderer, and `part_severance.sever` calls it best-effort.

HOW THE CHUNK IS DRAWN. A severed wing is a second INSTANCE OF THE SAME MODEL
with every part hidden except that one, while the ship hides only that part.
Both ends use `set_instance_node_hidden`, which writes the zero matrix as a
node's local transform and collapses its subtree to a point.

That is deliberately cheap: no mesh is split, no geometry is generated, and the
two instances share one model (models are cached by handle, so the chunk costs
a transform and a draw, not a copy of the hull).

⚠️ The cut is CLEAN — the wing separates exactly along its node boundary, with
no torn edge. Voxel chunks get a ragged face for free because the carve field
clips them; a node-part sheared at an authored boundary has no such field. If
that reads wrong at close range, carving the stump is the follow-up; it was not
done here because the parting is usually seen in motion and at speed.
"""

from __future__ import annotations

import engine.dev_mode as dev_mode
from engine import host_io
from engine.appc import articulation


def detach(ship, iid, part_name) -> bool:
    """Hide `part_name` on `ship`'s instance `iid` and spawn it as debris.

    `iid` is PASSED IN, never looked up from a module global — the same shape
    `hull_breakup.after_carve` uses, and for the same reason: the session lives
    in host_loop and appc modules must not reach into it.

    Returns True when the ship's own instance was updated — the visible half
    that matters. Chunk spawning is best-effort on top of that: a wing that
    vanishes is wrong, but a wing that vanishes AND takes an exception through
    combat is worse.
    """
    if iid is None:
        return False
    if not host_io.set_instance_node_hidden(iid, part_name, True):
        return False
    try:
        _spawn_chunk(ship, iid, part_name)
    except Exception as _e:  # noqa: BLE001
        dev_mode.log_swallowed("severed part chunk spawn", _e)
    return True


def _spawn_chunk(ship, ship_iid, part_name) -> None:
    """Create a debris instance showing ONLY `part_name` and hand it to the
    debris system, which integrates its drift and tumble each frame.

    Mass is the part's share of the hull, by AABB volume — `debris_chunk.spawn`
    only ever uses its cell counts as a RATIO, so a volume fraction substitutes
    for them exactly.
    """
    from engine import renderer
    from engine.appc import debris_chunk

    leaf = articulation.leaf_for(ship)
    boxes = articulation.part_boxes_for(leaf)
    box = boxes.get(part_name)
    if box is None:
        return

    model = host_io.instance_model(ship_iid)
    if not model:
        return
    chunk_iid = renderer.create_instance(model)
    if chunk_iid is None:
        return
    # Show ONE part: hide every other authored part on the copy.
    for name in boxes:
        if name != part_name:
            host_io.set_instance_node_hidden(chunk_iid, name, True)

    (lo, hi) = box
    centre = tuple((lo[i] + hi[i]) * 0.5 for i in range(3))
    half = tuple((hi[i] - lo[i]) * 0.5 for i in range(3))
    radius = max(half) or 0.01

    vol = max(1e-9, 8.0 * half[0] * half[1] * half[2])
    total = 0.0
    for b in boxes.values():
        (blo, bhi) = b
        total += ((bhi[0] - blo[0]) * (bhi[1] - blo[1]) * (bhi[2] - blo[2]))
    frac = vol / total if total > 0.0 else 0.1

    try:
        parent_mass = float(ship.GetMass())
    except Exception:  # noqa: BLE001
        parent_mass = 1.0

    # `cells` / `parent_occupied_cells` are used by spawn() only as a ratio, so
    # a volume fraction expressed against a nominal 1000 reproduces the mass
    # split without inventing a voxel count the part does not have.
    debris_chunk.spawn(chunk_iid, ship, int(max(1.0, frac * 1000.0)),
                       centre, radius, parent_mass, 1000)


def reattach(ship, iid, part_name) -> bool:
    """Restore a hidden part. For the dev/mission-reset path only — severance
    itself is permanent."""
    if iid is None:
        return False
    return host_io.set_instance_node_hidden(iid, part_name, False)
