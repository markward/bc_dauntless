"""Attach queue for Dauntless-created hardpoint templates (spec 2026-10-22 4.1).

BC's LoadPropertySet adds only the template names it lists, so a template a
Dauntless hardpoint block creates would never reach a ship's property set.
Such blocks call App.DauntlessAttachTemplate(prop); the SDK-module hook drains
the queue after the hardpoint module executes and wraps its LoadPropertySet so
each queued prop is added to "Scene Root" afterwards. Templates registered
without queueing (e.g. the Kessok Strobe) stay unattached, as in BC.
"""

_queue: list = []


def queue(prop) -> None:
    _queue.append(prop)


def drain() -> list:
    global _queue
    out, _queue = _queue, []
    return out


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
