"""Mods screen orchestration: which mode, what each outcome does, and that a
broken screen never stops boot."""
import pytest

from engine import ship_catalog
from engine.ui import mods_screen


class _Rec:
    def __init__(self, ship_id):
        self.ship_id = ship_id
        self.errors = ()
        self.missing = ("era",)


@pytest.fixture(autouse=True)
def _clean():
    ship_catalog.reset_session()
    yield
    ship_catalog.reset_session()


def test_decide_mode(monkeypatch):
    monkeypatch.setattr(mods_screen.ship_catalog, "incomplete_ships", lambda: [_Rec("A")])
    assert mods_screen.decide_mode([]) == "gate"
    monkeypatch.setattr(mods_screen.ship_catalog, "incomplete_ships", lambda: [])
    assert mods_screen.decide_mode(["--mods"]) == "home"
    assert mods_screen.decide_mode([]) is None


def _panel_outcome(outcome):
    def run(panel):
        panel._outcome = outcome
    return run


def test_no_screen_boots(monkeypatch):
    monkeypatch.setattr(mods_screen, "decide_mode", lambda argv=None: None)
    assert mods_screen.run_mods_screen(lambda p: pytest.fail("no screen")) == "boot"


def test_skip_hides_the_incomplete_ships(monkeypatch):
    monkeypatch.setattr(mods_screen, "decide_mode", lambda argv=None: "gate")
    monkeypatch.setattr(mods_screen, "_build_panel", lambda mode, error="": _FakePanel())
    monkeypatch.setattr(mods_screen.ship_catalog, "incomplete_ships", lambda: [_Rec("A"), _Rec("B")])
    assert mods_screen.run_mods_screen(_panel_outcome("skip")) == "boot"
    assert ship_catalog.skipped() == frozenset({"a", "b"})


def test_quit_and_closed_window_quit(monkeypatch):
    monkeypatch.setattr(mods_screen, "decide_mode", lambda argv=None: "home")
    monkeypatch.setattr(mods_screen, "_build_panel", lambda mode, error="": _FakePanel())
    assert mods_screen.run_mods_screen(_panel_outcome("quit")) == "quit"
    assert mods_screen.run_mods_screen(_panel_outcome(None)) == "quit"


def test_continue_reshows_once_then_skips(monkeypatch):
    shown = []
    monkeypatch.setattr(mods_screen, "decide_mode", lambda argv=None: "gate")
    monkeypatch.setattr(mods_screen, "_build_panel",
                        lambda mode, error="": shown.append(error) or _FakePanel())
    monkeypatch.setattr(mods_screen.ship_catalog, "incomplete_ships", lambda: [_Rec("A")])
    assert mods_screen.run_mods_screen(_panel_outcome("continue")) == "boot"
    assert len(shown) == 2 and shown[1]
    assert ship_catalog.skipped() == frozenset({"a"})


def test_a_broken_screen_boots(monkeypatch):
    monkeypatch.setattr(mods_screen, "decide_mode", lambda argv=None: "gate")
    def boom(mode, error=""):
        raise RuntimeError("x")
    monkeypatch.setattr(mods_screen, "_build_panel", boom)
    assert mods_screen.run_mods_screen(lambda p: None) == "boot"


def test_build_panel_passes_stock_classes_dict(monkeypatch):
    class _StockRec:
        def __init__(self, values):
            self.values = values

    stock_recs = [_StockRec({"title": "Galaxy", "era": "tng", "role": "explorer", "species": "federation"})]
    monkeypatch.setattr(mods_screen.ship_catalog, "incomplete_ships", lambda: [])
    monkeypatch.setattr(mods_screen.ship_catalog, "ships",
                        lambda source: stock_recs if source == "stock" else [])
    monkeypatch.setattr(mods_screen.ship_catalog, "species", lambda: [])

    captured = {}

    class _FakePanelCls:
        def __init__(self, mode, editable, readonly, *, species, stock_classes,
                     writer=None, suggest=None, error=""):
            captured["stock_classes"] = stock_classes

        @property
        def outcome(self):
            return None

    import engine.ui.mods_screen_panel as _panel_mod
    monkeypatch.setattr(_panel_mod, "ModsScreenPanel", _FakePanelCls)

    mods_screen._build_panel("home")

    assert isinstance(captured["stock_classes"], dict)
    assert captured["stock_classes"]["Galaxy"]["era"] == "tng"


class _FakePanel:
    def __init__(self):
        self._outcome = None

    @property
    def outcome(self):
        return self._outcome
