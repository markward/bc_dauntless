"""Owner tags: which engine module made a world object, read through __dict__.

engine/systems/owners.py is the registry a module uses to say "this object is
mine, under this key", so a later rebuild can hand it back to its maker.
"""
import App
from engine.core.ids import TGObject, _Stub
from engine.systems import owners


class _TestOwner:
    def __init__(self, name):
        self.name = name

    def rebuild(self, old, record):
        return None

    def after_rebuild(self, new, record):
        pass


def test_tag_and_owner_of():
    owner = _TestOwner("test_owner_tag")
    owners.register(owner)
    obj = App.ShipClass_Create("X")
    owners.tag(obj, "test_owner_tag", 7)
    assert owners.owner_of(obj) == (owner, 7)
    assert owners.get("test_owner_tag") is owner


def test_registering_a_name_again_replaces_it():
    first = _TestOwner("test_owner_replace")
    second = _TestOwner("test_owner_replace")
    owners.register(first)
    owners.register(second)
    assert owners.get("test_owner_replace") is second


def test_untagged_and_unregistered_are_none():
    assert owners.owner_of(App.ShipClass_Create("Untagged")) is None
    obj = App.ShipClass_Create("Orphan")
    owners.tag(obj, "test_owner_never_registered", 1)
    assert owners.owner_of(obj) is None
    assert owners.get("test_owner_never_registered") is None


class _StubEverything(TGObject):
    """A TGObject whose __getattr__ answers EVERY name with a stub,
    underscore names included -- the worst case for a getattr read."""

    def __getattr__(self, name):
        return _Stub(name, type(self).__name__)


def test_a_stub_attribute_never_reads_as_owned():
    obj = _StubEverything()
    assert getattr(obj, "_dauntless_owner") is not None
    assert owners.owner_of(obj) is None


def test_restores_after_battle_only_when_the_owner_says_true():
    """An owner opts out of the battle restore's snapshot only with
    `restores_after_battle = True`; absent, or any other value, reads False."""
    obj = App.ShipClass_Create("Restorer")
    assert owners.restores_after_battle(obj) is False       # untagged
    owner = _TestOwner("test_owner_restores")
    owners.register(owner)
    try:
        owners.tag(obj, "test_owner_restores", 1)
        assert owners.restores_after_battle(obj) is False   # no attribute
        for value in (1, "yes", False, None):
            owner.restores_after_battle = value
            assert owners.restores_after_battle(obj) is False, value
        owner.restores_after_battle = True
        assert owners.restores_after_battle(obj) is True
    finally:
        owners._owners.pop("test_owner_restores", None)
