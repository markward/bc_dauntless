"""QuickBattleSetupPanel: the Python-owned state machine over the scenario
and the ship catalog. Spec 2026-10-02-quickbattle-setup-screen-design.md §3."""
import json

import pytest

from engine.quickbattle import presets as presets_mod
from engine.quickbattle.stats import ShipStats
from engine.ship_catalog import CatalogEntry, Variant
from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel


def _ce(ship_id, title=None, playable=True, variants=(), species="Federation",
        role="tactical", era=("DS9", "DS9")):
    return CatalogEntry(ship_id=ship_id, icon=ship_id, source="stock", origins=(),
                        title=title or ship_id, species=species, era=era, role=role,
                        playable=playable, variants=tuple(variants), missing=(),
                        errors=(), raw_name=title or ship_id, raw_race=None)


CATALOG = [
    _ce("Galaxy", variants=[Variant("USS Dauntless", registry="Dauntless"),
                            Variant("USS Venture", registry="Venture")]),
    _ce("Sovereign", variants=[Variant("USS Sovereign", registry="Sovereign")]),
    _ce("Warbird", species="Romulan"),
    _ce("FedStarbase", title="Fed Starbase", playable=False, role="station"),
    _ce("Excelsior", era=("MOV", "MOV")),
]


class _Stats:
    def get(self, f): return ShipStats(1000.0, 2000.0)
    def maxima(self, entries): return (24000.0, 49500.0)
    def reset(self): pass


@pytest.fixture
def panel(tmp_path):
    p = QuickBattleSetupPanel(
        on_start=lambda: started.append(1), catalog_fn=lambda: list(CATALOG),
        presets=presets_mod.load_presets(tmp_path / "p.json"), stats=_Stats(),
        bio_fn=lambda ce: "bio", qb_module=None)
    p.open()
    return p


started = []


def _setup(p):
    out = p.render_payload() or ""
    for chunk in out.split(");"):
        if "setQuickBattleSetup(" in chunk:
            return json.loads(chunk.split("setQuickBattleSetup(", 1)[1])
    p.invalidate()
    return _setup(p)


def _enemy(p):
    return p.scenario.groups[1]


def test_initial_state(panel):
    s = _setup(panel)
    assert s["open"] and s["target"] == _enemy(panel).id
    assert s["eras"] == ["DS9"] and s["species"] == ["Federation"]
    assert not s["can_start"] and s["preset"] is None
    assert s["summary"] == "2 groups · 1 ship"


def test_catalog_push_has_stats_bios_and_tables(panel):
    out = panel.render_payload()
    cat = json.loads(out.split("setQuickBattleCatalog(", 1)[1].split(");", 1)[0])
    ids = [s["id"] for s in cat["ships"]]
    assert "Galaxy" in ids and cat["hull_max"] == 24000.0
    g = next(s for s in cat["ships"] if s["id"] == "Galaxy")
    assert (g["hull"], g["shields"], g["bio"]) == (1000.0, 2000.0, "bio")
    assert [v["name"] for v in g["variants"]] == ["USS Dauntless", "USS Venture"]


def test_add_to_target_and_start(panel):
    started.clear()
    panel.dispatch_event("add:Warbird")
    assert _setup(panel)["can_start"]
    panel.dispatch_event("start")
    assert started == [1] and not panel.is_open()


def test_add_names_group_and_quantity(panel):
    # The sheet's group picker and stepper: add:<ship>:<gid>:<n> appends n
    # entries to that group, whatever the current target.
    pid = panel.scenario.player_group().id
    assert panel.dispatch_event("add:Sovereign:%s:3" % pid)
    assert [e.ship for e in panel.scenario.player_group().entries[1:]] == ["Sovereign"] * 3
    assert _enemy(panel).entries == []
    assert _setup(panel)["target"] == pid             # the picker keeps its choice


def test_add_closes_the_ship_sheet(panel):
    panel.dispatch_event("select:Warbird")
    assert _setup(panel)["selected"] == "Warbird"
    assert panel.dispatch_event("add:Warbird:%s:2" % _enemy(panel).id)
    assert _setup(panel)["selected"] is None


