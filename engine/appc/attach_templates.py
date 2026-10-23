"""Attach queue for Dauntless-created hardpoint templates (spec 2026-10-22 4.1).

BC's LoadPropertySet adds only the template names it lists, so a template a
Dauntless hardpoint block creates would never reach a ship's property set.
Such blocks call App.DauntlessAttachTemplate(prop); the SDK-module hook drains
the queue after the hardpoint module executes and wraps its LoadPropertySet so
each queued prop is added to "Scene Root" afterwards. Templates registered
without queueing (e.g. the Kessok Strobe) stay unattached, as in BC.

The hook also `record`s which names it attached per hardpoint leaf: the Ship
Property Viewer may rename a light on a stock ship only when Dauntless created
it (an attached name); every other stock light is the game's own template.
"""

_queue: list = []
# leaf -> names queued by that leaf's last hardpoint-module exec.
_attached: dict = {}


def queue(prop) -> None:
    _queue.append(prop)


def drain() -> list:
    global _queue
    out, _queue = _queue, []
    return out


def record(leaf, props) -> None:
    """Remember the names of `props`, the templates `leaf`'s hardpoint module
    just queued. Replaces the leaf's previous record (every CreateShip
    re-executes the module)."""
    _attached[leaf] = {p.GetName() for p in props}


def attached_names(leaf) -> set:
    """The template names `leaf`'s last hardpoint exec attached (a copy)."""
    return set(_attached.get(leaf, ()))


def wrap_load_property_set(module, props) -> None:
    original = module.LoadPropertySet
    props = list(props)

    def LoadPropertySet(pObj):
        result = original(pObj)
        present = [p for p in pObj.GetPropertyList()]
        for prop in props:
            if not any(p is prop for p in present):
                pObj.AddToSet("Scene Root", prop)
                present.append(prop)
        return result

    module.LoadPropertySet = LoadPropertySet
