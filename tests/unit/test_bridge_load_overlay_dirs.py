"""Bridge PBR: the bridge is loaded with the replacements overlay as its
sibling-map directory (spec 2026-10-08-bridge-emitters §9.2)."""
from engine import host_loop


def test_overlay_dirs_are_the_replacements_dirs_for_the_texture_rel(monkeypatch):
    class Rep:
        def dirs_for(self, rel):
            assert rel == "data/Models/Sets/DBridge/High"
            return ["/proj/native/assets/replacements/data/Models/Sets/DBridge/High"]

    monkeypatch.setattr(host_loop._mods, "replacements", lambda: Rep())
    assert host_loop._bridge_overlay_dirs("data/Models/Sets/DBridge/High") == [
        "/proj/native/assets/replacements/data/Models/Sets/DBridge/High"]


def test_no_overlay_files_means_no_overlay_dirs(monkeypatch):
    class Rep:
        def dirs_for(self, rel):
            return []

    monkeypatch.setattr(host_loop._mods, "replacements", lambda: Rep())
    assert host_loop._bridge_overlay_dirs("x") == []