@pytest.mark.parametrize("tail", [":nope:1", ":{gid}:0", ":{gid}:11", ":{gid}:x", ":{gid}:"])
def test_add_refuses_bad_group_or_quantity(panel, tail):
    panel.dispatch_event("select:Warbird")
    assert not panel.dispatch_event("add:Warbird" + tail.format(gid=_enemy(panel).id))
    assert _enemy(panel).entries == []
    assert _setup(panel)["selected"] == "Warbird"     # a refused add keeps the sheet


def test_set_player_refuses_unplayable(panel):
    panel.dispatch_event("set-player:FedStarbase")
    assert panel.scenario.player_entry().ship == "Galaxy"
    panel.dispatch_event("set-player:Sovereign")
    assert panel.scenario.player_entry().ship == "Sovereign"


def test_group_new_targets_it_and_delete_with_ships_confirms(panel):
    panel.dispatch_event("group-new")
    g = panel.scenario.groups[-1]
    assert _setup(panel)["target"] == g.id
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("group-delete:" + g.id)
    s = _setup(panel)
    assert s["confirm"]["ok"] == "Delete" and panel.scenario.group(g.id) is not None
    panel.dispatch_event("confirm")
    assert panel.scenario.group(g.id) is None
    assert _setup(panel)["target"] == _enemy(panel).id


def test_empty_group_deletes_without_confirm(panel):
    panel.dispatch_event("group-delete:" + _enemy(panel).id)
    s = _setup(panel)
    assert s["confirm"] is None and len(panel.scenario.groups) == 1
    assert s["target"] == panel.scenario.player_group().id


def test_details_draft_update_and_cancel(panel):
    gid = _enemy(panel).id
    panel.dispatch_event("details:" + gid)
    panel.dispatch_event("draft:allegiance:neutral")
    panel.dispatch_event("draft:difficulty:high")
    panel.dispatch_event("draft-cancel")
    assert _enemy(panel).allegiance == "enemy"
    panel.dispatch_event("details:" + gid)
    panel.dispatch_event("draft:allegiance:neutral")
    panel.dispatch_event("draft:difficulty:high")
    panel.dispatch_event("draft-update")
    assert (_enemy(panel).allegiance, _enemy(panel).difficulty) == ("neutral", "high")
    assert _setup(panel)["draft"] is None


def test_rename_variant_move_remove(panel):
    gid = _enemy(panel).id
    panel.dispatch_event("rename:%s:%s" % (gid, "Raiders%20One"))
    assert _enemy(panel).name == "Raiders One"
    panel.dispatch_event("add:Galaxy")
    e = _enemy(panel).entries[0]
    panel.dispatch_event("variant:%s:%s" % (e.id, "USS%20Venture"))
    assert e.variant == "USS Venture"
    panel.dispatch_event("variant:%s:" % e.id)
    assert e.variant is None
    panel.dispatch_event("move:%s:%s" % (e.id, panel.scenario.player_group().id))
    assert e in panel.scenario.player_group().entries
    panel.dispatch_event("remove:" + e.id)
    assert e not in panel.scenario.player_group().entries


def test_presets_save_overwrite_load_dirty_delete(panel):
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("preset-save:Alpha")
    s = _setup(panel)
    assert s["preset"] == "Alpha" and not s["dirty"] and s["presets"] == ["Alpha"]
    panel.dispatch_event("add:Warbird")
    assert _setup(panel)["dirty"]
    panel.dispatch_event("preset-save:Alpha")
    assert _setup(panel)["confirm"]["ok"] == "Overwrite"
    panel.dispatch_event("cancel")
    panel.dispatch_event("preset-load:Alpha")
    assert _setup(panel)["confirm"]["ok"] == "Load"
    panel.dispatch_event("confirm")
    assert len(_enemy(panel).entries) == 1 and not _setup(panel)["dirty"]
    panel.dispatch_event("preset-delete:Alpha")
    panel.dispatch_event("confirm")
    s = _setup(panel)
    assert s["presets"] == [] and s["preset"] is None


