"""A registered ship must be a REAL QuickBattle ship, not just a menu row.

This enters above the tables deliberately: it builds QuickBattle's panes
and asserts the ship is present as a button. Asserting only that the tables
gained a row would pass while the ship remained unspawnable -- "listed but
won't spawn" is the failure this whole design exists to avoid, and entering
one layer lower would not catch it.

The SDK's own BuildDialog() dereferences g_pXO (set by QuickBattle.Initialize
via AssignGlobalPointers), so this drives the same real cascade
tests/host/test_quickbattle_boot.py uses -- controller.loader.load_quickbattle()
-- before calling BuildDialog() a second time to rebuild the ships pane with
the mod ship already registered. The native _dauntless_host extension is
required (the SDK Appc shim imports it at module-load time); skip cleanly
when it is not built.
"""

import pytest

pytest.importorskip("_dauntless_host")

from engine import foundation, mods
from engine.foundation import quickbattle
from tests.helpers.bc_assets import require_game_dir


class _FakeRenderer:
    """Minimal renderer surface the realization walk + reconciliation touch.

    Mirrors tests/host/test_quickbattle_boot.py::_FakeRenderer -- the cascade
    is only driven here to get a live g_pXO, never to check render state.
    """

    def __init__(self):
        self._next = 1
        self.live = set()

    def load_model(self, path, search):
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    def create_instance(self, h):
        iid = self._next
        self._next += 1
        self.live.add(iid)
        return iid

    def destroy_instance(self, iid):
        self.live.discard(iid)

    def set_world_transform(self, iid, m):
        pass

    def set_rim_eligible(self, iid, b):
        pass

    def set_rim_strength(self, iid, s):
        pass


def _touch(p, body=""):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)
    yield
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)


def test_a_foundation_ship_appears_in_the_quickbattle_panes(tmp_path, monkeypatch):
    require_game_dir("data/Models/Ships")

    _touch(tmp_path / "M" / "scripts" / "Custom" / "Ships" / "s.py",
           "import Foundation\n"
           "Foundation.ShipDef.ZZTest = Foundation.FedShipDef(\n"
           "    'ZZTest', 1, {'name': 'ZZ Test Ship', 'shipFile': 'ZZTest'})\n"
           "Foundation.ShipDef.ZZTest.RegisterQBShipMenu('Fed Ships')\n")

    # The SDK finder must be installed (Custom/Ships does `import Foundation`
    # and other SDK imports) before load_plugins() runs -- the same ordering
    # engine/host_loop.py's boot sequence follows.
    from tools import mission_harness
    mission_harness.setup_sdk()

    mods.configure(mods.build_index(tmp_path))
    report = foundation.load_plugins()
    assert report.failures == [], report.failures

    import importlib
    qb = importlib.import_module("QuickBattle.QuickBattle")

    # The tables must know it...
    assert "ZZ Test Ship" in qb.g_dShipNameToType
    sid = qb.g_dShipNameToType["ZZ Test Ship"]
    assert sid in qb.g_dFriendlyShipTypeToDetails

    # ...and the built panes must show it. BuildDialog() dereferences g_pXO,
    # which only exists once the real QuickBattle cascade has run -- drive it
    # the same way tests/host/test_quickbattle_boot.py does, then rebuild the
    # dialog so GenerateShipMenu() runs again with the mod ship already
    # sitting in the tables.
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    controller = hl.HostController()
    controller.renderer = _FakeRenderer()
    controller.loader = hl._MissionLoader(controller, verbose=False)
    controller.loader.load_quickbattle()

    qb.BuildDialog()
    labels = _all_button_labels(qb.g_pShipsPane)
    assert "ZZ Test Ship" in labels, (
        "the ship registered into the tables but never reached the picker; "
        "found: %r" % (labels,))


def _all_button_labels(pane):
    """Every button label under a ship pane, at any depth.

    Reads `_children` directly rather than calling `GetChildren()`, for the
    same reason engine/ui/quick_battle_setup_panel.py's `_child_widgets`
    does: GetChildren() is not implemented uniformly. TGPane/STSubPane store
    (child, x, y) 3-tuples and inherit a real GetChildren(); STMenu (and its
    STCharacterMenu subclass -- the ship-category widget GenerateShipMenu
    builds) stores bare widgets in `_children` but never defines
    GetChildren() at all, so TGObject.__getattr__ vends a truthy _Stub in
    its place -- calling it silently returns an empty-looking non-iterator,
    not an AttributeError, so the walk would falsely report every category
    empty (stock ships included) rather than crash where the bug would be
    obvious.
    """
    from engine.appc.characters import STButton
    out = []
    stack = [pane]
    while stack:
        w = stack.pop()
        for child in w.__dict__.get("_children") or []:
            if isinstance(child, tuple):
                child = child[0]
            if isinstance(child, STButton):
                out.append(child.GetLabel())
            stack.append(child)
    return out
