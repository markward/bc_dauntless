"""Physical parents: the single answer to "which mesh part is this authored
property on".

A property may carry an explicit `SetPhysicalParent(name)`. When it does and
the model has that part, that wins; otherwise the geometric rule
(`part_severance.part_for_mount`) answers. Spec section 5.

`part_severance` and `articulation` are imported lazily inside functions so
`part_severance` can import this module without a cycle.

The preview overlay lets the Ship Property Viewer show an unsaved choice
live: `(leaf, property name) -> name | None` (None means Auto).
"""
import sys
from typing import NamedTuple, Optional


class PropRef(NamedTuple):
    """A name plus baked physical parent, where no property object is in hand."""
    name: str
    baked: Optional[str]

    def GetName(self):
        return self.name

    def GetPhysicalParent(self):
        return self.baked


_preview = {}      # leaf -> {property name: part name | None}
_warned = set()    # (leaf, part name)


def property_of(obj):
    getter = getattr(obj, "GetProperty", None)
    if getter is not None:
        prop = getter()
        if prop is not None:
            return prop
    return obj


def explicit_parent(leaf, prop):
    leaf = str(leaf).lower()
    overlay = _preview.get(leaf)
    if overlay is not None and prop.GetName() in overlay:
        return overlay[prop.GetName()]
    return prop.GetPhysicalParent()


def _parts(leaf):
    from engine.appc import articulation
    return articulation.part_boxes_for(str(leaf).lower())


def is_missing(leaf, name):
    parts = _parts(leaf)
    return bool(parts) and name not in parts


def part_for_property(leaf, prop, point, iid=None):
    from engine.appc import part_severance
    leaf = str(leaf).lower()
    name = explicit_parent(leaf, prop)
    if name is not None:
        if not is_missing(leaf, name):
            return name
        key = (leaf, name)
        if key not in _warned:
            _warned.add(key)
            sys.stderr.write(
                "[physical-parents] %s: property %r names missing part %r; "
                "using Auto\n" % (leaf, prop.GetName(), name))
    return part_severance.part_for_mount(leaf, point, iid)


def source_for(leaf, prop):
    name = explicit_parent(leaf, prop)
    if name is None:
        return "auto"
    return "missing" if is_missing(leaf, name) else "set"


def set_preview(leaf, overrides):
    _preview[str(leaf).lower()] = dict(overrides)


def clear_preview(leaf=None):
    if leaf is None:
        _preview.clear()
    else:
        _preview.pop(str(leaf).lower(), None)


def reset():
    _preview.clear()
    _warned.clear()