def test_preset_load_reconciles(panel, tmp_path):
    from engine.quickbattle import scenario as sc
    s = sc.default_scenario()
    s.add_ship(s.groups[1].id, "RemovedModShip")
    s.add_ship(s.groups[1].id, "Warbird")
    panel._presets.save("Old", s)
    panel.dispatch_event("preset-load:Old")
    assert [e.ship for e in _enemy(panel).entries] == ["Warbird"]


def test_filters_counts_out_of_era_and_selection_cleared(panel):
    panel.dispatch_event("add:Excelsior")
    s = _setup(panel)
    assert s["counts"]["Federation"] == 3       # Galaxy, Sovereign, Fed Starbase (DS9 only)
    row = _enemy(panel).entries[0]
    assert next(e for g in s["groups"] for e in g["entries"]
                if e["id"] == row.id)["out_of_era"]
    panel.dispatch_event("select:Galaxy")
    assert _setup(panel)["selected"] == "Galaxy"
    panel.dispatch_event("species:Federation")      # toggles Federation off
    assert _setup(panel)["selected"] is None


def test_esc_layers(panel):
    panel.dispatch_event("select:Galaxy")
    panel.dispatch_event("details:" + _enemy(panel).id)
    panel.dispatch_event("group-delete:" + _enemy(panel).id)  # empty -> deletes, no confirm
    panel.dispatch_event("esc")      # draft is gone with the group; closes the sheet
    assert _setup(panel)["selected"] is None
    panel.dispatch_event("esc")
    assert not panel.is_open()


def test_handle_key_esc_asks_the_page_first(panel):
    panel.render_payload()
    panel.handle_key_esc()
    assert (panel.render_payload() or "").startswith("qbEscape();")


def test_provider_and_unknown_verbs(panel):
    from engine.quickbattle import spawn
    panel.dispatch_event("add:Warbird")
    assert spawn.current_plan().orders[0].class_id == "Warbird"
    assert not panel.dispatch_event("nonsense")
    assert not panel.dispatch_event("remove:nope")


def test_closed_payload(panel):
    panel.close()
    assert '{"open": false}' in panel.render_payload()


# ── Behaviours the brief lists that the tests above do not pin ──────────────

def _make(tmp_path, catalog_fn, **kw):
    kw.setdefault("presets", presets_mod.load_presets(tmp_path / "p.json"))
    kw.setdefault("stats", _Stats())
    kw.setdefault("bio_fn", lambda ce: "bio")
    kw.setdefault("qb_module", None)
    p = QuickBattleSetupPanel(catalog_fn=catalog_fn, **kw)
    p.open()
    return p


def _group_payload(s, gid):
    return next(g for g in s["groups"] if g["id"] == gid)


def test_group_summaries_and_footer_pluralise(panel):
    s = _setup(panel)
    pg = panel.scenario.player_group()
    assert _group_payload(s, pg.id)["summary"] == "Friendly · escorts form up beside you"
    gid = _enemy(panel).id
    assert _group_payload(s, gid)["summary"] == "Enemy · Fore · Standard (35 km)"
    panel.dispatch_event("details:" + gid)
    panel.dispatch_event("draft:difficulty:high")
    panel.dispatch_event("draft:distance:out_of_range")
    panel.dispatch_event("draft-update")
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("add:Warbird")
    s = _setup(panel)
    assert _group_payload(s, gid)["summary"] == \
        "Enemy · Fore · Out of range (150 km) · High"
    assert s["summary"] == "2 groups · 3 ships"
    panel.dispatch_event("group-delete:" + gid)
    panel.dispatch_event("confirm")
    assert _setup(panel)["summary"] == "1 group · 1 ship"


def test_group_delete_confirm_copy(panel):
    gid = _enemy(panel).id
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("add:Galaxy")
    panel.dispatch_event("group-delete:" + gid)
    c = _setup(panel)["confirm"]
    assert c == {"title": "Delete group?", "name": "Enemy group",
                 "body": "Delete Enemy group and its 2 ships?", "ok": "Delete",
                 "before": "Delete ", "after": " and its 2 ships?"}
    panel.dispatch_event("cancel")
    assert _setup(panel)["confirm"] is None and panel.scenario.group(gid) is not None


