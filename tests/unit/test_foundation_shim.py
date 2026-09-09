"""`import Foundation` must reach OURS, never a mod's.

_SDKFinder checks PROJECT_ROOT before the mod index -- an ordering the mod
overlay chose deliberately, because project-root shims are our own
replacements and must not be overridable. A mod pack bundling Foundation's
real Foundation.py would otherwise win, and that file is Python 1.5 and
monkeypatches QuickBattle.py and loadspacehelper.py, both of which we have
reimplemented.
"""

import pytest

from engine import mods


def _touch(p, body=""):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


@pytest.fixture(autouse=True)
def _clean():
    mods.configure(None)
    yield
    mods.configure(None)


def test_import_foundation_reaches_the_engine_module():
    import Foundation
    from engine import foundation
    assert Foundation.FedShipDef is not None
    assert Foundation.ShipDef is foundation.ShipDef
    assert Foundation.shipList is foundation.shipList


def test_a_mod_supplied_foundation_does_not_win(tmp_path):
    _touch(tmp_path / "M" / "scripts" / "Foundation.py",
           "MARKER = 'from the mod'\n")
    mods.configure(mods.build_index(tmp_path))

    import importlib
    import sys
    sys.modules.pop("Foundation", None)
    try:
        m = importlib.import_module("Foundation")
        assert not hasattr(m, "MARKER"), (
            "a mod-supplied Foundation.py shadowed ours")
    finally:
        sys.modules.pop("Foundation", None)
