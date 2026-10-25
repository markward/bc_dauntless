"""Owner tags: which engine module made a world object, and under what key.

A module that places objects of its own into BC's world (home stations today)
registers an `Owner` here and tags each object it builds with
`(owner name, key)`. Anything that later has to rebuild the world -- a battle
restore -- asks `owner_of(obj)` and hands the object back to its maker instead
of guessing how it was made.

The tag lives in the object's `__dict__` and is only ever read from there:
`TGObject.__getattr__` answers unknown names with a truthy stub, so a getattr
read could make an untagged object look owned.
"""
from __future__ import annotations

from typing import Protocol

_TAG_ATTR = "_dauntless_owner"

_owners: dict = {}


class Owner(Protocol):
    name: str

    def rebuild(self, old, record) -> object | None:
        """Build a replacement for `old` from `record`; the new object, or
        None when there is nothing to build."""

    def after_rebuild(self, new, record) -> None:
        """Called once `new` has replaced the old object."""


def register(owner) -> None:
    """Register `owner` under `owner.name`; the same name again replaces the
    entry, so a module reload is safe."""
    _owners[owner.name] = owner


def get(name: str):
    return _owners.get(name)


def tag(obj, owner_name: str, key) -> None:
    """The only writer of the tag."""
    obj.__dict__[_TAG_ATTR] = (owner_name, key)


def owner_of(obj):
    """`(owner, key)` for a tagged object whose owner is registered, else None."""
    tagged = obj.__dict__.get(_TAG_ATTR)
    if tagged is None:
        return None
    owner_name, key = tagged
    owner = _owners.get(owner_name)
    if owner is None:
        return None
    return owner, key