def test_preset_confirm_copy(panel):
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("preset-save:Alpha")
    panel.dispatch_event("preset-save:Alpha")
    assert _setup(panel)["confirm"] == {
        "title": "Overwrite preset?", "name": "Alpha",
        "body": "A preset named Alpha already exists. Replace it with the current scenario?",
        "ok": "Overwrite", "before": "A preset named ",
        "after": " already exists. Replace it with the current scenario?"}
    panel.dispatch_event("cancel")
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("preset-load:Alpha")
    assert _setup(panel)["confirm"] == {
        "title": "Load preset?", "name": "Alpha",
        "body": "Your current setup has unsaved changes. Load Alpha anyway?",
        "ok": "Load", "before": "Your current setup has unsaved changes. Load ",
        "after": " anyway?"}
    panel.dispatch_event("cancel")
    panel.dispatch_event("preset-delete:Alpha")
    assert _setup(panel)["confirm"] == {
        "title": "Delete preset?", "name": "Alpha", "body": "Delete preset Alpha?",
        "ok": "Delete", "before": "Delete preset ", "after": "?"}


def test_confirm_splits_body_around_the_name_not_a_substring_of_it(panel):
    # A name that also occurs inside an earlier word ("set" in "setup") must
    # be bolded where the sentence names it: the page bolds `name` between
    # `before` and `after`, never by searching `body`.
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("preset-save:set")
    panel.dispatch_event("add:Warbird")                 # dirty -> load confirms
    panel.dispatch_event("preset-load:set")
    c = _setup(panel)["confirm"]
    assert c["before"] + c["name"] + c["after"] == c["body"]
    assert c["before"] == "Your current setup has unsaved changes. Load "
    panel.dispatch_event("cancel")
    gid = _enemy(panel).id
    panel.dispatch_event("group-delete:" + gid)
    c = _setup(panel)["confirm"]
    assert c["before"] + c["name"] + c["after"] == c["body"]


def test_preset_load_when_clean_needs_no_confirm(panel):
    from engine.quickbattle import scenario as sc
    s = sc.default_scenario()
    s.add_ship(s.groups[1].id, "Warbird")
    panel._presets.save("Beta", s)
    panel.dispatch_event("select:Galaxy")
    panel.dispatch_event("details:" + _enemy(panel).id)
    panel.dispatch_event("preset-load:Beta")       # default scenario is clean
    out = _setup(panel)
    assert out["confirm"] is None and out["preset"] == "Beta"
    assert out["draft"] is None and out["selected"] is None
    assert out["target"] == _enemy(panel).id


def test_era_toggle_counts_and_out_of_era(panel):
    panel.dispatch_event("add:Excelsior")
    panel.dispatch_event("era:MOV")
    s = _setup(panel)
    assert s["eras"] == ["MOV", "DS9"]
    assert s["counts"]["Federation"] == 4 and s["counts"]["Romulan"] == 1
    assert not s["groups"][1]["entries"][0]["out_of_era"]
    panel.dispatch_event("select:Galaxy")
    panel.dispatch_event("era:DS9")              # hides Galaxy -> selection cleared
    assert _setup(panel)["selected"] is None
    assert not panel.dispatch_event("era:NOPE")


def test_entry_payload_fields(panel):
    panel.dispatch_event("add:Galaxy")
    panel.dispatch_event("add:Warbird")
    s = _setup(panel)
    pe, g1, wb = (s["groups"][0]["entries"][0], s["groups"][1]["entries"][0],
                  s["groups"][1]["entries"][1])
    assert pe["player"] and pe["has_menu"]            # Galaxy has variants
    assert pe["variant_label"] == "USS Dauntless · class default"
    panel.dispatch_event("variant:%s:%s" % (g1["id"], "USS%20Venture"))
    g1 = _setup(panel)["groups"][1]["entries"][0]
    assert (g1["variant"], g1["variant_label"]) == ("USS Venture", "USS Venture")
    assert wb["variant_label"] is None and wb["has_menu"] and not wb["player"]
    assert wb["title"] == "Warbird" and wb["ship"] == "Warbird"


