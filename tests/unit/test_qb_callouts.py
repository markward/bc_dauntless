"""Spec 2026-10-22 warp-in §6.7: which Incoming line the tactical officer says."""
import pytest

from engine.quickbattle import late_arrivals as la


@pytest.mark.parametrize("n,already,key", [
    (0, False, None), (0, True, None),
    (1, True, "Incoming6"), (4, True, "Incoming6"),
    (1, False, "Incoming1"), (2, False, "Incoming2"),
    (3, False, "Incoming3"), (4, False, "Incoming4"),
    (5, False, "Incoming5"), (9, False, "Incoming5"),
])
def test_enemy_callout_key(n, already, key):
    assert la.enemy_callout_key(n, already) == key


def test_other_key():
    assert la.OTHER_CALLOUT_KEY == "gs025"


class _Char:
    def __init__(self, db):
        self._db = db

    def GetDatabase(self):
        return self._db


class _QB:
    def __init__(self, tact, general):
        self.g_pTact = tact
        self.g_pSci = None
        self.g_pGeneralDatabase = general


class _Seq:
    def AddAction(self, a):
        pass

    def Play(self):
        pass


@pytest.fixture
def spoken(monkeypatch):
    import App
    calls = []

    def spy(char, kind, key, set_name, flag, db, *rest):
        calls.append((char, key, db))
        return object()

    monkeypatch.setattr(App, "CharacterAction_Create", spy)
    monkeypatch.setattr(App, "TGSequence_Create", lambda: _Seq())
    la._callout_warned.clear()
    yield calls
    la._callout_warned.clear()


def test_own_database_passes_none(spoken):
    felix = _Char(object())
    la.callout(_QB(felix, object()), {"enemy": 2}, False)
    assert spoken == [(felix, "Incoming2", None)]


def test_no_own_database_uses_general(spoken):
    general = object()
    felix = _Char(None)
    la.callout(_QB(felix, general), {"enemy": 2}, False)
    assert len(spoken) == 1 and spoken[0][2] is general


def test_no_database_at_all_says_nothing_and_warns(spoken, caplog):
    la.callout(_QB(_Char(None), None), {"enemy": 2}, False)
    assert spoken == []
    assert "no database for g_pTact" in caplog.text


def test_reset_clears_warn_once():
    la._callout_warned.add("x")
    la.reset()
    assert la._callout_warned == set()
