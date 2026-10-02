"""Scenario model: defaults, invariants, edits, JSON round-trip.
Spec: docs/superpowers/specs/2026-10-02-quickbattle-setup-screen-design.md §2"""
import pytest

from engine.quickbattle import scenario as sc


def test_default_scenario_has_player_group_and_empty_enemy_group():
    s = sc.default_scenario()
    assert [g.name for g in s.groups] == ["Friendly group", "Enemy group"]
    pg = s.player_group()
    assert pg.player and pg.allegiance == "friendly"
    assert pg.direction is None and pg.distance is None
    assert [(e.ship, e.player) for e in pg.entries] == [("Galaxy", True)]
    eg = s.groups[1]
    assert (eg.allegiance, eg.direction, eg.distance, eg.difficulty) == \
        ("enemy", "fore", "standard", "medium")
    assert eg.entries == []
    assert not s.can_start()


def test_ids_are_unique_strings():
    s = sc.default_scenario()
    ids = [g.id for g in s.groups] + [e.id for g in s.groups for e in g.entries]
    assert len(set(ids)) == len(ids) and all(isinstance(i, str) and i for i in ids)


def test_add_group_is_enemy_fore_standard_with_first_free_number():
    s = sc.default_scenario()
    g2 = s.add_group()
    g3 = s.add_group()
    assert (g2.allegiance, g2.direction, g2.distance, g2.difficulty) == \
        ("enemy", "fore", "standard", "medium")
    assert g2.name == "Enemy group 2" and g3.name == "Enemy group 3"
    s.delete_group(g2.id)
    assert s.add_group().name == "Enemy group 2"


def test_player_group_cannot_be_deleted_and_player_entry_cannot_move_or_go():
    s = sc.default_scenario()
    pg, pe = s.player_group(), s.player_entry()
    assert not s.delete_group(pg.id)
    assert not s.remove_entry(pe.id)
    assert not s.move_entry(pe.id, s.groups[1].id)
    assert s.player_entry() is pe


def test_add_move_remove_entries_and_can_start():
    s = sc.default_scenario()
    eg = s.groups[1]
    e = s.add_ship(eg.id, "Warbird")
    assert e is not None and s.can_start()
    g2 = s.add_group()
    assert s.move_entry(e.id, g2.id)
    assert eg.entries == [] and g2.entries[-1] is e
    assert s.remove_entry(e.id) and not s.can_start()
    assert s.add_ship("nope", "Warbird") is None


def test_escort_counts_for_can_start():
    s = sc.default_scenario()
    s.add_ship(s.player_group().id, "Akira")
    assert s.can_start()


def test_update_details_follows_allegiance_when_name_unedited():
    s = sc.default_scenario()
    eg = s.groups[1]
    assert s.update_details(eg.id, "neutral", "port", "close", "high")
    assert (eg.allegiance, eg.direction, eg.distance, eg.difficulty) == \
        ("neutral", "port", "close", "high")
    assert eg.name == "Neutral group"
    s.rename_group(eg.id, "Bystanders")
    s.update_details(eg.id, "enemy", "port", "close", "high")
    assert eg.name == "Bystanders" and eg.custom_name


def test_update_details_rejects_bad_values():
    s = sc.default_scenario()
    eg = s.groups[1]
    assert not s.update_details(eg.id, "hostile", "fore", "standard", "medium")
    assert not s.update_details(eg.id, "enemy", "up", "standard", "medium")
    assert not s.update_details(eg.id, "enemy", "fore", "far", "medium")
    assert not s.update_details(eg.id, "enemy", "fore", "standard", "insane")
    assert eg.allegiance == "enemy"


def test_player_group_details_change_only_difficulty():
    s = sc.default_scenario()
    pg = s.player_group()
    assert s.update_details(pg.id, "enemy", "aft", "long", "low")
    assert (pg.allegiance, pg.direction, pg.distance, pg.difficulty) == \
        ("friendly", None, None, "low")


def test_rename_ignores_empty_and_unchanged():
    s = sc.default_scenario()
    eg = s.groups[1]
    assert not s.rename_group(eg.id, "   ")
    assert not s.rename_group(eg.id, "Enemy group")
    assert not eg.custom_name
    assert s.rename_group(eg.id, "  Raiders ")
    assert eg.name == "Raiders" and eg.custom_name


def test_set_player_ship_swaps_in_place_and_resets_variant():
    s = sc.default_scenario()
    pe = s.player_entry()
    s.set_variant(pe.id, "USS Venture")
    s.set_player_ship("Sovereign")
    assert s.player_entry() is pe
    assert (pe.ship, pe.variant) == ("Sovereign", None)


def test_json_round_trip_and_same_setup_ignores_ids():
    s = sc.default_scenario()
    s.add_ship(s.groups[1].id, "Warbird")
    d = s.to_json()
    t = sc.from_json(d)
    assert sc.same_setup(s, t)
    assert t.to_json() == d
    other = sc.default_scenario()
    other.add_ship(other.groups[1].id, "Warbird")
    assert sc.same_setup(s, other)            # different ids, same setup
    other.groups[1].difficulty = "high"
    assert not sc.same_setup(s, other)


@pytest.mark.parametrize("mutate", [
    lambda d: d["groups"].clear(),
    lambda d: d["groups"][0].update(player=False),
    lambda d: d["groups"][1]["entries"].append(
        {"id": "x", "ship": "Akira", "variant": None, "player": True}),
    lambda d: d["groups"][1].update(allegiance="hostile"),
    lambda d: d["groups"][0].update(allegiance="enemy"),
])
def test_from_json_rejects_broken_invariants(mutate):
    d = sc.default_scenario().to_json()
    mutate(d)
    with pytest.raises(ValueError):
        sc.from_json(d)


def test_first_non_player_group():
    s = sc.default_scenario()
    assert s.first_non_player_group() is s.groups[1]
    s.delete_group(s.groups[1].id)
    assert s.first_non_player_group() is None