def test_player_variant_must_be_playable(tmp_path):
    cat = [_ce("Galaxy", variants=[Variant("USS Galaxy"),
                                   Variant("Galaxy Hulk", playable=False)])]
    p = _make(tmp_path, lambda: list(cat))
    pe = p.scenario.player_entry()
    assert not p.dispatch_event("variant:%s:%s" % (pe.id, "Galaxy%20Hulk"))
    assert pe.variant is None
    assert not p.dispatch_event("variant:%s:%s" % (pe.id, "Nope"))


def test_player_draft_edits_only_difficulty(panel):
    gid = panel.scenario.player_group().id
    panel.dispatch_event("details:" + gid)
    assert not panel.dispatch_event("draft:allegiance:enemy")
    assert panel.dispatch_event("draft:difficulty:low")
    panel.dispatch_event("draft-update")
    pg = panel.scenario.player_group()
    assert (pg.allegiance, pg.difficulty) == ("friendly", "low")


def test_unknown_ids_and_values_are_refused(panel):
    pg = panel.scenario.player_group().id
    for verb in ("add:NoSuchShip", "select:NoSuchShip", "set-player:NoSuchShip",
                 "target:nope", "details:nope", "group-delete:nope",
                 "group-delete:" + pg, "move:nope:" + pg, "variant:nope:",
                 "draft:difficulty:high",           # no draft open
                 "draft-update", "confirm", "species:Nope",
                 "preset-delete:NoSuchPreset", "preset-load:NoSuchPreset",
                 "preset-save:%20"):
        assert not panel.dispatch_event(verb), verb
    panel.dispatch_event("details:" + _enemy(panel).id)
    assert not panel.dispatch_event("draft:difficulty:extreme")
    assert not panel.dispatch_event("draft:colour:red")


def test_esc_pops_confirm_first(panel):
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("group-delete:" + _enemy(panel).id)
    panel.dispatch_event("esc")
    assert _setup(panel)["confirm"] is None and panel.is_open()


def test_dirty_without_preset_follows_can_start(panel):
    assert not _setup(panel)["dirty"]
    panel.dispatch_event("add:Warbird")
    assert _setup(panel)["dirty"]


def test_dirty_without_preset_catches_player_change_before_load(panel):
    # Spec D10: loading over unsaved changes asks first, even with no current
    # preset -- changing the player ship alone does not touch can_start().
    from engine.quickbattle import scenario as sc
    other = sc.default_scenario()
    other.add_ship(other.groups[1].id, "Warbird")
    panel._presets.save("Beta", other)
    assert not _setup(panel)["dirty"]          # a fresh panel is not dirty
    panel.dispatch_event("set-player:Sovereign")
    assert _setup(panel)["dirty"]
    panel.dispatch_event("preset-load:Beta")
    assert _setup(panel)["confirm"] is not None


def test_close_verb_closes(panel):
    assert panel.dispatch_event("close")
    assert not panel.is_open()


def test_start_refused_without_ships(panel):
    started.clear()
    panel.dispatch_event("start")
    assert started == [] and panel.is_open()


def test_catalog_payload_tables(panel):
    out = panel.render_payload()
    cat = json.loads(out.split("setQuickBattleCatalog(", 1)[1].split(");", 1)[0])
    assert [e["id"] for e in cat["eras"]][:2] == ["ENT", "TOS"]
    assert set(cat["eras"][0]) == {"id", "name", "tag", "start", "end"}
    assert [r["id"] for r in cat["roles"]] == ["tactical", "auxiliary", "station",
                                              "automated"]
    assert cat["species"][0]["name"] == "Federation"
    assert set(cat["species"][0]) == {"name", "insignia", "flagship_icon"}
    assert [d["id"] for d in cat["distances"]] == ["close", "standard", "long",
                                                   "out_of_range"]
    assert cat["distances"][1] == {"id": "standard", "label": "Standard", "km": 35.0}
    assert [d["id"] for d in cat["directions"]][0] == "fore"
    assert [d["id"] for d in cat["difficulties"]] == ["low", "medium", "high"]
    ex = next(s for s in cat["ships"] if s["id"] == "Excelsior")
    assert ex["era"] == ["MOV", "MOV"] and ex["role"] == "tactical"
    assert ex["species"] == "Federation" and ex["playable"] is True


