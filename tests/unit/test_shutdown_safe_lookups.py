"""Lookups called from Condition.__del__ must survive interpreter shutdown.

SDK Condition objects (ConditionSingleShieldBelow, ConditionSystemBelow,
others) call back into the engine from their ``__del__`` methods to remove
watchers. If those engine functions perform runtime imports, they raise
``ImportError: sys.meta_path is None`` once Python starts tearing down the
import system, producing pages of noise at process exit.

We model the shutdown state by poisoning ``sys.modules`` so any subsequent
``import`` statement raises ``ImportError`` — same failure mode as a real
shutdown. The lookups must degrade to safe defaults instead of raising.
"""
import sys

import pytest

from engine.appc.sets import _NullSet
from engine.appc.objects import ObjectGroup


@pytest.fixture
def app_import_poisoned():
    saved = sys.modules.get("App")
    sys.modules["App"] = None  # any subsequent `import App` now raises ImportError
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop("App", None)
        else:
            sys.modules["App"] = saved


@pytest.fixture
def sets_import_poisoned():
    saved = sys.modules.get("engine.appc.sets")
    sys.modules["engine.appc.sets"] = None
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop("engine.appc.sets", None)
        else:
            sys.modules["engine.appc.sets"] = saved


def test_nullset_getobject_safe_at_shutdown(app_import_poisoned, sets_import_poisoned):
    ns = _NullSet()
    assert ns.GetObject("does_not_exist") is None


def test_objectgroup_getactiveobjecttuple_safe_at_shutdown(app_import_poisoned):
    g = ObjectGroup()
    g.AddName("does_not_exist")
    assert g.GetActiveObjectTuple() == ()
