import pytest

from engine.quickbattle import scenario as sc
from engine.ship_catalog import CatalogEntry, Variant


def _ce(ship_id, title=None, playable=True, variants=(), species="Federation",
        role="tactical"):
    return CatalogEntry(
        ship_id=ship_id, icon=ship_id, source="stock", origins=(), title=title or ship_id,
        species=species, era=("DS9", "DS9"), role=role, playable=playable,
        variants=tuple(variants), missing=(), errors=(), raw_name=title or ship_id,
        raw_race=None)


GALAXY = _ce("Galaxy", variants=[Variant("USS Dauntless", registry="Dauntless"),
                                 Variant("USS Venture", registry="Venture")])
AKIRA = _ce("Akira", variants=[Variant("USS Geronimo", registry="Geronimo"),
                               Variant("USS Enterprise-X", script="EnterpriseX")])
WARBIRD = _ce("Warbird", species="Romulan")
STARBASE = _ce("FedStarbase", title="Fed Starbase", playable=False, role="station")
INDEX = sc.catalog_index([GALAXY, AKIRA, WARBIRD, STARBASE])


def test_catalog_index_is_case_insensitive():
    assert INDEX["galaxy"] is GALAXY and INDEX["fedstarbase"] is STARBASE


def test_resolve_variant():
    assert sc.resolve_variant(GALAXY, None).name == "USS Dauntless"
    assert sc.resolve_variant(GALAXY, "USS Venture").registry == "Venture"
    assert sc.resolve_variant(GALAXY, "USS Nope") is None
    assert sc.resolve_variant(WARBIRD, None) is None


def test_can_be_player_uses_variant_flag_then_entry_flag():
    assert sc.can_be_player(GALAXY, None)
    assert not sc.can_be_player(STARBASE, None)
    member = _ce("Defiant", variants=[Variant("Defiant"), Variant("Valiant", script="Valiant",
                                                                  playable=False)])
    assert sc.can_be_player(member, "Defiant")
    assert not sc.can_be_player(member, "Valiant")


def test_reconcile_drops_unknown_ship_and_variant_keeps_rest():
    s = sc.default_scenario()
    eg = s.groups[1]
    keep = s.add_ship(eg.id, "warbird")
    gone = s.add_ship(eg.id, "ModShipRemoved")
    named = s.add_ship(eg.id, "Galaxy")
    s.set_variant(named.id, "USS Removed")
    msgs = sc.reconcile(s, INDEX)
    assert [e.id for e in eg.entries] == [keep.id, named.id]
    assert named.variant is None
    assert len(msgs) == 2 and all(isinstance(m, str) for m in msgs)
    assert sc.reconcile(s, INDEX) == []


def test_reconcile_unknown_or_unplayable_player_becomes_galaxy():
    s = sc.default_scenario()
    s.set_player_ship("ModShipRemoved")
    assert sc.reconcile(s, INDEX)
    assert (s.player_entry().ship, s.player_entry().variant) == ("Galaxy", None)
    s.set_player_ship("FedStarbase")
    sc.reconcile(s, INDEX)
    assert s.player_entry().ship == "Galaxy"


def test_battle_plan_orders_names_registries_and_levels():
    s = sc.default_scenario()
    pg, eg = s.player_group(), s.groups[1]
    s.update_details(eg.id, "enemy", "port", "long", "high")
    esc = s.add_ship(pg.id, "Galaxy")           # escort, class default -> "USS Dauntless (2)"
    w = s.add_ship(eg.id, "Warbird")
    v = s.add_ship(eg.id, "Galaxy")
    s.set_variant(v.id, "USS Venture")
    x = s.add_ship(eg.id, "Akira")
    s.set_variant(x.id, "USS Enterprise-X")
    plan = sc.battle_plan(s, INDEX)

    assert plan.player == sc.PlayerOrder(ship_file="Galaxy", class_id="Galaxy",
                                         registry="Dauntless", display_name="USS Dauntless")
    ids = [o.entry_id for o in plan.orders]
    assert ids == [esc.id, w.id, v.id, x.id]
    o_esc, o_w, o_v, o_x = plan.orders
    assert (o_esc.allegiance, o_esc.direction, o_esc.distance_gu) == ("friendly", None, None)
    assert o_esc.display_name == "USS Dauntless (2)"
    assert o_esc.ai_level == 0.5
    assert (o_w.ship_file, o_w.registry, o_w.display_name, o_w.title) == \
        ("Warbird", None, None, "Warbird")
    assert o_w.direction == "port" and o_w.ai_level == 1.0
    assert o_w.distance_gu == pytest.approx(80.0 / 0.175)
    assert (o_v.registry, o_v.display_name) == ("Venture", "USS Venture")
    assert (o_x.ship_file, o_x.class_id, o_x.registry) == ("EnterpriseX", "Akira", None)


def test_class_default_registry_falls_back_to_bc_default_table():
    plain_galaxy = _ce("Galaxy", variants=[Variant("USS Dauntless")])
    plan = sc.battle_plan(sc.default_scenario(), sc.catalog_index([plain_galaxy]))
    assert plan.player.registry == "Dauntless"