def test_catalog_pushed_once_then_on_invalidate(panel):
    assert "setQuickBattleCatalog(" in panel.render_payload()
    panel.dispatch_event("add:Warbird")
    assert "setQuickBattleCatalog(" not in (panel.render_payload() or "")
    panel.invalidate()
    assert "setQuickBattleCatalog(" in panel.render_payload()


def test_catalog_generation_change_reconciles_and_resets(tmp_path, monkeypatch):
    from engine.quickbattle import bios
    cat = list(CATALOG)
    resets = []

    class Stats(_Stats):
        def reset(self): resets.append("stats")

    monkeypatch.setattr(bios, "reset", lambda: resets.append("bios"))
    p = _make(tmp_path, lambda: list(cat), stats=Stats())
    p.dispatch_event("add:Warbird")
    p.render_payload()
    resets.clear()
    cat[:] = [c for c in cat if c.ship_id != "Warbird"]
    out = p.render_payload()
    assert "setQuickBattleCatalog(" in out
    assert _enemy(p).entries == []
    assert sorted(resets) == ["bios", "stats"]


def test_default_catalog_filters_incomplete_and_skipped(monkeypatch):
    import dataclasses
    from engine import ship_catalog
    from engine.ui import quick_battle_setup_panel as mod
    bad = dataclasses.replace(_ce("Broken"), missing=("era",))
    monkeypatch.setattr(ship_catalog, "entries", lambda: list(CATALOG) + [bad])
    monkeypatch.setattr(ship_catalog, "skipped", lambda: frozenset({"warbird"}))
    ids = [e.ship_id for e in mod._default_catalog()]
    assert "Broken" not in ids and "Warbird" not in ids and "Galaxy" in ids


def test_no_arg_construction_registers_provider_lazily():
    from engine.quickbattle import spawn
    p = QuickBattleSetupPanel()
    assert spawn._provider == p.current_plan
    assert not p.is_open()


def test_current_plan_none_when_catalog_empty(tmp_path):
    p = _make(tmp_path, lambda: [])
    assert p.current_plan() is None


def test_changes_sync_the_sdk_outside_a_battle(tmp_path):
    """sync_sdk no longer writes g_sPlayerType (Mark's home-ship ruling,
    2026-10-02): outside a battle the player is always the home ship, picked
    at RecreatePlayer time, not ahead of it by the setup screen."""
    from types import SimpleNamespace
    qb = SimpleNamespace(bInSimulation=0, g_dFriendlyShipTypeToDetails={},
                         g_dEnemyShipTypeToDetails={}, g_kEnemyList=[],
                         g_kFriendList=[], g_sPlayerType=None)
    p = _make(tmp_path, lambda: list(CATALOG), qb_module=qb)
    p.dispatch_event("add:Warbird")
    assert qb.g_sPlayerType is None and [m[0] for m in qb.g_kEnemyList] == ["Warbird"]
    qb.bInSimulation = 1
    p.dispatch_event("add:Warbird")
    assert len(qb.g_kEnemyList) == 1             # no sync mid-battle


def test_closed_handle_key_esc_is_a_noop(panel):
    panel.close()
    panel.render_payload()
    panel.handle_key_esc()
    assert panel.render_payload() is None


def test_unplannable_scenario_does_not_break_dispatch(tmp_path):
    """No Galaxy in the catalog: reconcile's fallback player has no entry, so
    battle_plan raises. A verb must still be handled, not blow up the registry."""
    from types import SimpleNamespace
    qb = SimpleNamespace(bInSimulation=0, g_dFriendlyShipTypeToDetails={},
                         g_dEnemyShipTypeToDetails={}, g_kEnemyList=[],
                         g_kFriendList=[], g_sPlayerType=None)
    p = _make(tmp_path, lambda: [_ce("Warbird", species="Romulan")], qb_module=qb)
    assert p.dispatch_event("add:Warbird")


