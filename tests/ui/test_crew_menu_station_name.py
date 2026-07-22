from engine.ui import crew_menu_hotkeys


class _FakeBridge:
    def __init__(self, mapping):
        self._m = mapping
    def GetObject(self, name):
        return self._m.get(name)


def test_station_name_for_matches_by_identity(monkeypatch):
    helm = object()
    tac = object()
    bridge = _FakeBridge({"Helm": helm, "Tactical": tac, "XO": None,
                          "Science": None, "Engineer": None})

    class _SM:
        def GetSet(self, n): return bridge if n == "bridge" else None

    import App
    monkeypatch.setattr(App, "g_kSetManager", _SM(), raising=False)
    monkeypatch.setattr(App, "CharacterClass_GetObject",
                        lambda pset, name: pset.GetObject(name), raising=False)

    assert crew_menu_hotkeys.station_name_for(helm) == "Helm"
    assert crew_menu_hotkeys.station_name_for(tac) == "Tactical"
    assert crew_menu_hotkeys.station_name_for(object()) is None