# ── Review fixes ────────────────────────────────────────────────────────────

def test_pending_confirm_blocks_other_verbs_and_cannot_hit_a_new_scenario(panel):
    """Reviewer repro: a group-delete confirm pending, then a clean preset
    load, then confirm, deleted the LOADED preset's group."""
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("preset-save:A")
    gid = _enemy(panel).id
    panel.dispatch_event("group-delete:" + gid)
    assert not panel.dispatch_event("preset-load:A")
    assert not panel.dispatch_event("add:Warbird")
    assert not panel.dispatch_event("group-new")
    assert len(_enemy(panel).entries) == 2 and _setup(panel)["confirm"] is not None
    panel.dispatch_event("cancel")
    assert panel.dispatch_event("preset-load:A")
    assert panel.dispatch_event("confirm") is False     # nothing pending any more
    assert len(panel.scenario.groups) == 2


def test_close_drops_pending_confirm_and_draft(panel):
    panel.dispatch_event("details:" + _enemy(panel).id)
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("draft-cancel")
    panel.dispatch_event("details:" + _enemy(panel).id)
    panel.close()
    panel.open()
    assert _setup(panel)["draft"] is None
    panel.dispatch_event("group-delete:" + _enemy(panel).id)
    panel.close()
    panel.open()
    s = _setup(panel)
    assert s["confirm"] is None
    assert not panel.dispatch_event("confirm")
    assert len(panel.scenario.groups) == 2


def test_catalog_change_syncs_the_sdk(tmp_path):
    """sync_sdk no longer writes g_sPlayerType (Mark's home-ship ruling,
    2026-10-02) -- only the manifests/XO-start sync fires on a catalog
    change."""
    from types import SimpleNamespace
    cat = list(CATALOG)
    qb = SimpleNamespace(bInSimulation=0, g_dFriendlyShipTypeToDetails={},
                         g_dEnemyShipTypeToDetails={}, g_kEnemyList=[],
                         g_kFriendList=[], g_sPlayerType=None)
    p = _make(tmp_path, lambda: list(cat), qb_module=qb)
    p.dispatch_event("add:Warbird")
    assert [m[0] for m in qb.g_kEnemyList] == ["Warbird"]
    cat[:] = [c for c in cat if c.ship_id not in ("Warbird", "Galaxy")]
    p.render_payload()
    assert qb.g_kEnemyList == [] and qb.g_sPlayerType is None


def test_set_player_never_raises_out_of_dispatch(panel, monkeypatch):
    def boom(ship):
        raise RuntimeError("scenario broke")
    monkeypatch.setattr(panel.scenario, "set_player_ship", boom)
    assert panel.dispatch_event("set-player:Sovereign") is False


def test_unplayable_catalog_plan_falls_back_to_bc(tmp_path):
    from engine.quickbattle import spawn
    p = _make(tmp_path, lambda: [_ce("FedStarbase", playable=False)])
    assert not p.dispatch_event("set-player:FedStarbase")
    assert spawn._provider == p.current_plan
    assert spawn.current_plan() is None            # ValueError -> BC's fallback


def test_dirty_does_not_reload_the_preset_every_frame(panel):
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("preset-save:Alpha")
    calls = []
    real = panel._presets.load
    panel._presets.load = lambda name: calls.append(name) or real(name)
    for _ in range(3):
        panel.invalidate()
        assert not _setup(panel)["dirty"]
    panel.dispatch_event("add:Warbird")
    assert _setup(panel)["dirty"]
    assert calls == []
    panel.dispatch_event("preset-delete:Alpha")
    panel.dispatch_event("confirm")
    assert _setup(panel)["dirty"]                      # no preset -> can_start


def test_panel_is_throttled_but_events_still_bypass(panel):
    assert 0.0 < panel.poll_interval_s <= 0.1
    panel.consume_due()
    panel.dispatch_event("add:Warbird")                # registry marks due itself;
    panel.handle_key_esc()                             # esc marks due here
    assert panel.consume_due()
